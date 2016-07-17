import rlp
from ethereum.utils import normalize_address, hash32, trie_root, \
    big_endian_int, address, int256, encode_int, \
    safe_ord, int_to_addr, sha3, big_endian_to_int
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from rlp.utils import decode_hex, encode_hex, ascii_chr
from ethereum import utils
from ethereum import trie
from ethereum import bloom
from ethereum import transactions
from ethereum.trie import Trie
from ethereum.securetrie import SecureTrie
from ethereum import opcodes
from ethereum.state import get_block
from ethereum.processblock import apply_msg, create_contract, _apply_msg, Log
from ethereum import vm
from ethereum.specials import specials
from config import default_config
from db import BaseDB, EphemDB
from ethereum.exceptions import InvalidNonce, InsufficientStartGas, UnsignedTransaction, \
        BlockGasLimitReached, InsufficientBalance
import sys
if sys.version_info.major == 2:
    from repoze.lru import lru_cache
else:
    from functools import lru_cache
from ethereum.slogging import get_logger

log = get_logger('eth.block')
log_tx = get_logger('eth.pb.tx')
log_msg = get_logger('eth.pb.msg')
log_state = get_logger('eth.pb.msg.state')

# contract creating transactions send to an empty address
CREATE_CONTRACT_ADDRESS = b''

VERIFIERS = {
    'ethash': lambda state, header: header.check_pow(),
    'contract': lambda state, header: ''.join(map(chr, apply_const_message(state, vm.Message(int_to_addr(254), int_to_addr(255), 0, 1000000, vm.CallData([ord(x) for x in header.signing_hash+header.extra_data]), code_address=int_to_addr(255)))))
}

def initialize(state, block):
    pre_root = state.trie.root_hash or ('\x00' * 32)
    state.txindex = 0
    state.gas_used = 0
    state.bloom = 0
    state.timestamp = block.header.timestamp
    state.gas_limit = block.header.gas_limit
    state.block_number = block.header.number
    state.recent_uncles[state.block_number] = [x.hash for x in block.uncles]
    state.block_coinbase = block.header.coinbase
    state.block_difficulty = block.header.difficulty
    if state.is_METROPOLIS(at_fork_height=True):
        self.set_code(utils.normalize_address(
            state.config["METROPOLIS_STATEROOT_STORE"]), state.config["METROPOLIS_GETTER_CODE"])
        self.set_code(utils.normalize_address(
            state.config["METROPOLIS_BLOCKHASH_STORE"]), state.config["METROPOLIS_GETTER_CODE"])
    if state.is_METROPOLIS():
        state.set_storage_data(utils.normalize_address(state.config["METROPOLIS_STATEROOT_STORE"]),
                               state.block_number % state.config["METROPOLIS_WRAPAROUND"],
                               pre_root)
        state.set_storage_data(utils.normalize_address(state.config["METROPOLIS_BLOCKHASH_STORE"]),
                               state.block_number % state.config["METROPOLIS_WRAPAROUND"],
                               state.prev_headers[0].hash if state.prev_headers else '\x00' * 32)
    if state.is_DAO(at_fork_height=True):
        for acct in state.config['CHILD_DAO_LIST']:
            state.transfer_value(acct, state.config['DAO_WITHDRAWER'], state.get_balance(acct))


