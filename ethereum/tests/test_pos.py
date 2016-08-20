from ethereum import utils
from ethereum.state import State
from ethereum import vm
from ethereum.state_transition import apply_transaction, apply_const_message, validate_block_header, initialize
from ethereum.transactions import Transaction
from ethereum.chain import Chain
from ethereum.parse_genesis_declaration import mk_basic_state
from ethereum import abi
from ethereum.casper_utils import RandaoManager, generate_validation_code, call_casper, \
    get_skips_and_block_making_time, sign_block, make_block, get_contract_code, \
    casper_config, get_casper_ct, get_casper_code, get_rlp_decoder_code, \
    get_hash_without_ed_code, make_casper_genesis, validator_sizes, find_indices
from ethereum.slogging import LogRecorder, configure_logging, set_level
import serpent
from ethereum.config import default_config, Env
import copy
import time
import rlp

# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
config_string = ':info,eth.vm.log:trace'
configure_logging(config_string=config_string)

NUM_PARTICIPANTS = 20

print 'Initializing privkeys, addresses and randaos for validators'
privkeys = [utils.sha3(str(i)) for i in range(NUM_PARTICIPANTS)]
addrs = [utils.privtoaddr(k) for k in privkeys]
randaos = [RandaoManager(utils.sha3(str(i))) for i in range(NUM_PARTICIPANTS)]
deposit_sizes = [256] * (NUM_PARTICIPANTS // 4) + [128] * (NUM_PARTICIPANTS - (NUM_PARTICIPANTS // 4))

# Creating casper contract translator
ct = get_casper_ct()
assert ct
print 'Constructing genesis'
s = make_casper_genesis(validators=[(generate_validation_code(a), ds * 10**18, r.get(9999))
                                    for a, ds, r in zip(addrs, deposit_sizes, randaos)],
                        alloc={a: {'balance': 10**18} for a in addrs},
                        timestamp=int(time.time() - 10),
                        epoch_length=100)
print 'Genesis constructed successfully'

next_validator = call_casper(s, 'getValidator', [0])
print 'Next validator:', next_validator
indices = [find_indices(s, generate_validation_code(addrs[i])) for i in range(len(addrs))]
next_validator_id = indices.index(next_validator)

print 'Index in set:', next_validator_id

chains = [Chain(s.to_snapshot(), env=s.env) for i in range(NUM_PARTICIPANTS)]
skip_count, timestamp = get_skips_and_block_making_time(chains[next_validator_id], indices[next_validator_id])
assert skip_count == 0
b = make_block(chains[0], privkeys[next_validator_id],
               randaos[next_validator_id], indices[next_validator_id], skip_count)
print 'Block timestamp:', b.header.timestamp, s.timestamp, timestamp
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
x = chains[0].state.gas_used
t = Transaction(1, 0, 10**6, casper_config['CASPER_ADDR'], 0, ct.encode('includeDunkle', [rlp.encode(b3.header)])).sign(privkeys[0])
apply_transaction(chains[0].state, t)
x2 = chains[0].state.gas_used
assert x2 - x == t.startgas, (x2 - x, t.startgas)
print 'Dunkle addition failed, as expected, since dunkle is a duplicate'
