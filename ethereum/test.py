from serenity_blocks import State, tx_state_transition, mk_contract_address, \
    block_state_transition, initialize_with_gas_limit, get_code, put_code
from serenity_transactions import Transaction
from db import EphemDB, OverlayDB
import serpent
import ringsig_tester
from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GASLIMIT, NULL_SENDER, ETHER, ECRECOVERACCT, BASICSENDER, RNGSEEDS, GENESIS_TIME, ENTER_EXIT_DELAY, BET_INCENTIVIZER, GAS_REMAINING, CREATOR, GAS_DEPOSIT
from utils import privtoaddr, normalize_address, zpad, encode_int, \
    big_endian_to_int, encode_int32, shardify, sha3, int_to_addr
import ecdsa_accounts
import abi
import sys
import guardian
from guardian import call_method, casper_ct, defaultBetStrategy, Bet, encode_prob
from mandatory_account_code import mandatory_account_ct, mandatory_account_evm, mandatory_account_code
import time
import network
import os
import bitcoin

# Maybe add logging
# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace'
# configure_logging(config_string=config_string)

# Listener; prints out logs in json format
def my_listen(sender, topics, data):
    jsondata = casper_ct.listen(sender, topics, data)
    if jsondata and jsondata["_event_type"] in ('BlockLoss', 'StateLoss'):
        if not bets[jsondata['index']].byzantine:
            if jsondata['loss'] < 0:
                if jsondata['odds'] < 10**7 and jsondata["_event_type"] == 'BlockLoss':
                    index = jsondata['index']
                    height = jsondata['height']
                    print 'bettor current probs', bets[index].probs[:height]
                    raise Exception("Odds waaaay too low! %r" % jsondata)
                if jsondata['odds'] > 10**11:
                    index = jsondata['index']
                    height = jsondata['height']
                    print 'bettor stateroots:', bets[index].stateroots
                    print 'bettor opinion:', bets[index].opinions[index].stateroots
                    if len(bets[0].stateroots) < height:
                        print 'in bettor 0 stateroots:', repr(bets[0].stateroots[height])
                    raise Exception("Odds waaaay too high! %r" % jsondata)
    if jsondata and jsondata["_event_type"] == 'ExcessRewardEvent':
        raise Exception("Excess reward event: %r" % jsondata)
    ecdsa_accounts.constructor_ct.listen(sender, topics, data)
    mandatory_account_ct.listen(sender, topics, data)
    jsondata = ringsig_ct.listen(sender, topics, data)

# Get command line parameters
def get_arg(flag, typ, default):
    if flag in sys.argv:
        return typ(sys.argv[sys.argv.index(flag) + 1])
    else:
        return default

MAX_NODES = get_arg('--maxnodes', int, 12)
assert MAX_NODES >= 5, "Need at least 5 max nodes"
CLOCKWRONG = get_arg('--clockwrong', int, 0)
CLOCKWRONG_CUMUL = CLOCKWRONG + 1
BRAVE = get_arg('--brave', int, 0)
BRAVE_CUMUL = CLOCKWRONG_CUMUL + BRAVE
CRAZYBET = get_arg('--crazybet', int, 0)
CRAZYBET_CUMUL = BRAVE_CUMUL + CRAZYBET
DBL_BLK_SUICIDE = get_arg('--dblblk', int, 0)
DBL_BLK_SUICIDE_CUMUL = CRAZYBET_CUMUL + DBL_BLK_SUICIDE
DBL_BET_SUICIDE = get_arg('--dblbet', int, 0)
DBL_BET_SUICIDE_CUMUL = DBL_BLK_SUICIDE_CUMUL + DBL_BET_SUICIDE
assert 0 <= CLOCKWRONG_CUMUL <= BRAVE_CUMUL <= CRAZYBET_CUMUL <= DBL_BLK_SUICIDE_CUMUL <= DBL_BET_SUICIDE_CUMUL <= MAX_NODES, \
    "Negative numbers or too many nodes with special properties"

print 'Running with %d maximum nodes: %d with wonky clocks, %d brave, %d crazy-betting, %d double-block suiciding, %d double-bet suiciding' % (MAX_NODES, CLOCKWRONG, BRAVE, CRAZYBET, DBL_BLK_SUICIDE, DBL_BET_SUICIDE)