def finalize(state, block):
    """Apply rewards and commit."""
    delta = int(state.config['BLOCK_REWARD'] + state.config['NEPHEW_REWARD'] * len(block.uncles))
    state.delta_balance(state.block_coinbase, delta)

    br = state.config['BLOCK_REWARD']
    udpf = state.config['UNCLE_DEPTH_PENALTY_FACTOR']

    for uncle in block.uncles:
        r = int(br * (udpf + uncle.number - state.block_number) // udpf)

        state.delta_balance(uncle.coinbase, r)
    if state.block_number - state.config['MAX_UNCLE_DEPTH'] in state.recent_uncles:
        del state.recent_uncles[state.block_number - state.config['MAX_UNCLE_DEPTH']]
    state.commit()
    state.reset_journal()
    state.add_block_header(block.header)


def apply_block(state, block, creating=False):
    # Pre-processing and verification
    snapshot = state.snapshot()
    assert validate_block_header(state, block.header)
    assert validate_uncles(state, block)
    initialize(state, block)
    receipts = []
    # Process transactions
    for tx in block.transactions:
        success, output, logs = apply_transaction(state, tx)
        if state.block_number >= state.config["METROPOLIS_FORK_BLKNUM"]:
            r = Receipt('\x00' * 32, state.gas_used, logs)
        else:
            r = Receipt(state.trie.root_hash, state.gas_used, logs)
        receipts.append(r)
        state.bloom |= r.bloom  # int
        state.txindex += 1
    # Finalize (incl paying block rewards)
    finalize(state, block)
    # Verify state root, tx list root, receipt root
    if creating:
        block.header.receipts_root = mk_receipt_sha(receipts)
        block.header.tx_list_root = mk_transaction_sha(block.transactions)
        block.header.state_root = state.trie.root_hash
    else:
        if block.header.receipts_root != mk_receipt_sha(receipts):
            state.revert(snapshot)
            raise ValueError("Receipt root mismatch: header %s computed %s, %d receipts" %
                             (encode_hex(block.header.receipts_root), encode_hex(mk_receipt_sha(receipts))), len(receipts))
        if block.header.tx_list_root != mk_transaction_sha(block.transactions):
            state.revert(snapshot)
            raise ValueError("Transaction root mismatch: header %s computed %s, %d transactions" %
                             (encode_hex(block.header.tx_list_root), encode_hex(mk_transaction_sha(block.transactions)),
                              len(block.transactions)))
        if block.header.state_root != state.trie.root_hash:
            state.revert(snapshot)
            raise ValueError("State root mismatch: header %s computed %s" %
                             (encode_hex(block.header.state_root), encode_hex(state.trie.root_hash)))
        if block.header.bloom != state.bloom:
            state.revert(snapshot)
            raise ValueError("Bloom mismatch: header %d computed %d" % (block.header.bloom, state.bloom))
        if block.header.gas_used != state.gas_used:
            state.revert(snapshot)
            raise ValueError("Gas used mismatch: header %d computed %d" % (block.header.gas_used, state.gas_used))
    return state, receipts

def validate_transaction(state, tx):

    def rp(what, actual, target):
        return '%r: %r actual:%r target:%r' % (tx, what, actual, target)

    # (1) The transaction signature is valid;
    if not tx.sender:  # sender is set and validated on Transaction initialization
        if state.is_METROPOLIS():
            tx._sender = normalize_address(state.config["METROPOLIS_ENTRY_POINT"])
        else:
            raise UnsignedTransaction(tx)
    if state.is_METROPOLIS():
        tx.check_low_s_metropolis()
    elif state.is_HOMESTEAD():
        tx.check_low_s_homestead()

    # (2) the transaction nonce is valid (equivalent to the
    #     sender account's current nonce);
    acctnonce = state.get_nonce(tx.sender)
    if acctnonce != tx.nonce:
        raise InvalidNonce(rp('nonce', tx.nonce, acctnonce))

    # (3) the gas limit is no smaller than the intrinsic gas,
    # g0, used by the transaction;
    if tx.startgas < tx.intrinsic_gas_used:
        raise InsufficientStartGas(rp('startgas', tx.startgas, tx.intrinsic_gas_used))

    # (4) the sender account balance contains at least the
    # cost, v0, required in up-front payment.
    total_cost = tx.value + tx.gasprice * tx.startgas

    if state.get_balance(tx.sender) < total_cost:
        raise InsufficientBalance(rp('balance', state.get_balance(tx.sender), total_cost))


    # check block gas limit
    if state.gas_used + tx.startgas > state.gas_limit:
        raise BlockGasLimitReached(rp('gaslimit', state.gas_used + tx.startgas, state.gas_limit))

    return True


def apply_const_message(state, msg):
    state1 = state.ephemeral_clone()
    assert state1.config == state.config
    ext = VMExt(state1, transactions.Transaction(0, 0, 21000, '', 0, ''))
    result, gas_remained, data = apply_msg(ext, msg)
    return data if result else None


def apply_transaction(state, tx):
    state.logs = []
    state.suicides = []
    state.refunds = 0
    validate_transaction(state, tx)

    # print(block.get_nonce(tx.sender), '@@@')

    def rp(what, actual, target):
        return '%r: %r actual:%r target:%r' % (tx, what, actual, target)

    intrinsic_gas = tx.intrinsic_gas_used
    if state.is_HOMESTEAD():
        assert tx.s * 2 < transactions.secpk1n
        if not tx.to or tx.to == CREATE_CONTRACT_ADDRESS:
            intrinsic_gas += opcodes.CREATE[3]
            if tx.startgas < intrinsic_gas:
                raise InsufficientStartGas(rp('startgas', tx.startgas, intrinsic_gas))

    log_tx.debug('TX NEW', tx_dict=tx.log_dict())
    # start transacting #################
    state.increment_nonce(tx.sender)

    # buy startgas
    assert state.get_balance(tx.sender) >= tx.startgas * tx.gasprice
    state.delta_balance(tx.sender, -tx.startgas * tx.gasprice)
    message_gas = tx.startgas - intrinsic_gas
    message_data = vm.CallData([safe_ord(x) for x in tx.data], 0, len(tx.data))
    message = vm.Message(tx.sender, tx.to, tx.value, message_gas, message_data, code_address=tx.to)

    # MESSAGE
    ext = VMExt(state, tx)
    if tx.to and tx.to != CREATE_CONTRACT_ADDRESS:
        result, gas_remained, data = apply_msg(ext, message)
        log_tx.debug('_res_', result=result, gas_remained=gas_remained, data=data)
    else:  # CREATE
        result, gas_remained, data = create_contract(ext, message)
        assert utils.is_numeric(gas_remained)
        log_tx.debug('_create_', result=result, gas_remained=gas_remained, data=data)

    assert gas_remained >= 0

    log_tx.debug("TX APPLIED", result=result, gas_remained=gas_remained,
                 data=data)

    if not result:  # 0 = OOG failure in both cases
        log_tx.debug('TX FAILED', reason='out of gas',
                     startgas=tx.startgas, gas_remained=gas_remained)
        state.gas_used += tx.startgas
        state.delta_balance(state.block_coinbase, tx.gasprice * tx.startgas)
        output = b''
        success = 0
    else:
        log_tx.debug('TX SUCCESS', data=data)
        gas_used = tx.startgas - gas_remained
        state.refunds += len(set(state.suicides)) * opcodes.GSUICIDEREFUND
        if state.refunds > 0:
            log_tx.debug('Refunding', gas_refunded=min(state.refunds, gas_used // 2))
            gas_remained += min(state.refunds, gas_used // 2)
            gas_used -= min(state.refunds, gas_used // 2)
            state.refunds = 0
        # sell remaining gas
        state.delta_balance(tx.sender, tx.gasprice * gas_remained)
        state.delta_balance(state.block_coinbase, tx.gasprice * gas_used)
        state.gas_used += gas_used
        if tx.to:
            output = b''.join(map(ascii_chr, data))
        else:
            output = data
        success = 1
    suicides = state.suicides
    state.suicides = []
    for s in suicides:
        state.set_balance(s, 0)
        state.del_account(s)
    logs = state.logs
    state.logs = []
    if not state.is_METROPOLIS() and not SKIP_MEDSTATES:
        state.commit()
    return success, output, logs


def mk_receipt_sha(receipts):
    t = trie.Trie(EphemDB())
    for i, receipt in enumerate(receipts):
        t.update(rlp.encode(i), rlp.encode(receipt))
        # print i, rlp.decode(rlp.encode(receipt))
    return t.root_hash

mk_transaction_sha = mk_receipt_sha

def validate_block_header(state, header):
    o = VERIFIERS[state.config['CONSENSUS_ALGO']](state, header)
    assert o
    # print 'Consensus verification result:', repr(o)
    parent = state.prev_headers[0]
    if parent:
        if header.prevhash != parent.hash:
            raise ValueError("Block's prevhash and parent's hash do not match: block prevhash %s parent hash %s" %
                             (encode_hex(header.prevhash), encode_hex(parent.hash)))
        if header.number != parent.number + 1:
            raise ValueError("Block's number is not the successor of its parent number")
        if not check_gaslimit(parent, header.gas_limit, config=state.config):
            raise ValueError("Block's gaslimit is inconsistent with its parent's gaslimit")
        if header.difficulty != calc_difficulty(parent, header.timestamp, config=state.config):
            raise ValueError("Block's difficulty is inconsistent with its parent's difficulty: parent %d expected %d actual %d" %
                             (parent.difficulty, calc_difficulty(parent, header.timestamp, config=state.config), header.difficulty))
        if header.gas_used > header.gas_limit:
            raise ValueError("Gas used exceeds gas limit")
        if len(header.extra_data) > 32 and not state.is_SERENITY():
            raise ValueError("Extra data too long")
        if len(header.extra_data) > 1024:
            raise ValueError("Extra data too long")
        if header.timestamp <= parent.timestamp:
            raise ValueError("Timestamp equal to or before parent")
        if header.timestamp >= 2**256:
            raise ValueError("Timestamp waaaaaaaaaaayy too large")
    if header.gas_limit >= 2**63:
        raise ValueError("Header gas limit too high")
    return True

def validate_block(state, block):
    state_prime, receipts = apply_block(state, block)


# Gas limit adjustment algo
def calc_gaslimit(parent, config=default_config):
    decay = parent.gas_limit // config['GASLIMIT_EMA_FACTOR']
    new_contribution = ((parent.gas_used * config['BLKLIM_FACTOR_NOM']) //
                        config['BLKLIM_FACTOR_DEN'] // config['GASLIMIT_EMA_FACTOR'])
    gl = max(parent.gas_limit - decay + new_contribution, config['MIN_GAS_LIMIT'])
    if gl < config['GENESIS_GAS_LIMIT']:
        gl2 = parent.gas_limit + decay
        gl = min(config['GENESIS_GAS_LIMIT'], gl2)
    assert check_gaslimit(parent, gl, config=config)
    return gl


def check_gaslimit(parent, gas_limit, config=default_config):
    #  block.gasLimit - parent.gasLimit <= parent.gasLimit // GasLimitBoundDivisor
    gl = parent.gas_limit // config['GASLIMIT_ADJMAX_FACTOR']
    a = bool(abs(gas_limit - parent.gas_limit) <= gl)
    b = bool(gas_limit >= config['MIN_GAS_LIMIT'])
    return a and b


# Difficulty adjustment algo
def calc_difficulty(parent, timestamp, config=default_config):
    offset = parent.difficulty // config['BLOCK_DIFF_FACTOR']
    if parent.number >= (config['METROPOLIS_FORK_BLKNUM'] - 1):
        sign = max((2 if parent.uncles_hash != sha3(rlp.encode([])) else 1) - ((timestamp - parent.timestamp) // config['METROPOLIS_DIFF_ADJUSTMENT_CUTOFF']), -99)
    elif parent.number >= (config['HOMESTEAD_FORK_BLKNUM'] - 1):
        sign = max(1 - ((timestamp - parent.timestamp) // config['HOMESTEAD_DIFF_ADJUSTMENT_CUTOFF']), -99)
    else:
        sign = 1 if timestamp - parent.timestamp < config['DIFF_ADJUSTMENT_CUTOFF'] else -1
    # If we enter a special mode where the genesis difficulty starts off below
    # the minimal difficulty, we allow low-difficulty blocks (this will never
    # happen in the official protocol)
    o = int(max(parent.difficulty + offset * sign, min(parent.difficulty, config['MIN_DIFF'])))
    period_count = (parent.number + 1) // config['EXPDIFF_PERIOD']
    if period_count >= config['EXPDIFF_FREE_PERIODS']:
        o = max(o + 2**(period_count - config['EXPDIFF_FREE_PERIODS']), config['MIN_DIFF'])
    return o


def validate_uncles(state, block):
    """Validate the uncles of this block."""
    # Make sure hash matches up
    if utils.sha3(rlp.encode(block.uncles)) != block.header.uncles_hash:
        assert False
    # Enforce maximum number of uncles
    if len(block.uncles) > state.config['MAX_UNCLES']:
        assert False
    # Uncle must have lower block number than blockj
    for uncle in block.uncles:
        assert uncle.number < block.header.number

    # Check uncle validity
    MAX_UNCLE_DEPTH = state.config['MAX_UNCLE_DEPTH']
    ancestor_chain = [block.header] + [a for a in state.prev_headers[:MAX_UNCLE_DEPTH + 1] if a]
    assert len(ancestor_chain) == min(block.header.number + 1, MAX_UNCLE_DEPTH + 2)
    # Uncles of this block cannot be direct ancestors and cannot also
    # be uncles included 1-6 blocks ago
    ineligible = [b.hash for b in ancestor_chain]
    for blknum, uncles in state.recent_uncles.items():
        if state.block_number > blknum >= state.block_number - MAX_UNCLE_DEPTH:
            ineligible.extend([u for u in uncles])
    eligible_ancestor_hashes = [x.hash for x in ancestor_chain[2:]]
    for uncle in block.uncles:
        if uncle.prevhash not in eligible_ancestor_hashes:
            log.error("Uncle does not have a valid ancestor", block=self,
                      eligible=[encode_hex(x) for x in eligible_ancestor_hashes],
                      uncle_prevhash=encode_hex(uncle.prevhash))
            assert False
        parent = [x for x in ancestor_chain if x.hash == uncle.prevhash][0]
        if uncle.difficulty != calc_difficulty(parent, uncle.timestamp, config=state.config):
            assert False
        if uncle.number != parent.number + 1:
            assert False
        if uncle.timestamp < parent.timestamp:
            assert False
        if not uncle.check_pow():
            assert False
        if uncle.hash in ineligible:
            log.error("Duplicate uncle", block=block,
                      uncle=encode_hex(utils.sha3(rlp.encode(uncle))))
            assert False
        ineligible.append(uncle.hash)
    return True


class VMExt():

    def __init__(self, state, tx):
        self._state = state
        self.get_code = state.get_code
        self.set_code = state.set_code
        self.get_balance = state.get_balance
        self.set_balance = state.set_balance
        self.get_nonce = state.get_nonce
        self.set_nonce = state.set_nonce
        self.increment_nonce = state.increment_nonce
        self.set_storage_data = state.set_storage_data
        self.get_storage_data = state.get_storage_data
        self.get_storage_bytes = state.get_storage_bytes
        self.set_storage_bytes = state.set_storage_bytes
        self.log_storage = lambda x: 'storage logging stub'
        self.add_suicide = lambda x: state.add_suicide(x)
        self.add_refund = lambda x: \
            state.set_param('refunds', state.refunds + x)
        self.block_hash = lambda x: state.get_block_hash(state.block_number - x - 1) \
            if (1 <= state.block_number - x <= 256 and x <= state.block_number) else b''
        self.block_coinbase = state.block_coinbase
        self.block_timestamp = state.timestamp
        self.block_number = state.block_number
        self.block_difficulty = state.block_difficulty
        self.block_gas_limit = state.gas_limit
        self.log = lambda addr, topics, data: \
            state.add_log(Log(addr, topics, data))
        self.create = lambda msg: create_contract(self, msg)
        self.msg = lambda msg: _apply_msg(self, msg, self.get_code(msg.code_address))
        self.blackbox_msg = lambda msg, code: _apply_msg(BlankVMExt(state), msg, code)
        self.account_exists = state.account_exists
        self.post_homestead_hardfork = lambda: state.is_HOMESTEAD()
        self.post_metropolis_hardfork = lambda: state.is_METROPOLIS()
        self.post_serenity_hardfork = lambda: state.is_SERENITY()
        self.snapshot = state.snapshot
        self.revert = state.revert
        self.transfer_value = state.transfer_value
        self.reset_storage = state.reset_storage
        self.tx_origin = tx.sender if tx else '\x00' * 20
        self.tx_gasprice = tx.gasprice if tx else 0


class BlankVMExt():

    def __init__(self, state):
        self._state = state
        self.get_code = lambda addr: ''
        self.set_code = lambda addr, code: None
        self.get_balance = lambda addr: 0
        self.set_balance = lambda addr, value: None
        self.get_nonce = lambda addr: 0
        self.set_nonce = lambda addr, value: None
        self.increment_nonce = lambda addr: None
        self.set_storage_data = lambda addr, value: None
        self.get_storage_data = lambda addr: 0
        self.get_storage_bytes = lambda addr: None
        self.set_storage_bytes = lambda addr, value: None
        self.log_storage = lambda x: 'storage logging stub'
        self.add_suicide = lambda x: None
        self.add_refund = lambda x: None
        self.block_hash = lambda x: '\x00' * 32
        self.block_coinbase = '\x00' * 20
        self.block_timestamp = 0
        self.block_number = 0
        self.block_difficulty = 0
        self.block_gas_limit = 0
        self.log = lambda addr, topics, data: None
        self.create = lambda msg: 0, 0, ''
        self.msg = lambda msg: _apply_msg(
            self, msg, '') if msg.code_address in specials else (0, 0, '')
        self.blackbox_msg = lambda msg, code: 0, 0, ''
        self.account_exists = lambda addr: False
        self.post_homestead_hardfork = lambda: state.is_HOMESTEAD()
        self.post_metropolis_hardfork = lambda: state.is_METROPOLIS()
        self.post_serenity_hardfork = lambda: state.is_SERENITY()
        self.snapshot = state.snapshot
        self.revert = state.revert
        self.transfer_value = lambda x, y, z: True
        self.reset_storage = lambda addr: None
        self.tx_origin = '\x00' * 20
        self.tx_gasprice = 0

    # def msg(self, msg):
    #     print repr(msg.to), repr(msg.code_address), specials.keys(), msg.code_address in specials
    #     o = _apply_msg(self, msg, '') if msg.code_address in specials else (0, 0, '')
    #     print o
    #     return o


class Receipt(rlp.Serializable):

    fields = [
        ('state_root', trie_root),
        ('gas_used', big_endian_int),
        ('bloom', int256),
        ('logs', CountableList(Log))
    ]

    def __init__(self, state_root, gas_used, logs, bloom=None):
        # does not call super.__init__ as bloom should not be an attribute but a property
        self.state_root = state_root
        self.gas_used = gas_used
        self.logs = logs
        if bloom is not None and bloom != self.bloom:
            raise ValueError("Invalid bloom filter")
        self._cached_rlp = None
        self._mutable = True

    @property
    def bloom(self):
        bloomables = [x.bloomables() for x in self.logs]
        return bloom.bloom_from_list(utils.flatten(bloomables))
