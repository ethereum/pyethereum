from serenity_blocks import State, tx_state_transition, mk_contract_address, \
    block_state_transition, initialize_with_gas_limit, get_code, put_code
from serenity_transactions import Transaction
from db import EphemDB, OverlayDB
import serpent
from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GASLIMIT, NULL_SENDER, ETHER, ECRECOVERACCT, RNGSEEDS, GENESIS_TIME, ENTER_EXIT_DELAY, BET_INCENTIVIZER, GAS_REMAINING
from utils import privtoaddr, normalize_address, zpad, encode_int, \
    big_endian_to_int, encode_int32, shardify, sha3
import ecdsa_accounts
import abi
import sys
import bet
from bet import call_method, casper_ct, defaultBetStrategy, bet_incentivizer_code, bet_incentivizer_ct, Bet
import time
import network
import os

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

def get_arg(flag, typ, default):
    if flag in sys.argv:
        return typ(sys.argv[sys.argv.index(flag) + 1])
    else:
        return default

MAX_NODES = get_arg('--maxnodes', int, 10)
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
                              bravery=(0.997 if CLOCKWRONG_CUMUL <= index < BRAVE_CUMUL else 0.84),
                              crazy_bet=(BRAVE_CUMUL <= index < CRAZYBET_CUMUL),
                              double_block_suicide=(5 if CRAZYBET_CUMUL <= index < DBL_BLK_SUICIDE_CUMUL else 2**80),
                              double_bet_suicide=(1 if DBL_BLK_SUICIDE_CUMUL <= index < DBL_BET_SUICIDE_CUMUL else 2**80))

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
tx_state_transition(gc, Transaction(None, 3000000, data='', code=code))
put_code(genesis, CASPER, get_code(gc, mk_contract_address(code=code)))
print 'Casper added'
casper_ct = abi.ContractTranslator(serpent.mk_full_signature(casper_file))
# print {x: casper_ct.function_data[x]['prefix'] for x in casper_ct.function_data}
# sys.exit()
# Add the bet incentivizer
code2 = serpent.compile(bet_incentivizer_code)
tx_state_transition(gc, Transaction(None, 1000000, data='', code=code2))
put_code(genesis, BET_INCENTIVIZER, get_code(gc, mk_contract_address(code=code2)))
print 'Bet incentivizer added'

# Get the code for the basic ecrecover account
put_code(genesis, ECRECOVERACCT, ecdsa_accounts.constructor_code)
print 'ECRECOVER account added'
    
# We might want logging
# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace'
# configure_logging(config_string=config_string)