def mk_bet_strategy(state, index, key):
    return defaultBetStrategy(state.clone(), key,
                              clockwrong=(1 <= index < CLOCKWRONG_CUMUL),
                              bravery=(0.997 if CLOCKWRONG_CUMUL <= index < BRAVE_CUMUL else 0.92),
                              crazy_bet=(BRAVE_CUMUL <= index < CRAZYBET_CUMUL),
                              double_block_suicide=(5 if CRAZYBET_CUMUL <= index < DBL_BLK_SUICIDE_CUMUL else 2**80),
                              double_bet_suicide=(1 if DBL_BLK_SUICIDE_CUMUL <= index < DBL_BET_SUICIDE_CUMUL else 2**80))

# Create the genesis
genesis = State('', EphemDB())
initialize_with_gas_limit(genesis, 10**9)
gc = genesis.clone()
# Unleash the kraken....err, I mean casper
casper_file = os.path.join(os.path.split(__file__)[0], 'casper.se.py')
casper_hash_file = os.path.join(os.path.split(__file__)[0], '_casper.hash')
casper_evm_file = os.path.join(os.path.split(__file__)[0], '_casper.evm')
# Cache compilation of Casper to save time
try:
    h = sha3(open(casper_file).read()).encode('hex')
    assert h == open(casper_hash_file).read()
    code = open(casper_evm_file).read()
except:
    h = sha3(open(casper_file).read()).encode('hex')
    code = serpent.compile(casper_file)
    open(casper_evm_file, 'w').write(code)
    open(casper_hash_file, 'w').write(h)
# Add Casper contract to blockchain
tx_state_transition(gc, Transaction(None, 4000000, data='', code=code))
put_code(genesis, CASPER, get_code(gc, mk_contract_address(code=code)))
print 'Casper added'
casper_ct = abi.ContractTranslator(serpent.mk_full_signature(casper_file))
# Ringsig file and ct
ringsig_file = os.path.join(os.path.split(__file__)[0], 'ringsig.se.py')
ringsig_code = serpent.compile(open(ringsig_file).read())
ringsig_ct = abi.ContractTranslator(serpent.mk_full_signature(open(ringsig_file).read()))

# Get the code for the basic ecrecover account
code2 = ecdsa_accounts.constructor_code
tx_state_transition(gc, Transaction(None, 1000000, data='', code=code2))
put_code(genesis, ECRECOVERACCT, get_code(gc, mk_contract_address(code=code2)))
print 'ECRECOVER account added'

# Get the code for the basic EC sender account
code2 = ecdsa_accounts.runner_code
tx_state_transition(gc, Transaction(None, 1000000, data='', code=code2))
put_code(genesis, BASICSENDER, get_code(gc, mk_contract_address(code=code2)))
print 'Basic sender account added'

# Generate the initial set of keys
keys = [zpad(encode_int(x+1), 32) for x in range(0, MAX_NODES - 2)]
# Create a second set of 4 keys
secondkeys = [zpad(encode_int(x+1), 32) for x in range(MAX_NODES - 2, MAX_NODES)]
# Initialize the first keys
for i, k in enumerate(keys):
    # Generate the address
    a = ecdsa_accounts.privtoaddr(k)
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 0
    # Give them 1600 ether
    genesis.set_storage(ETHER, a, 1600 * 10**18)
    # Make their validation code
    vcode = ecdsa_accounts.mk_validation_code(k)
    print 'Length of validation code:', len(vcode)
    # Make the transaction to join as a Casper guardian
    txdata = casper_ct.encode('join', [vcode])
    tx = ecdsa_accounts.mk_transaction(0, 25 * 10**9, 1000000, CASPER, 1500 * 10**18, txdata, k, True)
    print 'Joining'
    v = tx_state_transition(genesis, tx, listeners=[my_listen])
    index = casper_ct.decode('join', ''.join(map(chr, v)))[0]
    print 'Joined with index', index
    print 'Length of account code:', len(get_code(genesis, a))
    # Check that the EVM that each account must have at the end
    # to get transactions included by default is there
    assert mandatory_account_evm == get_code(genesis, a).rstrip('\x00')
    # Check sequence number
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 1
    # Check that we actually joined Casper with the right
    # validation code
    vcode2 = call_method(genesis, CASPER, casper_ct, 'getGuardianValidationCode', [index])
    assert vcode2 == vcode

