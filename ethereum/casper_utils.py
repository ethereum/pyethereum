from ethereum import utils
from ethereum.state import State
from ethereum.transactions import Transaction
from ethereum.config import Env, default_config
from ethereum.state_transition import apply_transaction, apply_const_message
from ethereum.parse_genesis_declaration import mk_basic_state
from ethereum import vm
from ethereum import abi
import copy
import os
mydir = os.path.split(__file__)[0]
casper_path = os.path.join(mydir, 'casper_contract.py')
rlp_decoder_path = os.path.join(mydir, 'rlp_decoder_contract.py')
hash_without_ed_path = os.path.join(mydir, 'hash_without_ed_contract.py')
validator_sizes = [64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072]

# The casper Code
def get_casper_code():
    import serpent
    return get_contract_code(serpent.compile(open(casper_path).read()))

# RLP decoder code
def get_rlp_decoder_code():
    import serpent
    return get_contract_code(serpent.compile(open(rlp_decoder_path).read()))

# RLP decoder code
def get_hash_without_ed_code():
    import serpent
    return get_contract_code(serpent.compile(open(hash_without_ed_path).read()))

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
casper_config['HEADER_VALIDATION'] = 'contract'
casper_config['CASPER_ADDR'] = utils.int_to_addr(255)
casper_config['RLP_DECODER_ADDR'] = utils.int_to_addr(253)
casper_config['HASH_WITHOUT_BLOOM_ADDR'] = utils.int_to_addr(252)
casper_config['MAX_UNCLE_DEPTH'] = 0
casper_config['PREV_HEADER_DEPTH'] = 1

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
~log1(0, 0, mustbe)
a = ecrecover(~calldataload(0), ~calldataload(32), ~calldataload(64), ~calldataload(96))
~log1(1, 1, a)
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

# Check a particular count of skips
def check_skips(chain, my_indices, skips):
    indices = call_casper(chain.state, 'getValidator', [skips])
    return indices and (my_indices[0], my_indices[1]) == (indices[0], indices[1])

# Get timestamp given a particular number of skips
def get_timestamp(chain, skips):
    # Add three because the context the function will be called in will be one
    # block height later
    return call_casper(chain.state, 'getMinTimestamp', [skips]) + 3 

# Add a signature to a block
def sign_block(block, key, randao_parent, indices, skips):
    block.header.extra_data = \
        randao_parent + \
        utils.zpad(utils.encode_int(skips), 32) + \
        utils.zpad(utils.encode_int(indices[0]), 32) + \
        utils.zpad(utils.encode_int(indices[1]), 32)
    print 'key', repr(key), utils.privtoaddr(key).encode('hex')
    for val in utils.ecsign(block.header.signing_hash, key):
        block.header.extra_data += utils.zpad(utils.encode_int(val), 32)
    return block

# Create and sign a block
def make_block(chain, key, randao, indices, skips):
    h = chain.make_head_candidate(timestamp=get_timestamp(chain, skips))
    return sign_block(h, key, randao.get_parent(call_casper(chain.state, 'getRandao', [indices[0], indices[1]])), indices, skips)

# Create a casper genesis from given parameters
# Validators: (vcode, deposit_size, randao_commitment)
# Alloc: state declaration
def make_casper_genesis(validators, alloc, timestamp=0, epoch_length=100):
    state = mk_basic_state({}, None, env=Env(config=casper_config))
    state.gas_limit = 10**8 * (len(validators) + 1)
    state.prev_headers[0].timestamp = timestamp
    state.prev_headers[0].difficulty = 1
    state.timestamp = timestamp
    state.block_difficulty = 1
    state.set_code(casper_config['CASPER_ADDR'], get_casper_code())
    state.set_code(casper_config['RLP_DECODER_ADDR'], get_rlp_decoder_code())
    state.set_code(casper_config['HASH_WITHOUT_BLOOM_ADDR'], get_hash_without_ed_code())
    state.set_code(casper_config['METROPOLIS_STATEROOT_STORE'], casper_config['SERENITY_GETTER_CODE'])
    state.set_code(casper_config['METROPOLIS_BLOCKHASH_STORE'], casper_config['SERENITY_GETTER_CODE'])
    ct = get_casper_ct()
    # Set genesis time, and initialize epoch number
    t = Transaction(0, 0, 10**8, casper_config['CASPER_ADDR'], 0, ct.encode('initialize', [timestamp, epoch_length]))
    apply_transaction(state, t)
    # Add validators
    for i, (vcode, deposit_size, randao_commitment) in enumerate(validators):
        state.set_balance(utils.int_to_addr(1), deposit_size)
        t = Transaction(i, 0, 10**8, casper_config['CASPER_ADDR'], deposit_size,
                        ct.encode('deposit', [vcode, randao_commitment]))
        t._sender = utils.int_to_addr(1)
        success = apply_transaction(state, t)
        assert success
    for addr, data in alloc.items():
        addr = utils.normalize_address(addr)
        assert len(addr) == 20
        if 'wei' in data:
            state.set_balance(addr, utils.parse_as_int(data['wei']))
        if 'balance' in data:
            state.set_balance(addr, utils.parse_as_int(data['balance']))
        if 'code' in data:
            state.set_code(addr, utils.parse_as_bin(data['code']))
        if 'nonce' in data:
            state.set_nonce(addr, utils.parse_as_int(data['nonce']))
        if 'storage' in data:
            for k, v in data['storage'].items():
                state.set_storage_data(addr, utils.parse_as_bin(k), utils.parse_as_bin(v))
    # Start the first epoch
    t = Transaction(1, 0, 10**8, casper_config['CASPER_ADDR'], 0, ct.encode('newEpoch', []))
    apply_transaction(state, t)
    assert call_casper(state, 'getEpoch', []) == 0
    assert call_casper(state, 'getTotalDeposits', []) == sum([d for a,d,r in validators])
    state.commit()
    return state


def find_indices(state, vcode):
    for i in range(len(validator_sizes)):
        epoch = state.block_number // call_casper(state, 'getEpochLength', [])
        valcount = call_casper(state, 'getHistoricalValidatorCount', [epoch, i])
        for j in range(valcount):
            valcode = call_casper(state, 'getValidationCode', [i, j])
            if valcode == vcode:
                return [i, j]
    return None
