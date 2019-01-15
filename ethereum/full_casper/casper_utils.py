# TODO: integrate this and make it actually work as a consensus strategy
import os
import copy
import rlp
from ethereum import utils
from ethereum.utils import sha3, ecsign, encode_int32
from ethereum.transactions import Transaction
from ethereum.config import Env, default_config
from ethereum.state_transition import apply_transaction, apply_const_message, \
    apply_message, initialize
from ethereum.block import Block, BlockHeader
from ethereum.state import State
from ethereum.parse_genesis_declaration import mk_basic_state
from ethereum import vm
from ethereum import abi
from ethereum.slogging import get_logger

log_bc = get_logger('eth.block_creation')
mydir = os.path.split(__file__)[0]
casper_path = os.path.join(mydir, 'casper_contract.py')
rlp_decoder_path = os.path.join(mydir, 'rlp_decoder_contract.py')
hash_without_ed_path = os.path.join(mydir, 'hash_without_ed_contract.py')
finalizer_path = os.path.join(mydir, 'finalizer_contract.py')


# Get the final saved code of a contract from the init code
def get_contract_code(init_code):
    s = State(env=Env(config=casper_config))
    s.gas_limit = 10**9
    apply_transaction(s, Transaction(0, 0, 10**8, '', 0, init_code))
    addr = utils.mk_metropolis_contract_address(
        casper_config['METROPOLIS_ENTRY_POINT'], init_code)
    o = s.get_code(addr)
    assert o
    return o


_casper_code = None
_rlp_decoder_code = None
_hash_without_ed_code = None
_finalizer_code = None


def get_casper_code():
    global _casper_code
    if not _casper_code:
        import serpent
        _casper_code = get_contract_code(
            serpent.compile(open(casper_path).read()))
    return _casper_code


def get_rlp_decoder_code():
    global _rlp_decoder_code
    if not _rlp_decoder_code:
        import serpent
        _rlp_decoder_code = get_contract_code(
            serpent.compile(open(rlp_decoder_path).read()))
    return _rlp_decoder_code


def get_hash_without_ed_code():
    global _hash_without_ed_code
    if not _hash_without_ed_code:
        import serpent
        _hash_without_ed_code = get_contract_code(
            serpent.compile(open(hash_without_ed_path).read()))
    return _hash_without_ed_code


def get_finalizer_code():
    global _finalizer_code
    if not _finalizer_code:
        import serpent
        _finalizer_code = get_contract_code(
            serpent.compile(open(finalizer_path).read()))
    return _finalizer_code


# The Casper-specific config declaration
casper_config = copy.deepcopy(default_config)
casper_config['HOMESTEAD_FORK_BLKNUM'] = 0
casper_config['METROPOLIS_FORK_BLKNUM'] = 0
casper_config['SERENITY_FORK_BLKNUM'] = 0
# config['CASPER_ADDR'] == config['SERENITY_HEADER_VERIFIER']
casper_config['CASPER_ADDR'] = utils.int_to_addr(255)
casper_config['RLP_DECODER_ADDR'] = utils.int_to_addr(253)
casper_config['HASH_WITHOUT_BLOOM_ADDR'] = utils.int_to_addr(252)
casper_config['MAX_UNCLE_DEPTH'] = 0
casper_config['PREV_HEADER_DEPTH'] = 1
casper_config['CONSENSUS_STRATEGY'] = 'casper'


_casper_ct = None


def get_casper_ct():
    import serpent
    global _casper_ct
    if not _casper_ct:
        _casper_ct = abi.ContractTranslator(
            serpent.mk_full_signature(
                open(casper_path).read()))
    return _casper_ct


# RandaoManager object to be used by validators to provide randaos
# when signing their block
RANDAO_SAVE_INTERVAL = 100


