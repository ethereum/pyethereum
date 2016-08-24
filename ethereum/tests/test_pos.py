from ethereum import utils
from ethereum.state import State
from ethereum import vm
from ethereum.state_transition import apply_transaction, apply_const_message, validate_block_header, initialize, casper_config
from ethereum.transactions import Transaction
from ethereum.chain import Chain
from ethereum.parse_genesis_declaration import mk_basic_state
from ethereum import abi
from ethereum.casper_utils import RandaoManager, generate_validation_code, call_casper, \
    get_skips_and_block_making_time, sign_block, get_casper_ct, make_casper_genesis, \
    validator_sizes, find_indices, get_timestamp, make_withdrawal_signature
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

print 'Initializing privkeys, addresses and randaos for validators'
privkeys = [utils.sha3(str(i)) for i in range(NUM_PARTICIPANTS)]
addrs = [utils.privtoaddr(k) for k in privkeys]
randaos = [RandaoManager(utils.sha3(str(i))) for i in range(NUM_PARTICIPANTS)]
deposit_sizes = [256] * (NUM_PARTICIPANTS // 4) + [128] * (NUM_PARTICIPANTS - (NUM_PARTICIPANTS // 4))
assert len(privkeys) == len(addrs) == len(randaos) == len(deposit_sizes) == NUM_PARTICIPANTS

# Creating casper contract translator
ct = get_casper_ct()
assert ct
print 'Constructing genesis'
s = make_casper_genesis(validators=[(generate_validation_code(a), ds * 10**18, r.get(9999))
                                    for a, ds, r in zip(addrs, deposit_sizes, randaos)][:-1],
                        alloc={a: {'balance': 10**18} for a in addrs},
                        timestamp=int(time.time() - 99999),
                        epoch_length=100)
print 'Genesis constructed successfully'
chains = [Chain(s.to_snapshot(), env=s.env) for i in range(NUM_PARTICIPANTS)]

# Create and sign a block
def make_block(chain, key, randao, indices, skips):
    h = make_head_candidate(chain, TransactionQueue(), timestamp=get_timestamp(chain, skips))
    return sign_block(h, key, randao.get_parent(call_casper(chain.state, 'getRandao', [indices[0], indices[1]])), indices, skips)

next_validator = call_casper(s, 'getValidator', [0])
print 'Next validator:', next_validator
indices = [find_indices(s, generate_validation_code(addrs[i]))[:2] for i in range(len(addrs) - 1)]
print indices, next_validator
next_validator_id = indices.index(next_validator)

print 'Index in set:', next_validator_id

skip_count, timestamp = get_skips_and_block_making_time(chains[next_validator_id], indices[next_validator_id])
assert skip_count == 0
b = make_block(chains[0], privkeys[next_validator_id],
               randaos[next_validator_id], indices[next_validator_id], skip_count)
# Validate it
print 'Block timestamp:', b.header.timestamp
initialize(s, b)
print 'Validating block'
assert validate_block_header(s, b.header)
print 'Validation successful'
assert chains[0].add_block(b)
print 'Block added to chain'
# Make another block
next_validator = call_casper(chains[0].state, 'getValidator', [0])
next_validator_id = indices.index(next_validator)
skip_count, timestamp = get_skips_and_block_making_time(chains[0], next_validator)
assert skip_count == 0
b2 = make_block(chains[0], privkeys[next_validator_id],
                randaos[next_validator_id], indices[next_validator_id], skip_count)
assert chains[0].add_block(b2)
print 'Second block added to chain'
# Make a dunkle and include it in a transaction
next_validator = call_casper(chains[1].state, 'getValidator', [1])
next_validator_id = indices.index(next_validator)
skip_count, timestamp = get_skips_and_block_making_time(chains[next_validator_id], next_validator)
assert skip_count == 1
b3 = make_block(chains[1], privkeys[next_validator_id],
                randaos[next_validator_id], indices[next_validator_id], skip_count)
print 'Dunkle produced'
t = Transaction(0, 0, 10**6, casper_config['CASPER_ADDR'], 0, ct.encode('includeDunkle', [rlp.encode(b3.header)])).sign(privkeys[0])
apply_transaction(chains[0].state, t)
assert call_casper(chains[0].state, 'isDunkleIncluded', [utils.sha3(rlp.encode(b3.header))])
print 'Dunkle added successfully'
# Try (and fail) to add the dunkle again
x = chains[0].state.gas_used
t = Transaction(1, 0, 10**6, casper_config['CASPER_ADDR'], 0, ct.encode('includeDunkle', [rlp.encode(b3.header)])).sign(privkeys[0])
apply_transaction(chains[0].state, t)
x2 = chains[0].state.gas_used
assert x2 - x == t.startgas, (x2 - x, t.startgas)
print 'Dunkle addition failed, as expected, since dunkle is a duplicate'
# Induct a new validator
k, a, ds, r = privkeys[-1], addrs[-1], deposit_sizes[-1], randaos[-1]
vc = generate_validation_code(a)
chains[0].state.set_balance(a, (ds + 1) * 10**18)
t2 = Transaction(chains[0].state.get_nonce(a), 0, 1000000, casper_config['CASPER_ADDR'],
                 ds * 10**18, ct.encode('deposit', [vc, r.get(9999)])).sign(k)
apply_transaction(chains[0].state, t2)
indices.append(find_indices(chains[0].state, vc)[:2])
assert indices[-1]
assert call_casper(chains[0].state, 'getStartEpoch', indices[-1]) == 2
chains[0].state.commit()
print 'Added new validator "in-flight", indices:', indices[-1]
# Create some blocks
vids = []
bn = call_casper(chains[0].state, 'getBlockNumber')
for i in range(bn + 1, 200):
    next_validator = call_casper(chains[0].state, 'getValidator', [0])
    next_validator_id = indices.index(next_validator)
    b = make_block(chains[0], privkeys[next_validator_id], randaos[next_validator_id],
                   indices[next_validator_id], 0)
    assert chains[0].add_block(b)
    vids.append(next_validator_id)
print 'Created 200 blocks before any deposits/widthdraws, created by validators:', vids
assert len(indices) - 1 not in vids
assert 0 in vids
# Remove a validator
sigdata = make_withdrawal_signature(privkeys[0])
txdata = ct.encode('startWithdrawal', [indices[0][0], indices[0][1], sigdata])
t3 = Transaction(chains[0].state.get_nonce(addrs[0]), 0, 1000000, casper_config['CASPER_ADDR'], 0, txdata).sign(privkeys[0])
apply_transaction(chains[0].state, t3)
assert call_casper(chains[0].state, 'getEndEpoch', indices[0]) == 4
chains[0].state.commit()
print 'Withdrew a validator'
for i in range(200, 400):
    next_validator = call_casper(chains[0].state, 'getValidator', [0])
    next_validator_id = indices.index(next_validator)
    b = make_block(chains[0], privkeys[next_validator_id], randaos[next_validator_id],
                   indices[next_validator_id], 0)
    assert b.header.number == i
    assert chains[0].add_block(b)
    vids.append(next_validator_id)
print 'Created 200 blocks after the deposit, created by validators:', vids[-200:]
assert len(indices) - 1 in vids
assert 0 in vids
for i in range(400, 600):
    next_validator = call_casper(chains[0].state, 'getValidator', [0])
    next_validator_id = indices.index(next_validator)
    b = make_block(chains[0], privkeys[next_validator_id], randaos[next_validator_id],
                   indices[next_validator_id], 0)
    assert chains[0].add_block(b)
    vids.append(next_validator_id)
print 'Created 200 blocks after the withdrawal, created by validators:', vids[-200:]
assert len(indices) - 1 in vids
assert 0 not in vids[-200:]
print 'PoS test fully passed'