# Generate the initial set of keys keys
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
    # Make a dummy transaction to initialize the account
    # tx = ecdsa_accounts.mk_transaction(0, 1, 1000000, CASPER, 0, '', k, create=True)
    # v = tx_state_transition(genesis, tx)
    # assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 1
    # Make their validation code
    vcode = ecdsa_accounts.mk_validation_code(k)
    print 'Length of validation code:', len(vcode)
    # Make the transaction to join as a Casper validator
    txdata = casper_ct.encode('join', [vcode])
    print 'Length of account code:', len(get_code(genesis, a))
    tx = ecdsa_accounts.mk_transaction(0, 1, 1000000, CASPER, 1500 * 10**18, txdata, k, True)
    print 'Joining'
    v = tx_state_transition(genesis, tx, listeners=[my_listen])
    index = casper_ct.decode('join', ''.join(map(chr, v)))[0]
    print 'Joined with index', index
    # Check sequence number
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 1
    # Check that we actually joined Casper with the right
    # validation code
    vcode2 = call_method(genesis, CASPER, casper_ct, 'getUserValidationCode', [index])
    assert vcode2 == vcode
    # Make the transaction to send some ether to the bet inclusion
    # incentivization contract
    txdata2 = bet_incentivizer_ct.encode('deposit', [index])
    tx = ecdsa_accounts.mk_transaction(1, 1, 1000000, BET_INCENTIVIZER, 1 * 10**18, txdata2, k, True)
    v = bet_incentivizer_ct.decode('deposit', ''.join(map(chr, tx_state_transition(genesis, tx))))[0]
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
bets = [mk_bet_strategy(genesis, i, k) for i, k in enumerate(keys)]
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
    mfhs = [bet.my_max_finalized_height for bet in bets if not bet.byzantine]
    mchs = [bet.calc_state_roots_from for bet in bets if not bet.byzantine]
    mfchs = [min(bet.my_max_finalized_height, bet.calc_state_roots_from) for bet in bets if not bet.byzantine]
    new_min_mfh = min(mfchs)
    print 'Max finalized heights: %r' % [bet.my_max_finalized_height for bet in bets]
    print 'Max calculated stateroots: %r' % [bet.calc_state_roots_from for bet in bets]
    print 'Max height received: %r' % [len(bet.blocks) for bet in bets]
    # Induction heights of each validator
    print 'Registered induction heights: %r' % [[op.induction_height for op in bet.opinions.values()] for bet in bets]
    # Withdrawn?
    print 'Withdrawn?: %r' % [(bet.withdrawn, bet.seq) for bet in bets]
    # Probabilities
    print 'Probs: %r' % {i: [bet.probs[i] if i < len(bet.probs) else None for bet in bets] for i in range(new_min_mfh, max([len(bet.blocks) for bet in bets]))}
    # Data about bets from each validator according to every other validator
    print 'Now: %.2f' % time.time()
    print 'According to each validator...'
    for bet in bets:
        print ('(%d) Bets received: %r, blocks received: %s. Last bet made: %.2f' % (bet.index, [((str(op.seq) + ' (withdrawn)') if op.withdrawn else op.seq) for op in bet.opinions.values()], ''.join(['1' if b else '0' for b in bet.blocks]), bet.last_bet_made))
    # Indices of validators
    print 'Indices: %r' % [bet.index for bet in bets]
    # Number of blocks received by each validator
    print 'Blocks received: %r' % [len(bet.blocks) for bet in bets]
    # Number of blocks received by each validator
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
                assert b.stateroots[i] not in ('\x00' * 32, None), (b.stateroots[:max(min_mfh + 1, new_min_mfh + 1)], min_mfh, new_min_mfh, b.my_max_finalized_height, b.calc_state_roots_from)
    print 'Executing blocks %d to %d' % (min_mfh + 1, max(min_mfh, new_min_mfh) + 1)
    for i in range(min_mfh + 1, max(min_mfh, new_min_mfh) + 1):
        assert state.root == bets[0].stateroots[i-1] if i > 0 else genesis.root
        block = bets[j].objects[bets[0].finalized_hashes[i]] if bets[0].finalized_hashes[i] != '\x00' * 32 else None
        block0 = bets[0].objects[bets[0].finalized_hashes[i]] if bets[0].finalized_hashes[i] != '\x00' * 32 else None
        assert block0 == block
        block_state_transition(state, block, listeners=[my_listen])
        if state.root != bets[0].stateroots[i] and i != max(min_mfh, new_min_mfh):
            print bets[0].calc_state_roots_from, bets[j].calc_state_roots_from
            print bets[0].my_max_finalized_height, bets[j].my_max_finalized_height
            sys.stderr.write('State root mismatch at block %d!\n' % i)
            sys.stderr.write('state.root: %s\n' % state.root.encode('hex'))
            sys.stderr.write('bet: %s\n' % bets[0].stateroots[i].encode('hex'))
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
    print 'Validator seqs online: %r' % [bet.seq for bet in bets]
    # Validator sequence numbers as recorded in the chain
    print 'Validator seqs on finalized chain (%d): %r' % (new_min_mfh, [call_method(state, CASPER, casper_ct, 'getUserSeq', [bet.index if bet.index >= 0 else bet.former_index]) for bet in bets])
    h = 0
    while h < len(bets[3].stateroots) and bets[3].stateroots[h] not in (None, '\x00' * 32):
        h += 1
    speculative_state = State(bets[3].stateroots[h-1] if h else genesis.root, OverlayDB(bets[3].db))
    print 'Validator seqs on speculative chain (%d): %r' % (h-1, [call_method(speculative_state, CASPER, casper_ct, 'getUserSeq', [bet.index if bet.index >= 0 else bet.former_index]) for bet in bets])
    # Validator deposit sizes (over 1500 * 10**18 means profit)
    print 'Validator deposit sizes: %r' % [call_method(state, CASPER, casper_ct, 'getUserDeposit', [bet.index]) for bet in bets if bet.index >= 0]
    for bet in bets:
        if bet.index >= 0 and big_endian_to_int(state.get_storage(BLKNUMBER, '\x00' * 32)) >= bet.induction_height:
            assert (call_method(state, CASPER, casper_ct, 'getUserDeposit', [bet.index]) >= 1499 * 10**18) or bet.byzantine, (bet.double_bet_suicide, bet.byzantine)
    # Account signing nonces
    print 'Account signing nonces: %r' % [big_endian_to_int(state.get_storage(bet.addr, encode_int32(2**256 - 1))) for bet in bets]
    # Transaction status
    print 'Transaction status in unconfirmed_txindex: %r' % [bets[0].unconfirmed_txindex.get(tx.hash, None) for tx in check_txs]
    print 'Transaction status in finalized_txindex: %r' % [bets[0].finalized_txindex.get(tx.hash, None) for tx in check_txs]
    print 'Transaction exceptions: %r' % [bets[0].tx_exceptions.get(tx.hash, 0) for tx in check_txs]
    print 'Tracking transactions: %r' % [(h[:8].encode('hex'), bets[0].get_transaction_status(h)) for h in bets[0].tracked_tx_hashes]