# Give the secondary keys some ether as well
for i, k in enumerate(secondkeys):
    # Generate the address
    a = ecdsa_accounts.privtoaddr(k)
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 0
    # Give them 1600 ether
    genesis.set_storage(ETHER, a, 1600 * 10**18)

# Set the starting RNG seed to equal to the number of casper guardians
# in genesis
genesis.set_storage(RNGSEEDS, encode_int32(2**256 - 1), genesis.get_storage(CASPER, 0))
# Set the genesis timestamp
genesis.set_storage(GENESIS_TIME, encode_int32(0), int(network.NetworkSimulator.start_time + 5))
print 'genesis time', int(network.NetworkSimulator.start_time + 5), '\n' * 10
# Create betting strategy objects for every guardian
bets = [mk_bet_strategy(genesis, i, k) for i, k in enumerate(keys)]
# Minimum max finalized height
min_mfh = -1

# Transactions to status report on
check_txs = []

# Function to check consistency between everything
def check_correctness(bets):
    global min_mfh
    print '#'*80
    # Max finalized heights for each bettor strategy
    mfhs = [bet.max_finalized_height for bet in bets if not bet.byzantine]
    mchs = [bet.calc_state_roots_from for bet in bets if not bet.byzantine]
    mfchs = [min(bet.max_finalized_height, bet.calc_state_roots_from) for bet in bets if not bet.byzantine]
    new_min_mfh = min(mfchs)
    print 'Max finalized heights: %r' % [bet.max_finalized_height for bet in bets]
    print 'Max calculated stateroots: %r' % [bet.calc_state_roots_from for bet in bets]
    print 'Max height received: %r' % [len(bet.blocks) for bet in bets]
    # Induction heights of each guardian
    print 'Registered induction heights: %r' % [[op.induction_height for op in bet.opinions.values()] for bet in bets]
    # Withdrawn?
    print 'Withdrawn?: %r' % [(bet.withdrawn, bet.seq) for bet in bets]
    # Probabilities
    # print 'Probs: %r' % {i: [bet.probs[i] if i < len(bet.probs) else None for bet in bets] for i in range(new_min_mfh, max([len(bet.blocks) for bet in bets]))}
    # Data about bets from each guardian according to every other guardian
    print 'Now: %.2f' % n.now
    print 'According to each guardian...'
    for bet in bets:
        print ('(%d) Bets received: %r, blocks received: %s. Last bet made: %.2f.' % (bet.index, [((str(op.seq) + ' (withdrawn)') if op.withdrawn else op.seq) for op in bet.opinions.values()], ''.join(['1' if b else '0' for b in bet.blocks]), bet.last_bet_made))
        print 'Probs (in 0-255 repr, from %d):' % (new_min_mfh + 1), map(lambda x: ord(encode_prob(x)), bet.probs[new_min_mfh + 1:])
    # Indices of guardians
    print 'Indices: %r' % [bet.index for bet in bets]
    # Number of blocks received by each guardian
    print 'Blocks received: %r' % [len(bet.blocks) for bet in bets]
    # Number of blocks received by each guardian
    print 'Blocks missing: %r' % [[h for h in range(len(bet.blocks)) if not bet.blocks[h]] for bet in bets]
    # Makes sure all block hashes for all heights up to the minimum finalized
    # height are the same
    print 'Verifying finalized block hash equivalence'
    for j in range(1, len(bets)):
        if not bets[j].byzantine and not bets[j-1].byzantine:
            j_hashes = bets[j].finalized_hashes[:(new_min_mfh+1)]
            jm1_hashes = bets[j-1].finalized_hashes[:(new_min_mfh+1)]
            assert j_hashes == jm1_hashes, (j_hashes, jm1_hashes)
    # Checks state roots for finalized heights and makes sure that they are
    # consistent
    print 'Verifying finalized state root correctness'
    state = State(genesis.root if min_mfh < 0 else bets[0].stateroots[min_mfh], OverlayDB(bets[0].db))
    for b in bets:
        if not b.byzantine:
            for i in range(new_min_mfh):
                assert b.stateroots[i] not in ('\x00' * 32, None)
    print 'Executing blocks %d to %d' % (min_mfh + 1, max(min_mfh, new_min_mfh) + 1)
    for i in range(min_mfh + 1, max(min_mfh, new_min_mfh) + 1):
        assert state.root == bets[0].stateroots[i-1] if i > 0 else genesis.root
        block = bets[j].objects[bets[0].finalized_hashes[i]] if bets[0].finalized_hashes[i] != '\x00' * 32 else None
        block0 = bets[0].objects[bets[0].finalized_hashes[i]] if bets[0].finalized_hashes[i] != '\x00' * 32 else None
        assert block0 == block
        block_state_transition(state, block, listeners=[my_listen])
        if state.root != bets[0].stateroots[i] and i != max(min_mfh, new_min_mfh):
            print bets[0].calc_state_roots_from, bets[j].calc_state_roots_from
            print bets[0].max_finalized_height, bets[j].max_finalized_height
            print 'my state', state.to_dict()
            print 'given state', State(bets[0].stateroots[i], bets[0].db).to_dict()
            import rlp
            print 'block', repr(rlp.encode(block))
            sys.stderr.write('State root mismatch at block %d!\n' % i)
            sys.stderr.write('state.root: %s\n' % state.root.encode('hex'))
            sys.stderr.write('bet: %s\n' % bets[0].stateroots[i].encode('hex'))
            raise Exception(" ")
    min_mfh = new_min_mfh
    print 'Min common finalized height: %d, integrity checks passed' % new_min_mfh
    # Last and next blocks to propose by each guardian
    print 'Last block created: %r' % [bet.last_block_produced for bet in bets]
    print 'Next blocks to create: %r' % [bet.next_block_to_produce for bet in bets]
    # Assert equivalence of proposer lists
    min_proposer_length = min([len(bet.proposers) for bet in bets])
    for i in range(1, len(bets)):
        assert bets[i].proposers[:min_proposer_length] == bets[0].proposers[:min_proposer_length]
    # Guardian sequence numbers as seen by themselves
    print 'Guardian seqs online: %r' % [bet.seq for bet in bets]
    # Guardian sequence numbers as recorded in the chain
    print 'Guardian seqs on finalized chain (%d): %r' % (new_min_mfh, [call_method(state, CASPER, casper_ct, 'getGuardianSeq', [bet.index if bet.index >= 0 else bet.former_index]) for bet in bets])
    h = 0
    while h < len(bets[3].stateroots) and bets[3].stateroots[h] not in (None, '\x00' * 32):
        h += 1
    speculative_state = State(bets[3].stateroots[h-1] if h else genesis.root, OverlayDB(bets[3].db))
    print 'Guardian seqs on speculative chain (%d): %r' % (h-1, [call_method(speculative_state, CASPER, casper_ct, 'getGuardianSeq', [bet.index if bet.index >= 0 else bet.former_index]) for bet in bets])
    # Guardian deposit sizes (over 1500 * 10**18 means profit)
    print 'Guardian deposit sizes: %r' % [call_method(state, CASPER, casper_ct, 'getGuardianDeposit', [bet.index]) for bet in bets if bet.index >= 0]
    print 'Estimated guardian excess gains: %r' % [call_method(state, CASPER, casper_ct, 'getGuardianDeposit', [bet.index]) - 1500 * 10**18 + 47 / 10**9. * 1500 * 10**18 * min_mfh for bet in bets if bet.index >= 0]
    for bet in bets:
        if bet.index >= 0 and big_endian_to_int(state.get_storage(BLKNUMBER, '\x00' * 32)) >= bet.induction_height:
            assert (call_method(state, CASPER, casper_ct, 'getGuardianDeposit', [bet.index]) >= 1499 * 10**18) or bet.byzantine, (bet.double_bet_suicide, bet.byzantine)
    # Account signing nonces
    print 'Account signing nonces: %r' % [big_endian_to_int(state.get_storage(bet.addr, encode_int32(2**256 - 1))) for bet in bets]
    # Transaction status
    print 'Transaction status in unconfirmed_txindex: %r' % [bets[0].unconfirmed_txindex.get(tx.hash, None) for tx in check_txs]
    print 'Transaction status in finalized_txindex: %r' % [bets[0].finalized_txindex.get(tx.hash, None) for tx in check_txs]
    print 'Transaction exceptions: %r' % [bets[0].tx_exceptions.get(tx.hash, 0) for tx in check_txs]

