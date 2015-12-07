from serenity_blocks import State, tx_state_transition, mk_contract_address, block_state_transition
from serenity_transactions import Transaction
from db import EphemDB, OverlayDB
import serpent
from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GAS_CONSUMED, GASLIMIT, NULL_SENDER, ETHER, ECRECOVERACCT, RNGSEEDS, GENESIS_TIME, ENTER_EXIT_DELAY, BET_INCENTIVIZER
from utils import privtoaddr, normalize_address, zpad, encode_int, big_endian_to_int, encode_int32
import ecdsa_accounts
import abi
import sys
import bet
from bet import call_method, casper_ct, defaultBetStrategy, bet_incentivizer_code, bet_incentivizer_ct
import time
import network
import os

genesis = State('', EphemDB())
gc = genesis.clone()
# Unleash the kraken....err, I mean casper
casper_file = os.path.join(os.path.split(__file__)[0], 'casper.se.py')
code = serpent.compile(casper_file)
tx_state_transition(gc, Transaction(None, 1000000, '', code))
genesis.set_storage(CASPER, '', gc.get_storage(mk_contract_address(code=code), ''))
ct = abi.ContractTranslator(serpent.mk_full_signature(casper_file))
# Add the bet incentivizer
code2 = serpent.compile(bet_incentivizer_code)
tx_state_transition(gc, Transaction(None, 1000000, '', code2))
genesis.set_storage(BET_INCENTIVIZER, '', gc.get_storage(mk_contract_address(code=code2), ''))

# Get the code for the basic ecrecover account
genesis.set_storage(ECRECOVERACCT, '', ecdsa_accounts.constructor_code)
    
# We might want logging
# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace'
# configure_logging(config_string=config_string)

# Generate 8 keys
keys = [zpad(encode_int(x), 32) for x in range(1, 7)]
# Create a second set of 3 keys
secondkeys = [zpad(encode_int(x), 32) for x in range(13, 16)]
# Initialize the first keys
for i, k in enumerate(keys):
    # Generate the address
    a = ecdsa_accounts.privtoaddr(k)
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 0
    # Give them 1600 ether
    genesis.set_storage(ETHER, a, 1600 * 10**18)
    # Make a dummy transaction to initialize the account
    # tx = ecdsa_accounts.mk_transaction(0, 1, 1000000, CASPER, 0, '', k, create=True)
    # v = tx_state_transition(genesis, tx)
    # assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 1
    # Make their validation code
    vcode = ecdsa_accounts.mk_validation_code(k)
    print 'Length of validation code:', len(vcode)
    # Make the transaction to join as a Casper validator
    txdata = ct.encode('join', [vcode])
    print 'Length of account code:', len(genesis.get_storage(a, ''))
    tx = ecdsa_accounts.mk_transaction(0, 1, 1000000, CASPER, 1500 * 10**18, txdata, k, True)
    v = tx_state_transition(genesis, tx)
    index = ct.decode('join', ''.join(map(chr, v)))[0]
    print 'Joined with index', index
    # Check sequence number
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 1
    # Check that we actually joined Casper with the right
    # validation code
    vcode2 = call_method(genesis, CASPER, ct, 'getUserValidationCode', [index])
    assert vcode2 == vcode
    # Make the transaction to send some ether to the bet inclusion
    # incentivization contract
    txdata2 = bet_incentivizer_ct.encode('deposit', [index])
    tx = ecdsa_accounts.mk_transaction(1, 1, 1000000, BET_INCENTIVIZER, 1 * 10**18, txdata2, k, True)
    v = bet_incentivizer_ct.decode('deposit', ''.join(map(chr, tx_state_transition(genesis, tx))))[0]
    assert v is True
    # And set my gasprice to 1
    txdata2 = bet_incentivizer_ct.encode('setGasprice', [index, 1])
    tx = ecdsa_accounts.mk_transaction(2, 1, 1000000, BET_INCENTIVIZER, 0, txdata2, k, True)
    v = bet_incentivizer_ct.decode('setGasprice', ''.join(map(chr, tx_state_transition(genesis, tx))))[0]
    assert v is True

# Give the secondary keys some ether as well
for i, k in enumerate(secondkeys):
    # Generate the address
    a = ecdsa_accounts.privtoaddr(k)
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 0
    # Give them 1600 ether
    genesis.set_storage(ETHER, a, 1600 * 10**18)

