from ethereum import utils
from ethereum.state import State
from ethereum import vm
from ethereum.state_transition import apply_transaction, apply_const_message, validate_block_header, initialize
from ethereum.transactions import Transaction
from ethereum.chain import Chain
from ethereum.parse_genesis_declaration import mk_basic_state
from ethereum import abi
import serpent
from ethereum.config import default_config, Env
import copy
import time

# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

RANDAO_SAVE_INTERVAL = 100

class RandaoSeed():

    def __init__(self, seed, rounds=10**4+1):
        self.medstate = []        
        for i in range(rounds):
            if not i % RANDAO_SAVE_INTERVAL:
                self.medstate.append(seed)
            seed = utils.sha3(seed)

    def get(self, index):
        med = self.medstate[index // RANDAO_SAVE_INTERVAL]
        for i in range(index % RANDAO_SAVE_INTERVAL):
            med = utils.sha3(med)
        return med

    def get_parent(self, val):
        origval = val
        for i in range(RANDAO_SAVE_INTERVAL):
            if val in self.medstate:
                o = self.get(self.medstate.index(val) * RANDAO_SAVE_INTERVAL - i - 1)
                assert utils.sha3(o) == origval
                return o
            val = utils.sha3(val)
        raise Exception("parent not found")

print 'Initializing privkeys, addresses and randaos for validators'
privkeys = [utils.sha3(str(i)) for i in range(20)]
addrs = [utils.privtoaddr(k) for k in privkeys]
randaos = [RandaoSeed(utils.sha3(str(i))) for i in range(20)]
deposit_sizes = [128] * 15 + [256] * 5
indices = [None] * 20

casper_config = copy.deepcopy(default_config)
casper_config['HOMESTEAD_FORK_BLKNUM'] = 0
casper_config['METROPOLIS_FORK_BLKNUM'] = 0
casper_config['SERENITY_FORK_BLKNUM'] = 0
casper_config['CONSENSUS_ALGO'] = 'contract'

print 'Constructing genesis'

def get_contract_code(init_code):
    s = State(env=Env(config=casper_config))
    s.gas_limit = 10**9
    apply_transaction(s, Transaction(0, 0, 10**8, '', 0, init_code))
    addr = utils.mk_metropolis_contract_address(casper_config['METROPOLIS_ENTRY_POINT'], init_code)
    o = s.get_code(addr)
    assert o
    return o

print 'Creating casper contract'
import os
mydir = os.path.split(__file__)[0]
casper_path = os.path.join(mydir, 'casper_contract.py')
ct = abi.ContractTranslator(serpent.mk_full_signature(open(casper_path).read()))
s = mk_basic_state({}, None, env=Env(config=casper_config))
s.gas_limit = 10**9
s.prev_headers[0].timestamp = int(time.time())
s.timestamp = int(time.time())
casper_code = get_contract_code(serpent.compile(open(casper_path).read()))
casper_addr = utils.normalize_address(255)
s.set_code(casper_addr, casper_code)
assert len(casper_code)
print 'Casper contract created, code length %d' % len(casper_code)

def generate_validation_code(addr):
    code = """
# First 32 bytes of input = hash, remaining 96 = signature
mustbe = %s
a = ecrecover(~calldataload(0), ~calldataload(32), ~calldataload(64), ~calldataload(96))
if a != mustbe:
    ~invalid()
return(1)
    """ % ('0x'+utils.normalize_address(addr).encode('hex'))
    return get_contract_code(serpent.compile(code))

# Add all validators
for i, k, a, r, ds in zip(range(len(privkeys)), privkeys, addrs, randaos, deposit_sizes):
    # Leave 1 eth to pay txfees
    s.set_balance(a, (ds + 1) * 10**18)
    t = Transaction(0, 0, 10**8, casper_addr, ds * 10**18, ct.encode('deposit', [generate_validation_code(a), r.get(9999)])).sign(k)
    import sys
    o = []
    s.log_listeners.append(lambda l: o.append(ct.listen(l)))
    success, gas, logs = apply_transaction(s, t)
    s.log_listeners.pop()
    indices[i] = [o[-1]["i"], o[-1]["j"]]
    print 'Indices of validator %d: %d %d' % (i, indices[i][0], indices[i][1])


def call_casper(state, fun, args, gas=1000000, value=0):
    abidata = vm.CallData([utils.safe_ord(x) for x in ct.encode(fun, args)])
    msg = vm.Message(casper_config['METROPOLIS_ENTRY_POINT'], casper_addr,
                     value, gas, abidata, code_address=casper_addr)
    o = apply_const_message(state, msg)
    if o:
        return ct.decode(fun, ''.join(map(chr, o)))[0]
    else:
        return None

# Set genesis time
t = Transaction(0, 0, 10**8, casper_addr, 0, ct.encode('setGenesisTimestamp', [int(time.time())]))
apply_transaction(s, t)
     
s.commit()
print 'Checking validator deposit total'
assert call_casper(s, 'getTotalDeposits', []) == sum(deposit_sizes) * 10**18
print 'Validator deposit total consistent'

next_validator = call_casper(s, 'getValidator', [0])
print 'Next validator:', next_validator
next_validator_index = [i for i in range(len(indices)) if indices[i] == next_validator][0]
print 'Index in set:', next_validator_index

def get_skips_and_block_making_time(chain, my_indices):
    skips = 0
    while skips < 100:
        i, j = call_casper(chain.state, 'getValidator', [skips])
        if (my_indices[0], my_indices[1]) == (i, j):
            break
        skips += 1
    return skips, call_casper(chain.state, 'getMinTimestamp', [skips]) + 3

def sign_block(block, key, randao_parent, skips):
    block.header.extra_data = randao_parent + utils.zpad(utils.encode_int(skips), 32)
    for val in utils.ecsign(block.header.signing_hash, key):
        block.header.extra_data += utils.zpad(utils.encode_int(val), 32)
    return block

def make_block(chain, key, randao, my_indices):
    skips, timestamp = get_skips_and_block_making_time(chain, my_indices)
    print 'target timestamp', timestamp
    h = chain.make_head_candidate(timestamp=timestamp)
    print 'Making a block with %d skips' % skips
    return sign_block(h, key, randao.get_parent(call_casper(chain.state, 'getRandao', [my_indices[0], my_indices[1]])), skips)

chains = [Chain(s.to_snapshot(), env=s.env) for i in range(20)]

b = make_block(chains[next_validator_index], privkeys[next_validator_index], randaos[next_validator_index], indices[next_validator_index])
initialize(s, b)
assert validate_block_header(s, b.header)