class RandaoManager():

    def __init__(self, seed, rounds=10**4 + 1):
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
                o = self.get(self.medstate.index(val) *
                             RANDAO_SAVE_INTERVAL - i - 1)
                assert utils.sha3(o) == origval
                return o
            val = utils.sha3(val)
        raise Exception("Randao parent not found")


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
    """ % ('0x' + utils.normalize_address(addr).encode('hex'))
    return get_contract_code(serpent.compile(code))


# Call the casper contract statically,
# eg. x = call_casper(state, 'getValidationCode', [2, 5])
def call_casper(state, fun, args=[], gas=1000000, value=0):
    ct = get_casper_ct()
    abidata = vm.CallData([utils.safe_ord(x) for x in ct.encode(fun, args)])
    msg = vm.Message(casper_config['METROPOLIS_ENTRY_POINT'], casper_config['CASPER_ADDR'],
                     value, gas, abidata)
    o = apply_const_message(state, msg)
    if o:
        # print 'cc', fun, args, ct.decode(fun, o)[0]
        return ct.decode(fun, o)[0]
    else:
        return None


# Get the number of skips needed to make a block on the current
# parent
def get_skips_and_block_making_time(state, vchash, max_lookup=100):
    skips = 0
    while skips < max_lookup:
        vchash2 = call_casper(state, 'getValidator', [skips])
        if vchash2 and vchash2 == vchash:
            return skips, call_casper(state, 'getMinTimestamp', [skips]) + 3
        skips += 1
    return None, None


# Check a particular count of skips
def check_skips(chain, vchash, skips):
    vchash2 = call_casper(chain.state, 'getValidator', [skips])
    return vchash2 and vchash2 == vchash


# Get timestamp given a particular number of skips
def get_timestamp(chain, skips):
    # Add three because the context the function will be called in will be one
    # block height later
    return call_casper(chain.state, 'getMinTimestamp', [skips]) + 3


# Add a signature to a block
def sign_block(block, key, randao_parent, vchash, skips):
    block.header.extra_data = \
        randao_parent + \
        utils.zpad(utils.encode_int(skips), 32) + \
        vchash
    for val in utils.ecsign(block.header.signing_hash, key):
        block.header.extra_data += utils.zpad(utils.encode_int(val), 32)
    return block


# Sign a withdrawal request
def make_withdrawal_signature(key):
    h = sha3(b'withdrawwithdrawwithdrawwithdraw')
    v, r, s = ecsign(h, key)
    return encode_int32(v) + encode_int32(r) + encode_int32(s)


def casper_contract_bootstrap(
        state, timestamp=0, epoch_length=100, number=0, gas_limit=4712388, nonce=0):
    ct = get_casper_ct()
    # Set genesis time, and initialize epoch number
    t = Transaction(nonce,
                    0,
                    10**8,
                    casper_config['CASPER_ADDR'],
                    0,
                    ct.encode('initialize',
                              [timestamp,
                               epoch_length,
                               number,
                               gas_limit]))
    success, output = apply_transaction(state, t)
    assert success


def validator_inject(state, vcode, deposit_size,
                     randao_commitment, address, nonce=0, ct=None):
    if not ct:
        ct = get_casper_ct()
    state.set_balance(utils.int_to_addr(1), deposit_size)
    t = Transaction(nonce, 0, 10**8, casper_config['CASPER_ADDR'], deposit_size,
                    ct.encode('deposit', [vcode, randao_commitment, address]))
    t._sender = utils.int_to_addr(1)
    success, output = apply_transaction(state, t)
    assert success


def casper_state_initialize(state):
    config = state.config

    # preparation for casper
    # TODO: maybe serveral blocks before serenity hf?
    if state.is_SERENITY(at_fork_height=True):
        state.set_code(config['CASPER_ADDR'], get_casper_code())
        state.set_code(config['RLP_DECODER_ADDR'], get_rlp_decoder_code())
        state.set_code(
            config['HASH_WITHOUT_BLOOM_ADDR'],
            get_hash_without_ed_code())
        state.set_code(
            config['SERENITY_HEADER_POST_FINALIZER'],
            get_finalizer_code())
        state.set_code(
            config['METROPOLIS_STATEROOT_STORE'],
            config['SERENITY_GETTER_CODE'])
        state.set_code(
            config['METROPOLIS_BLOCKHASH_STORE'],
            config['SERENITY_GETTER_CODE'])


# Create a casper genesis from given parameters
# Validators: (vcode, deposit_size, randao_commitment)
# Alloc: state declaration
def make_casper_genesis(validators, alloc, timestamp=0, epoch_length=100):
    state = mk_basic_state(alloc, None, env=Env(config=casper_config))
    state.gas_limit = 10**8 * (len(validators) + 1)
    state.timestamp = timestamp
    state.block_difficulty = 1

    header = state.prev_headers[0]
    header.timestamp = timestamp
    header.difficulty = 1

    ct = get_casper_ct()
    initialize(state)
    casper_contract_bootstrap(
        state,
        timestamp=header.timestamp,
        gas_limit=header.gas_limit)

    # Add validators
    for i, (vcode, deposit_size, randao_commitment,
            address) in enumerate(validators):
        validator_inject(
            state,
            vcode,
            deposit_size,
            randao_commitment,
            address,
            i,
            ct)

    # Start the first epoch
    casper_start_epoch(state)

    assert call_casper(state, 'getEpoch', []) == 0
    assert call_casper(state, 'getTotalDeposits', []) == sum(
        [d for a, d, r, a in validators])
    state.set_storage_data(utils.normalize_address(state.config['METROPOLIS_BLOCKHASH_STORE']),
                           state.block_number % state.config['METROPOLIS_WRAPAROUND'],
                           header.hash)
    state.commit()

    return state


def casper_start_epoch(state):
    ct = get_casper_ct()
    t = Transaction(
        0,
        0,
        10**8,
        casper_config['CASPER_ADDR'],
        0,
        ct.encode(
            'newEpoch',
            [0]))
    t._sender = casper_config['CASPER_ADDR']
    apply_transaction(state, t)


def get_dunkle_candidates(chain, state, scan_limit=10):
    blknumber = call_casper(state, 'getBlockNumber')
    anc = chain.get_block(
        chain.get_blockhash_by_number(
            blknumber - scan_limit))
    if anc:
        descendants = chain.get_descendants(anc)
    else:
        descendants = chain.get_descendants(
            chain.get_block(chain.db.get(b'GENESIS_HASH')))
    potential_uncles = [
        x for x in descendants if x not in chain and isinstance(
            x, Block)]
    uncles = [x.header for x in potential_uncles if not call_casper(
        chain.state, 'isDunkleIncluded', [x.header.hash])]
    dunkle_txs = []
    ct = get_casper_ct()
    start_nonce = state.get_nonce(state.config['METROPOLIS_ENTRY_POINT'])
    for i, u in enumerate(uncles[:4]):
        txdata = ct.encode('includeDunkle', [rlp.encode(u)])
        dunkle_txs.append(
            Transaction(
                start_nonce + i,
                0,
                650000,
                chain.config['CASPER_ADDR'],
                0,
                txdata))
    return dunkle_txs


def casper_setup_block(chain, state=None, timestamp=None,
                       coinbase=b'\x35' * 20, extra_data='moo ha ha says the laughing cow.'):
    state = state or chain.state
    blk = Block(BlockHeader())
    now = timestamp or chain.time()
    prev_blknumber = call_casper(state, 'getBlockNumber')
    blk.header.number = prev_blknumber + 1
    blk.header.difficulty = 1
    blk.header.gas_limit = call_casper(state, 'getGasLimit')
    blk.header.timestamp = max(now, state.prev_headers[0].timestamp + 1)
    blk.header.prevhash = apply_const_message(state,
                                              sender=casper_config['METROPOLIS_ENTRY_POINT'],
                                              to=casper_config['METROPOLIS_BLOCKHASH_STORE'],
                                              data=utils.encode_int32(prev_blknumber))
    blk.header.coinbase = coinbase
    blk.header.extra_data = extra_data
    blk.header.bloom = 0
    blk.uncles = []
    initialize(state, blk)
    for tx in get_dunkle_candidates(chain, state):
        assert apply_transaction(state, tx)
        blk.transactions.append(tx)
    log_bc.info('Block set up with number %d and prevhash %s, %d dunkles' %
                (blk.header.number, utils.encode_hex(blk.header.prevhash), len(blk.transactions)))
    return blk


def casper_validate_header(state, header):
    output = apply_const_message(state,
                                 sender=state.config['SYSTEM_ENTRY_POINT'],
                                 to=state.config['SERENITY_HEADER_VERIFIER'],
                                 data=rlp.encode(header))
    if output is None:
        raise ValueError("Validation call failed with exception")
    elif output:
        raise ValueError(output)


def casper_post_finalize_block(state, block):
    apply_message(state,
                  sender=state.config['SYSTEM_ENTRY_POINT'],
                  to=state.config['SERENITY_HEADER_POST_FINALIZER'],
                  data=rlp.encode(block.header))
