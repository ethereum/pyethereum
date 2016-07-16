from ethereum import utils
from ethereum.state import State
from ethereum.transactions import Transaction
from ethereum.config import Env, default_config
from ethereum.state_transition import apply_transaction, apply_const_message
from ethereum import vm
from ethereum import abi
import copy
import os
mydir = os.path.split(__file__)[0]
casper_path = os.path.join(mydir, 'casper_contract.py')

# The casper Code
def get_casper_code():
    import serpent
    return get_contract_code(serpent.compile(open(casper_path).read()))

_casper_ct = None

def get_casper_ct():
    import serpent
    global _casper_ct
    if not _casper_ct:
        _casper_ct = abi.ContractTranslator(serpent.mk_full_signature(open(casper_path).read()))
    return _casper_ct

# The Casper-specific config declaration
casper_config = copy.deepcopy(default_config)
casper_config['HOMESTEAD_FORK_BLKNUM'] = 0
casper_config['METROPOLIS_FORK_BLKNUM'] = 0
casper_config['SERENITY_FORK_BLKNUM'] = 0
casper_config['CONSENSUS_ALGO'] = 'contract'
casper_config['CASPER_ADDR'] = utils.int_to_addr(255)

# RandaoManager object to be used by validators to provide randaos
# when signing their block
RANDAO_SAVE_INTERVAL = 100

class RandaoManager():

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

# Get the final saved code of a contract from the init code
def get_contract_code(init_code):
    s = State(env=Env(config=casper_config))
    s.gas_limit = 10**9
    apply_transaction(s, Transaction(0, 0, 10**8, '', 0, init_code))
    addr = utils.mk_metropolis_contract_address(casper_config['METROPOLIS_ENTRY_POINT'], init_code)
    o = s.get_code(addr)
    assert o
    return o

# Create the validation code for a given address
def generate_validation_code(addr):
    import serpent
    code = """
# First 32 bytes of input = hash, remaining 96 = signature
mustbe = %s
a = ecrecover(~calldataload(0), ~calldataload(32), ~calldataload(64), ~calldataload(96))
if a != mustbe:
    ~invalid()
return(1)
    """ % ('0x'+utils.normalize_address(addr).encode('hex'))
    return get_contract_code(serpent.compile(code))

# Call the casper contract statically, 
# eg. x = call_casper(state, 'getValidationCode', [2, 5])
def call_casper(state, fun, args, gas=1000000, value=0):
    ct = get_casper_ct()
    abidata = vm.CallData([utils.safe_ord(x) for x in ct.encode(fun, args)])
    msg = vm.Message(casper_config['METROPOLIS_ENTRY_POINT'], casper_config['CASPER_ADDR'],
                     value, gas, abidata, code_address=casper_config['CASPER_ADDR'])
    o = apply_const_message(state, msg)
    if o:
        return ct.decode(fun, ''.join(map(chr, o)))[0]
    else:
        return None

# Get the number of skips needed to make a block on the current
# parent
def get_skips_and_block_making_time(chain, my_indices, max_lookup=100):
    skips = 0
    while skips < max_lookup:
        indices = call_casper(chain.state, 'getValidator', [skips])
        if indices and (my_indices[0], my_indices[1]) == (indices[0], indices[1]):
            return skips, call_casper(chain.state, 'getMinTimestamp', [skips]) + 3
        skips += 1
    return None, None

# Add a signature to a block
def sign_block(block, key, randao_parent, skips):
    block.header.extra_data = randao_parent + utils.zpad(utils.encode_int(skips), 32)
    for val in utils.ecsign(block.header.signing_hash, key):
        block.header.extra_data += utils.zpad(utils.encode_int(val), 32)
    return block

# Create and sign a block
def make_block(chain, key, randao, my_indices):
    skips, timestamp = get_skips_and_block_making_time(chain, my_indices)
    h = chain.make_head_candidate(timestamp=timestamp)
    print 'Making a block with %d skips' % skips
    return sign_block(h, key, randao.get_parent(call_casper(chain.state, 'getRandao', [my_indices[0], my_indices[1]])), skips)