# Simulate a network
n = network.NetworkSimulator(latency=4, agents=bets, broadcast_success_rate=0.9)
n.generate_peers(5)
for _bet in bets:
    _bet.network = n

# Submitting ring sig contract as a transaction
print 'Submitting ring sig contract\n\n'
ringsig_addr = mk_contract_address(sender=bets[0].addr, code=ringsig_code)
print 'Ringsig address', ringsig_addr.encode('hex')
tx3 = ecdsa_accounts.mk_transaction(1, 25 * 10**9, 2000000, CREATOR, 0, ringsig_code, bets[0].key)
bets[0].add_transaction(tx3)
check_txs.extend([tx3])
ringsig_account_code = serpent.compile(("""
def init():
    sstore(0, %d)
    sstore(1, %d)
""" % (big_endian_to_int(ringsig_addr), big_endian_to_int(ringsig_addr))) + '\n' + mandatory_account_code)
ringsig_account_addr = mk_contract_address(sender=bets[0].addr, code=ringsig_account_code)
tx4 = ecdsa_accounts.mk_transaction(2, 25 * 10**9, 2000000, CREATOR, 0, ringsig_account_code, bets[0].key)
bets[0].add_transaction(tx4)
check_txs.extend([tx4])
print 'Ringsig account address', ringsig_account_addr.encode('hex')
# Keep running until the min finalized height reaches 20
while 1:
    n.run(25, sleep=0.25)
    check_correctness(bets)
    if min_mfh >= 36:
        print 'Reached breakpoint'
        break
    print 'Min mfh:', min_mfh
    print 'Peer lists:', [[p.id for p in n.peers[bet.id]] for bet in bets]