# Simulate a network
n = network.NetworkSimulator(latency=4, agents=bets, broadcast_success_rate=0.9)
n.generate_peers(5)
for bet in bets:
    bet.network = n
# Keep running until the min finalized height reaches 5
while 1:
    n.run(25, sleep=0.25)
    check_correctness(bets)
    if min_mfh >= 5:
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
    txdata = casper_ct.encode('join', [vcode])
    tx = ecdsa_accounts.mk_transaction(0, 1, 1000000, CASPER, 1500 * 10**18, txdata, k, create=True)
    print 'Making transaction: ', tx.hash.encode('hex')
    # Make the transaction to send some ether to the bet inclusion
    # incentivization contract
    txdata2 = bet_incentivizer_ct.encode('deposit', [index])
    tx2 = ecdsa_accounts.mk_transaction(1, 1, 1000000, BET_INCENTIVIZER, 1 * 10**18, txdata2, k, True)
    bets[0].add_transaction(tx)
    bets[0].add_transaction(tx2)
    check_txs.extend([tx, tx2])

THRESHOLD1 = 75 + 10 * (CLOCKWRONG + CRAZYBET + BRAVE)
THRESHOLD2 = THRESHOLD1 + ENTER_EXIT_DELAY
# Keep running until the min finalized height reaches 75. We expect that by
# this time all transactions from the previous phase have been included
while 1:
    n.run(25, sleep=0.25)
    check_correctness(bets)
    if min_mfh > THRESHOLD1:
        print 'Reached breakpoint'
        break
    print 'Min mfh:', min_mfh

# Create bet objects for the new validators
state = State(genesis.root, bets[0].db)
secondbets = [mk_bet_strategy(state, len(bets) + i, k) for i, k in enumerate(secondkeys)]
for bet in secondbets:
    bet.network = n
n.agents.extend(secondbets)
n.generate_peers(5)
print 'Increasing number of peers in the network to %d!' % MAX_NODES
recent_state = State(bets[0].stateroots[min_mfh], bets[0].db)
# Check that all signups are successful
signups = call_method(recent_state, CASPER, casper_ct, 'getValidatorSignups', [])
print 'Validators signed up: %d' % signups
assert signups == MAX_NODES
print 'All new validators inducted'
print 'Induction heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserInductionHeight', [i]) for i in range(len(keys + secondkeys))]

# Keep running until the min finalized height reaches ~175. We expect that by
# this time all validators will be actively betting off of each other's bets
while 1:
    n.run(25, sleep=0.25)
    check_correctness(bets)
    print 'Min mfh:', min_mfh
    print 'Induction heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserInductionHeight', [i]) for i in range(len(keys + secondkeys))]
    if min_mfh > THRESHOLD2:
        print 'Reached breakpoint'
        break

# Create transactions for old validators to leave
print '#' * 80 + '\n' + '#' * 80
print 'Generating transactions to withdraw some validators'
for bet in bets[:3]:
    bet.withdraw()

BLK_DISTANCE = len(bet.blocks) - min_mfh


# Keep running until the min finalized height reaches ~290.
while 1:
    n.run(25, sleep=0.25)
    check_correctness(bets)
    print 'Min mfh:', min_mfh
    print 'Withdrawal heights: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserWithdrawalHeight', [i]) for i in range(len(keys + secondkeys))]
    if min_mfh > 150 + BLK_DISTANCE + ENTER_EXIT_DELAY:
        print 'Reached breakpoint'
        break

recent_state = State(bets[0].stateroots[min_mfh], bets[0].db)
# Check that the only remaining active validators are the ones that have not
# yet signed out.
print 'Validator statuses: %r' % [call_method(recent_state, CASPER, casper_ct, 'getUserStatus', [i]) for i in range(MAX_NODES)]
assert len([i for i in range(50) if call_method(recent_state, CASPER, casper_ct, 'getUserStatus', [i]) == 2]) == MAX_NODES - 3
