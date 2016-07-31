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
    get_hash_without_ed_code
import serpent
from ethereum.config import default_config, Env
import copy
import time

# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

NUM_PARTICIPANTS = 20

print 'Initializing privkeys, addresses and randaos for validators'
privkeys = [utils.sha3(str(i)) for i in range(NUM_PARTICIPANTS)]
addrs = [utils.privtoaddr(k) for k in privkeys]
randaos = [RandaoManager(utils.sha3(str(i))) for i in range(NUM_PARTICIPANTS)]
deposit_sizes = [256] * (NUM_PARTICIPANTS // 4) + [128] * (NUM_PARTICIPANTS - (NUM_PARTICIPANTS // 4))
indices = [None] * NUM_PARTICIPANTS

print 'Constructing genesis'

print 'Creating casper contract'
casper_code = get_casper_code()
rlp_decoder_code = get_rlp_decoder_code()
hash_without_ed_code = get_hash_without_ed_code()
ct = get_casper_ct()
assert ct
s = mk_basic_state({}, None, env=Env(config=casper_config))
s.gas_limit = 10**9
s.prev_headers[0].timestamp = int(time.time())
s.prev_headers[0].difficulty = 1
s.timestamp = int(time.time())
s.block_difficulty = 1
s.set_code(casper_config['CASPER_ADDR'], casper_code)
s.set_code(casper_config['RLP_DECODER_ADDR'], rlp_decoder_code)
s.set_code(casper_config['HASH_WITHOUT_BLOOM_ADDR'], hash_without_ed_code)
assert len(casper_code)
print 'Casper contract created, code length %d' % len(casper_code)

# Add all validators
for i, k, a, r, ds in zip(range(len(privkeys)), privkeys, addrs, randaos, deposit_sizes):
    # Leave 1 eth to pay txfees
    s.set_balance(a, (ds + 1) * 10**18)
    t = Transaction(0, 0, 10**8, casper_config['CASPER_ADDR'], ds * 10**18, ct.encode('deposit', [generate_validation_code(a), r.get(9999)])).sign(k)
    import sys
    o = []
    s.log_listeners.append(lambda l: o.append(ct.listen(l)))
    success, gas, logs = apply_transaction(s, t)
    s.log_listeners.pop()
    indices[i] = [o[-1]["i"], o[-1]["j"]]
    print 'Indices of validator %d: %d %d' % (i, indices[i][0], indices[i][1])

# Set genesis time
t = Transaction(0, 0, 10**8, casper_config['CASPER_ADDR'], 0, ct.encode('setGenesisTimestamp', [int(time.time())]))
apply_transaction(s, t)
     
s.commit()
print 'Checking validator deposit total'
assert call_casper(s, 'getTotalDeposits', []) == sum(deposit_sizes) * 10**18
print 'Validator deposit total consistent'

next_validator = call_casper(s, 'getValidator', [0])
print 'Next validator:', next_validator
next_validator_index = [i for i in range(len(indices)) if indices[i] == next_validator][0]
print 'Index in set:', next_validator_index


chains = [Chain(s.to_snapshot(), env=s.env) for i in range(NUM_PARTICIPANTS)]
skip_count, timestamp = get_skips_and_block_making_time(chains[next_validator_index], indices[next_validator_index])
b = make_block(chains[next_validator_index], privkeys[next_validator_index],
               randaos[next_validator_index], indices[next_validator_index], skip_count)
initialize(s, b)
print 'Validating block'
print b.header.difficulty, s.block_difficulty
assert validate_block_header(s, b.header)
print 'Validation successful'