recent_state = State(bets[0].stateroots[min_mfh], bets[0].db)
assert get_code(recent_state, ringsig_addr)
assert get_code(recent_state, ringsig_account_addr)
print 'Length of ringsig contract: %d' % len(get_code(recent_state, ringsig_addr))

# Create transactions for a few new guardians to join
print '#' * 80 + '\n' + '#' * 80
print 'Generating transactions to include new guardians'
for i, k in enumerate(secondkeys):
    index = len(keys) + i
    # Make their validation code
    vcode = ecdsa_accounts.mk_validation_code(k)
    # Make the transaction to join as a Casper guardian
    txdata = casper_ct.encode('join', [vcode])
    tx = ecdsa_accounts.mk_transaction(0, 25 * 10**9, 1000000, CASPER, 1500 * 10**18, txdata, k, create=True)
    print 'Making transaction: ', tx.hash.encode('hex')
    bets[0].add_transaction(tx)
    check_txs.extend([tx])

THRESHOLD1 = 115 + 10 * (CLOCKWRONG + CRAZYBET + BRAVE)
THRESHOLD2 = THRESHOLD1 + ENTER_EXIT_DELAY

orig_ring_pubs = []
# Publish submits to ringsig contract
print 'Sending to ringsig contract\n\n'
for bet in bets[1:6]:
    x, y = bitcoin.privtopub(bitcoin.decode_privkey(bet.key))
    orig_ring_pubs.append((x, y))
    data = ringsig_ct.encode('submit', [x, y])
    tx = ecdsa_accounts.mk_transaction(1, 25 * 10**9, 750000, ringsig_account_addr, 10**17, data, bet.key)
    assert bet.should_i_include_transaction(tx)
    bet.add_transaction(tx, True)
    check_txs.extend([tx])
# Keep running until the min finalized height reaches 75. We expect that by
# this time all transactions from the previous phase have been included
while 1:
    n.run(25, sleep=0.25)
    check_correctness(bets)
    if min_mfh > THRESHOLD1:
        print 'Reached breakpoint'
        break
    print 'Min mfh:', min_mfh


