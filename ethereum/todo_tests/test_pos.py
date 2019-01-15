from ethereum import utils
from ethereum.state import State
from ethereum import vm
from ethereum.state_transition import apply_transaction, apply_const_message, validate_block_header, initialize
from ethereum.transactions import Transaction
from ethereum.chain import Chain
from ethereum.parse_genesis_declaration import mk_basic_state
from ethereum import abi
from ethereum.casper_utils import RandaoManager, generate_validation_code, call_casper, \
    get_skips_and_block_making_time, sign_block, get_contract_code, \
    casper_config, get_casper_ct, get_casper_code, get_rlp_decoder_code, \
    get_hash_without_ed_code, make_casper_genesis, get_timestamp, \
    make_withdrawal_signature
from ethereum.block_creation import make_head_candidate
from ethereum.transaction_queue import TransactionQueue
from ethereum.slogging import LogRecorder, configure_logging, set_level
import serpent
from ethereum.config import default_config, Env
import copy
import time
import rlp

# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
config_string = ':info,eth.vm.log:trace'
configure_logging(config_string=config_string)

NUM_PARTICIPANTS = 10
BLOCK_MAKING_PPB = 10

print('Initializing privkeys, addresses and randaos for validators')
privkeys = [utils.sha3(str(i)) for i in range(NUM_PARTICIPANTS)]
addrs = [utils.privtoaddr(k) for k in privkeys]
randaos = [RandaoManager(utils.sha3(str(i))) for i in range(NUM_PARTICIPANTS)]
deposit_sizes = [i * 500 + 500 for i in range(NUM_PARTICIPANTS)]
vcodes = [generate_validation_code(a) for a in addrs]
vchashes = [utils.sha3(c) for c in vcodes]
assert len(privkeys) == len(addrs) == len(randaos) == len(
    deposit_sizes) == len(vcodes) == len(vchashes) == NUM_PARTICIPANTS

# Creating casper contract translator
ct = get_casper_ct()
assert ct
print('Constructing genesis')
s = make_casper_genesis(validators=[(generate_validation_code(a), ds * 10**18, r.get(9999), a)
                                    for a, ds, r in zip(addrs, deposit_sizes, randaos)][:-1],
                        alloc={a: {'balance': 10**18} for a in addrs},
                        timestamp=int(time.time() - 99999),
                        epoch_length=100)
print('Genesis constructed successfully')
chains = [Chain(s.to_snapshot(), env=s.env) for i in range(NUM_PARTICIPANTS)]
withdrawal_time_1 = call_casper(
    chains[0].state, 'getLockDuration', [
        vchashes[0]])

# List of validator IDs that created each block
vids = []


# Create and sign a block
def make_block(chain, key, randao, vchash, skips):
    h, _ = make_head_candidate(
        chain, TransactionQueue(), timestamp=get_timestamp(
            chain, skips))
    return sign_block(h, key, randao.get_parent(call_casper(
        chain.state, 'getRandao', [vchash])), vchash, skips)


next_validator = call_casper(s, 'getValidator', [0])
print('Next validator:', next_validator.encode('hex'))
next_validator_id = vchashes.index(next_validator)
print('Next validator index:', next_validator_id)

skip_count, timestamp = get_skips_and_block_making_time(
    chains[0].state, next_validator)
assert skip_count == 0
b = make_block(chains[0], privkeys[next_validator_id],
               randaos[next_validator_id], vchashes[next_validator_id], skip_count)
# Validate it
print('Block timestamp:', b.header.timestamp)
initialize(s, b)
print('Validating block')
assert validate_block_header(s, b.header)
print('Validation successful')
assert chains[0].add_block(b)
vids.append(next_validator_id)
print('Block added to chain')
# Make another block
next_validator = call_casper(chains[0].state, 'getValidator', [0])
next_validator_id = vchashes.index(next_validator)
skip_count, timestamp = get_skips_and_block_making_time(
    chains[0].state, next_validator)
assert skip_count == 0
b2 = make_block(chains[0], privkeys[next_validator_id],
                randaos[next_validator_id], vchashes[next_validator_id], skip_count)
assert chains[0].add_block(b2)
vids.append(next_validator_id)
print('Second block added to chain')
# Make a dunkle and include it in a transaction
next_validator = call_casper(chains[1].state, 'getValidator', [1])
next_validator_id = vchashes.index(next_validator)
skip_count, timestamp = get_skips_and_block_making_time(
    chains[1].state, next_validator)
assert skip_count == 1
b3 = make_block(chains[1], privkeys[next_validator_id],
                randaos[next_validator_id], vchashes[next_validator_id], skip_count)
print('Dunkle produced')
t = Transaction(0,
                0,
                10**6,
                casper_config['CASPER_ADDR'],
                0,
                ct.encode('includeDunkle',
                          [rlp.encode(b3.header)])).sign(privkeys[0])
apply_transaction(chains[0].state, t)
assert call_casper(
    chains[0].state, 'isDunkleIncluded', [
        utils.sha3(
            rlp.encode(
                b3.header))])