# Set the starting RNG seed to equal to the number of casper validators
# in genesis
genesis.set_storage(RNGSEEDS, encode_int32(2**256 - 1), genesis.get_storage(CASPER, 0))
# Set the genesis timestamp
genesis.set_storage(GENESIS_TIME, encode_int32(0), int(time.time() + 5))
# Create betting strategy objects for every validator
bets = [defaultBetStrategy(genesis.clone(), k) for k in keys]

def check_correctness(bets):
    mfhs = [bet.my_max_finalized_height for bet in bets]
    print '#'*80
    print 'Peers: %r' % [map(lambda x: x.id, n.peers[bet.id]) for bet in bets]
    print 'Max finalized heights: %r' % mfhs
    # print 'Bets received: %r' % [[len(bet.bets[bet2.id] if bet2.id >= 0 else []) for bet2 in bets] for bet in bets]
    print 'Registered induction heights: %r' % [[op.induction_height for op in bet.opinions.values()] for bet in bets]
    print 'Registered withdrawal heights: %r' % [[op.withdrawal_height for op in bet.opinions.values()] for bet in bets]
    print 'Probs: %r' % [[float('%.5f' % p) for p in bet.probs] for bet in bets]
    print 'Probs in opinions: %r' % [[(op.seq, len(bet.bets[op.index]), bet.highest_bet_processed[op.index], op.max_height) for op in bet.opinions.values()] for bet in bets]
    print 'Indices: %r' % [bet.index for bet in bets]
    print 'Blocks received: %r' % [len(bet.blocks) for bet in bets]
    print 'Verifying finalized block hash equivalence'
    global min_mfh
    min_mfh = min(mfhs)
    for j in range(1, len(bets)):
        j_hashes = bets[j].finalized_hashes[:(min_mfh+1)]
        jm1_hashes = bets[j-1].finalized_hashes[:(min_mfh+1)]
        assert j_hashes == jm1_hashes, (j_hashes, jm1_hashes)
    print 'Verifying finalized state root correctness'
    state = State(bets[0].stateroots[0], OverlayDB(bets[0].db))
    for i in range(1, min_mfh + 1):
        block = bets[j].objects[bets[0].finalized_hashes[i]] if j_hashes[i] != '\x00' * 32 else None
        block_state_transition(state, block)
        assert state.root == bets[0].stateroots[i], (i, state.root, bets[0].stateroots[i])
    print 'Min common finalized height: %d, integrity checks passed' % min_mfh

# Simulate a network
n = network.NetworkSimulator(latency=4, agents=bets, broadcast_success_rate=0.9)
n.generate_peers(5)
for bet in bets:
    bet.network = n
min_mfh = 0
while 1:
    n.run(100, sleep=0.2)
    check_correctness(bets)
    if min_mfh >= 12:
        print 'Reached breakpoint'
        break
    print 'Min mfh:', min_mfh
    print 'Peer lists:', [[p.id for p in n.peers[bet.id]] for bet in bets]

# Create transactions for old validators to leave and new ones to join
print '#' * 80 + '\n' + '#' * 80
print 'Generating transactions to include new validators'
for k in secondkeys:
    # Make their validation code
    vcode = ecdsa_accounts.mk_validation_code(k)
    # Make the transaction to join as a Casper validator
    txdata = ct.encode('join', [vcode])
    tx = ecdsa_accounts.mk_transaction(0, 1, 1000000, CASPER, 1500 * 10**18, txdata, k, create=True)
    print 'Making transaction: ', tx.hash.encode('hex')
    bets[0].add_transaction(tx)

while 1:
    n.run(100, sleep=0.2)
    check_correctness(bets)
    if min_mfh > 36:
        print 'Reached breakpoint'
        break
    print 'Min mfh:', min_mfh

state = State(genesis.root, bets[0].db)
secondbets = [defaultBetStrategy(state.clone(), k) for k in secondkeys]
for bet in secondbets:
    bet.network = n
n.agents.extend(secondbets)
n.generate_peers(5)
print 'Increasing number of peers in the network to %d!' % len(keys + secondkeys)
recent_state = State(bets[0].stateroots[min_mfh], bets[0].db)
assert call_method(recent_state, CASPER, casper_ct, 'getNextUserId', []) == len(keys + secondkeys)
print 'All new validators inducted'
print 'Induction heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserInductionHeight', [i]) for i in range(len(keys + secondkeys))]

while 1:
    n.run(100, sleep=0.2)
    check_correctness(bets)
    print 'Min mfh:', min_mfh
    print 'Induction heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserInductionHeight', [i]) for i in range(len(keys + secondkeys))]
    if min_mfh > 60 + ENTER_EXIT_DELAY:
        print 'Reached breakpoint'
        break