recent_state = State(bets[0].stateroots[min_mfh], bets[0].db)
next_index = call_method(recent_state, ringsig_account_addr, ringsig_ct, 'getNextIndex', [])
assert next_index == 5, ("Next index: %d, should be 5" % next_index)
ring_pub_data = call_method(recent_state, ringsig_account_addr, ringsig_ct, 'getPubs', [0])
ring_pubs = [(ring_pub_data[i] % 2**256, ring_pub_data[i+1] % 2**256) for i in range(0, len(ring_pub_data), 2)]
print sorted(ring_pubs), sorted(orig_ring_pubs)
assert sorted(ring_pubs) == sorted(orig_ring_pubs)
print 'Submitted public keys:', ring_pubs

# Create ringsig withdrawal transactions
for i, bet in enumerate(bets[1:6]):
    x, y = bitcoin.privtopub(bitcoin.decode_privkey(bet.key))
    target_addr = 2000 + i
    x0, s, Ix, Iy = ringsig_tester.ringsig_sign_substitute(encode_int32(target_addr), bitcoin.decode_privkey(bet.key), ring_pubs)
    print 'Verifying ring signature using python code'
    assert ringsig_tester.ringsig_verify_substitute(encode_int32(target_addr), x0, s, Ix, Iy, ring_pubs)
    data = ringsig_ct.encode('withdraw', [int_to_addr(target_addr), x0, s, Ix, Iy, 0])
    tx = Transaction(ringsig_account_addr, 1000000, data=data, code=b'')
    print 'Verifying tx includability'
    assert bet.should_i_include_transaction(tx)
    bet.add_transaction(tx)
    check_txs.extend([tx])

# Create bet objects for the new guardians
state = State(genesis.root, bets[0].db)
secondbets = [mk_bet_strategy(state, len(bets) + i, k) for i, k in enumerate(secondkeys)]
for bet in secondbets:
    bet.network = n
n.agents.extend(secondbets)
n.generate_peers(5)
print 'Increasing number of peers in the network to %d!' % MAX_NODES
recent_state = State(bets[0].stateroots[min_mfh], bets[0].db)
# Check that all signups are successful
signups = call_method(recent_state, CASPER, casper_ct, 'getGuardianSignups', [])
print 'Guardians signed up: %d' % signups
assert signups == MAX_NODES
print 'All new guardians inducted'
print 'Induction heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getGuardianInductionHeight', [i]) for i in range(len(keys + secondkeys))]

# Keep running until the min finalized height reaches ~175. We expect that by
# this time all guardians will be actively betting off of each other's bets
while 1:
    n.run(25, sleep=0.25)
    check_correctness(bets)
    print 'Min mfh:', min_mfh
    print 'Induction heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getGuardianInductionHeight', [i]) for i in range(len(keys + secondkeys))]
    if min_mfh > THRESHOLD2:
        print 'Reached breakpoint'
        break

# Create transactions for old guardians to leave
print '#' * 80 + '\n' + '#' * 80
print 'Generating transactions to withdraw some guardians'
for bet in bets[:3]:
    bet.withdraw()

BLK_DISTANCE = len(bet.blocks) - min_mfh


# Keep running until the min finalized height reaches ~290.
while 1:
    n.run(25, sleep=0.25)
    check_correctness(bets)
    print 'Min mfh:', min_mfh
    print 'Withdrawal heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getGuardianWithdrawalHeight', [i]) for i in range(len(keys + secondkeys))]
    if min_mfh > 200 + BLK_DISTANCE + ENTER_EXIT_DELAY:
        print 'Reached breakpoint'
        break
    # Exit early if the withdrawal step already completed
    recent_state = bets[0].get_finalized_state()
    if len([i for i in range(50) if call_method(recent_state, CASPER, casper_ct, 'getGuardianStatus', [i]) == 2]) == MAX_NODES - 3:
        break

recent_state = bets[0].get_optimistic_state()
# Check that the only remaining active guardians are the ones that have not
# yet signed out.
print 'Guardian statuses: %r' % [call_method(recent_state, CASPER, casper_ct, 'getGuardianStatus', [i]) for i in range(MAX_NODES)]
assert len([i for i in range(50) if call_method(recent_state, CASPER, casper_ct, 'getGuardianStatus', [i]) == 2]) == MAX_NODES - 3