print('Dunkle added successfully')
# Try (and fail) to add the dunkle again
x = chains[0].state.gas_used
t = Transaction(1,
                0,
                10**6,
                casper_config['CASPER_ADDR'],
                0,
                ct.encode('includeDunkle',
                          [rlp.encode(b3.header)])).sign(privkeys[0])
apply_transaction(chains[0].state, t)
x2 = chains[0].state.gas_used
assert x2 - x == t.startgas, (x2 - x, t.startgas)
print('Dunkle addition failed, as expected, since dunkle is a duplicate')
# Induct a new validator
k, a, ds, r = privkeys[-1], addrs[-1], deposit_sizes[-1], randaos[-1]
vc = generate_validation_code(a)
chains[0].state.set_balance(a, (ds + 1) * 10**18)
t2 = Transaction(chains[0].state.get_nonce(a), 0, 1000000, casper_config['CASPER_ADDR'],
                 ds * 10**18, ct.encode('deposit', [vc, r.get(9999)])).sign(k)
apply_transaction(chains[0].state, t2)
assert call_casper(chains[0].state, 'getStartEpoch', [vchashes[-1]]) == 2
chains[0].state.commit()
print('Added new validator "in-flight", indices:', vchashes[-1].encode('hex'))
# Create some blocks
bn = call_casper(chains[0].state, 'getBlockNumber')
for i in range(bn + 1, 200):
    next_validator = call_casper(chains[0].state, 'getValidator', [0])
    next_validator_id = vchashes.index(next_validator)
    b = make_block(chains[0], privkeys[next_validator_id], randaos[next_validator_id],
                   vchashes[next_validator_id], 0)
    assert chains[0].add_block(b)
    vids.append(next_validator_id)
print('Created 200 blocks before any deposits/widthdraws, created by validators:', vids)
assert len(vchashes) - 1 not in vids
assert 0 in vids
# Remove a validator
sigdata = make_withdrawal_signature(privkeys[0])
txdata = ct.encode('startWithdrawal', [vchashes[0], sigdata])
t3 = Transaction(
    chains[0].state.get_nonce(
        addrs[0]),
    0,
    1000000,
    casper_config['CASPER_ADDR'],
    0,
    txdata).sign(
    privkeys[0])
apply_transaction(chains[0].state, t3)
assert call_casper(chains[0].state, 'getEndEpoch', [vchashes[0]]) == 4
chains[0].state.commit()
print('Withdrew a validator')
print('%d blocks before ETH becomes available' % withdrawal_time_1)
for i in range(200, 400):
    next_validator = call_casper(chains[0].state, 'getValidator', [0])
    next_validator_id = vchashes.index(next_validator)
    b = make_block(chains[0], privkeys[next_validator_id], randaos[next_validator_id],
                   vchashes[next_validator_id], 0)
    assert b.header.number == i
    assert chains[0].add_block(b)
    vids.append(next_validator_id)
print('Created 200 blocks after the deposit, created by validators:',
      vids[-200:])
assert len(vchashes) - 1 in vids
assert 0 in vids
for i in range(400, 400 + withdrawal_time_1 + 1):
    next_validator = call_casper(chains[0].state, 'getValidator', [0])
    next_validator_id = vchashes.index(next_validator)
    b = make_block(chains[0], privkeys[next_validator_id], randaos[next_validator_id],
                   vchashes[next_validator_id], 0)
    assert chains[0].add_block(b)
    vids.append(next_validator_id)
print('Created %d blocks after the withdrawal, created by validators:' %
      (withdrawal_time_1 + 1), vids[-200:])
assert len(vchashes) - 1 in vids
assert 0 not in vids[-200:]
pre_bal = chains[0].state.get_balance(addrs[0])
txdata = ct.encode('withdraw', [vchashes[0]])
t4 = Transaction(
    chains[0].state.get_nonce(
        addrs[0]),
    0,
    1000000,
    casper_config['CASPER_ADDR'],
    0,
    txdata).sign(
    privkeys[0])
apply_transaction(chains[0].state, t4)
post_bal = chains[0].state.get_balance(addrs[0])
print('Wei withdrawn:', post_bal - pre_bal)
blocks_by_v0_in_stage1 = len([i for i in vids[:200] if i == 0])
expected_revenue_in_stage1 = blocks_by_v0_in_stage1 * \
    max(sum(deposit_sizes[:-1]), 1000000) * 10**18 * BLOCK_MAKING_PPB / 10**9
blocks_by_v0_in_stage2 = len([i for i in vids[200:400] if i == 0])
expected_revenue_in_stage2 = blocks_by_v0_in_stage2 * \
    max(sum(deposit_sizes), 1000000) * 10**18 * BLOCK_MAKING_PPB / 10**9

assert post_bal - pre_bal == deposit_sizes[0] * 10**18 + \
    expected_revenue_in_stage1 + expected_revenue_in_stage2
print('PoS test fully passed')
