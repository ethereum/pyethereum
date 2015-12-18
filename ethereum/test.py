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
from bet import call_method, casper_ct, defaultBetStrategy, bet_incentivizer_code, bet_incentivizer_ct, Bet
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
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace'
# configure_logging(config_string=config_string)

# Generate 6 keys
keys = [zpad(encode_int(x), 32) for x in range(1, 7)]
# Create a second set of 2 keys
secondkeys = [zpad(encode_int(x), 32) for x in range(13, 15)]
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
    txdata3 = bet_incentivizer_ct.encode('setGasprice', [index, 1])
    tx = ecdsa_accounts.mk_transaction(2, 1, 1000000, BET_INCENTIVIZER, 0, txdata3, k, True)
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
# Minimum max finalized height
min_mfh = -1

# Transactions to status report on
check_txs = []

# Function to check consistency between everything
def check_correctness(bets):
    global min_mfh
    print '#'*80
    # List of peers of each node
    print 'Peers: %r' % {bet.id: map(lambda x: x.id, n.peers[bet.id]) for bet in bets}
    # Max finalized heights for each bettor strategy
    mfhs = [bet.my_max_finalized_height for bet in bets]
    print 'Max finalized heights: %r' % mfhs
    # Induction heights of each validator
    print 'Registered induction heights: %r' % [[op.induction_height for op in bet.opinions.values()] for bet in bets]
    # Withdrawn?
    print 'Withdrawn according to self?: %r' % [(bet.withdrawn, bet.seq) for bet in bets]
    print 'Withdrawn according to others?: %r' % [[(op.withdrawn, op.seq) for op in bet.opinions.values()] for bet in bets]
    # Probabilities of each validator on all of the blocks so far
    print 'Probs: %r' % [[float('%.5f' % p) for p in bet.probs] for bet in bets]
    # Data about bets from each validator according to every other validator
    print 'Bets processed by each validator according to each validator: %r' % [[(op.seq, len(bet.bets[op.index]), bet.highest_bet_processed[op.index], op.max_height) for op in bet.opinions.values()] for bet in bets]
    # Indices of validators
    print 'Indices: %r' % [bet.index for bet in bets]
    # Number of blocks received by each validator
    print 'Blocks received: %r' % [len(bet.blocks) for bet in bets]
    # Number of blocks received by each validator
    print 'Blocks missing: %r' % [[h for h in range(len(bet.blocks)) if not bet.blocks[h]] for bet in bets]
    # Makes sure all block hashes for all heights up to the minimum finalized
    # height are the same
    print 'Verifying finalized block hash equivalence'
    new_min_mfh = min(mfhs)
    for j in range(1, len(bets)):
        j_hashes = bets[j].finalized_hashes[:(new_min_mfh+1)]
        jm1_hashes = bets[j-1].finalized_hashes[:(new_min_mfh+1)]
        assert j_hashes == jm1_hashes, (j_hashes, jm1_hashes)
    # Checks state roots for finalized heights and makes sure that they are
    # consistent
    print 'Verifying finalized state root correctness'
    state = State(genesis.root if min_mfh < 0 else bets[0].stateroots[min_mfh], OverlayDB(bets[0].db))
    for i in range(min_mfh + 1, new_min_mfh + 1):
        block = bets[j].objects[bets[0].finalized_hashes[i]] if j_hashes[i] != '\x00' * 32 else None
        block_state_transition(state, block)
        if state.root != bets[0].stateroots[i]:
            sys.stderr.write('State root mismatch at block %d!\n' % i)
            sys.stderr.write('bet 0 stateroots %r\n' % bets[0].stateroots[:(i+1)])
            sys.stderr.write('bet 0 blocks %r\n' % [x.hash if x else None for x in bets[0].blocks[:(i+1)]])
            sys.stderr.write('%r\n' % bets[j].stateroots[:(i+1)])
            sys.stderr.write('%r\n' % [x.hash if x else None for x in bets[j].blocks[:(i+1)]])
            raise Exception(" ")
    min_mfh = new_min_mfh
    print 'Min common finalized height: %d, integrity checks passed' % new_min_mfh
    # Last and next blocks to propose by each validator
    print 'Last block created: %r' % [bet.last_block_produced for bet in bets]
    print 'Next blocks to create: %r' % [bet.next_block_to_produce for bet in bets]
    # Assert equivalence of proposer lists
    min_proposer_length = min([len(bet.proposers) for bet in bets])
    for i in range(1, len(bets)):
        assert bets[i].proposers[:min_proposer_length] == bets[0].proposers[:min_proposer_length]
    # Validator sequence numbers as seen by themselves
    print 'Validator seqs online: %r' % {bet.index: bet.seq for bet in bets}
    # Validator sequence numbers as recorded in the chain
    print 'Validator seqs on finalized chain: %r' % {bet.index: call_method(state, CASPER, ct, 'getUserSeq', [bet.index if bet.index >= 0 else bet.former_index]) for bet in bets}
    h = 0
    while h < len(bets[0].stateroots) and bets[0].stateroots[h] not in (None, '\x00' * 32):
        h += 1
    speculative_state = State(bets[0].stateroots[h-1] if h else genesis.root, OverlayDB(bets[0].db))
    print 'Validator seqs on speculative chain: %r' % {bet.index: call_method(speculative_state, CASPER, ct, 'getUserSeq', [bet.index if bet.index >= 0 else bet.former_index]) for bet in bets}
    # Validator deposit sizes (over 1500 * 10**18 means profit)
    print 'Validator deposit sizes: %r' % [call_method(state, CASPER, ct, 'getUserDeposit', [bet.index]) for bet in bets if bet.index >= 0]
    # Account signing nonces
    print 'Account signing nonces: %r' % [big_endian_to_int(state.get_storage(bet.addr, encode_int32(2**256 - 1))) for bet in bets]
    # Transaction status
    print 'Transaction status in unconfirmed_txindex: %r' % [bets[0].unconfirmed_txindex.get(tx.hash, None) for tx in check_txs]
    print 'Transaction status in finalized_txindex: %r' % [bets[0].finalized_txindex.get(tx.hash, None) for tx in check_txs]
    print 'Transaction exceptions: %r' % [bets[0].tx_exceptions.get(tx.hash, 0) for tx in check_txs]

# Simulate a network
n = network.NetworkSimulator(latency=4, agents=bets, broadcast_success_rate=0.9)
n.generate_peers(5)
for bet in bets:
    bet.network = n
# Keep running until the min finalized height reaches 12
while 1:
    n.run(100, sleep=0.2)
    check_correctness(bets)
    if min_mfh >= 12:
        print 'Reached breakpoint'
        break
    print 'Min mfh:', min_mfh
    print 'Peer lists:', [[p.id for p in n.peers[bet.id]] for bet in bets]

# Create transactions for a few new validators to join
print '#' * 80 + '\n' + '#' * 80
print 'Generating transactions to include new validators'
for i, k in enumerate(secondkeys):
    index = len(keys) + i
    # Make their validation code
    vcode = ecdsa_accounts.mk_validation_code(k)
    # Make the transaction to join as a Casper validator
    txdata = ct.encode('join', [vcode])
    tx = ecdsa_accounts.mk_transaction(0, 1, 1000000, CASPER, 1500 * 10**18, txdata, k, create=True)
    print 'Making transaction: ', tx.hash.encode('hex')
    # Make the transaction to send some ether to the bet inclusion
    # incentivization contract
    txdata2 = bet_incentivizer_ct.encode('deposit', [index])
    tx2 = ecdsa_accounts.mk_transaction(1, 1, 1000000, BET_INCENTIVIZER, 1 * 10**18, txdata2, k, True)
    # And set my gasprice to 1
    txdata3 = bet_incentivizer_ct.encode('setGasprice', [index, 1])
    tx3 = ecdsa_accounts.mk_transaction(2, 1, 1000000, BET_INCENTIVIZER, 0, txdata3, k, True)
    bets[0].add_transaction(tx)
    bets[0].add_transaction(tx2)
    bets[0].add_transaction(tx3)
    check_txs.extend([tx, tx2, tx3])

# Keep running until the min finalized height reaches 42. We expect that by
# this time all transactions from the previous phase have been included
while 1:
    n.run(100, sleep=0.2)
    check_correctness(bets)
    if min_mfh > 42:
        print 'Reached breakpoint'
        break
    print 'Min mfh:', min_mfh

# Create bet objects for the new validators
state = State(genesis.root, bets[0].db)
secondbets = [defaultBetStrategy(state.clone(), k) for k in secondkeys]
for bet in secondbets:
    bet.network = n
n.agents.extend(secondbets)
n.generate_peers(5)
print 'Increasing number of peers in the network to %d!' % len(keys + secondkeys)
recent_state = State(bets[0].stateroots[min_mfh], bets[0].db)
# Check that all signups are successful
assert call_method(recent_state, CASPER, casper_ct, 'getValidatorSignups', []) == len(keys + secondkeys)
print 'All new validators inducted'
print 'Induction heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserInductionHeight', [i]) for i in range(len(keys + secondkeys))]

# Keep running until the min finalized height reaches ~120. We expect that by
# this time all validators will be actively betting off of each other's bets
while 1:
    n.run(100, sleep=0.2)
    check_correctness(bets)
    print 'Min mfh:', min_mfh
    print 'Induction heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserInductionHeight', [i]) for i in range(len(keys + secondkeys))]
    if min_mfh > 60 + ENTER_EXIT_DELAY:
        print 'Reached breakpoint'
        break

# Create transactions for old validators to leave
print '#' * 80 + '\n' + '#' * 80
print 'Generating transactions to withdraw some validators'
for bet in bets[:3]:
    bet.withdraw()


# Keep running until the min finalized height reaches ~160.
while 1:
    n.run(120, sleep=0.2)
    check_correctness(bets)
    print 'Min mfh:', min_mfh
    print 'Withdrawal heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserWithdrawalHeight', [i]) for i in range(len(keys + secondkeys))]
    if min_mfh > 100 + ENTER_EXIT_DELAY:
        print 'Reached breakpoint'
        break

recent_state = State(bets[0].stateroots[min_mfh], bets[0].db)
# Check that the only remaining active validators are the ones that have not
# yet signed out.
print [call_method(recent_state, CASPER, casper_ct, 'getUserStatus', [i]) for i in range(8)]
assert len([i for i in range(8) if call_method(recent_state, CASPER, casper_ct, 'getUserStatus', [i]) == 2]) == len(keys + secondkeys) - 3
