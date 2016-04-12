import sys
import rlp
from rlp.sedes import CountableList, binary
from rlp.utils import decode_hex, encode_hex, ascii_chr
from ethereum import opcodes
from ethereum import utils
from ethereum import specials
from ethereum import bloom
from ethereum import vm as vm
from ethereum.exceptions import InvalidNonce, InsufficientStartGas, UnsignedTransaction, \
        BlockGasLimitReached, InsufficientBalance
from ethereum.utils import safe_ord, mk_contract_address
from ethereum import transactions
import ethereum.config as config

sys.setrecursionlimit(100000)

from ethereum.slogging import get_logger
log_tx = get_logger('eth.pb.tx')
log_msg = get_logger('eth.pb.msg')
log_state = get_logger('eth.pb.msg.state')

TT255 = 2 ** 255
TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1

OUT_OF_GAS = -1

# contract creating transactions send to an empty address
CREATE_CONTRACT_ADDRESS = b''


def verify(block, parent):
    from ethereum import blocks
    try:
        block2 = rlp.decode(rlp.encode(block), blocks.Block,
                            env=parent.env, parent=parent)
        assert block == block2
        return True
    except blocks.VerificationFailed:
        return False


class Log(rlp.Serializable):

    # TODO: original version used zpad (here replaced by int32.serialize); had
    # comment "why zpad"?
    fields = [
        ('address', utils.address),
        ('topics', CountableList(utils.int32)),
        ('data', binary)
    ]

    def __init__(self, address, topics, data):
        if len(address) == 40:
            address = decode_hex(address)
        assert len(address) == 20
        super(Log, self).__init__(address, topics, data)

    def bloomables(self):
        return [self.address] + [utils.int32.serialize(x) for x in self.topics]

    def to_dict(self):
        return {
            "bloom": encode_hex(bloom.b64(bloom.bloom_from_list(self.bloomables()))),
            "address": encode_hex(self.address),
            "data": b'0x' + encode_hex(self.data),
            "topics": [encode_hex(utils.int32.serialize(t))
                       for t in self.topics]
        }

    def __repr__(self):
        return '<Log(address=%r, topics=%r, data=%r)>' %  \
            (encode_hex(self.address), self.topics, self.data)


def validate_transaction(block, tx):

    def rp(what, actual, target):
        return '%r: %r actual:%r target:%r' % (tx, what, actual, target)

    # (1) The transaction signature is valid;
    if not tx.sender:  # sender is set and validated on Transaction initialization
        raise UnsignedTransaction(tx)
    if block.number >= config.default_config["HOMESTEAD_FORK_BLKNUM"]:
            tx.check_low_s()

    # (2) the transaction nonce is valid (equivalent to the
    #     sender account's current nonce);
    acctnonce = block.get_nonce(tx.sender)
    if acctnonce != tx.nonce:
        raise InvalidNonce(rp('nonce', tx.nonce, acctnonce))

    # (3) the gas limit is no smaller than the intrinsic gas,
    # g0, used by the transaction;
    if tx.startgas < tx.intrinsic_gas_used:
        raise InsufficientStartGas(rp('startgas', tx.startgas, tx.intrinsic_gas_used))

    # (4) the sender account balance contains at least the
    # cost, v0, required in up-front payment.
    total_cost = tx.value + tx.gasprice * tx.startgas
    if block.get_balance(tx.sender) < total_cost:
        raise InsufficientBalance(rp('balance', block.get_balance(tx.sender), total_cost))

    # check block gas limit
    if block.gas_used + tx.startgas > block.gas_limit:
        raise BlockGasLimitReached(rp('gaslimit', block.gas_used + tx.startgas, block.gas_limit))

    return True


class lazy_safe_encode(object):
    """Creates a lazy and logging safe representation of transaction data.
    Use this in logging of transactions; instead of

        >>> log.debug(data=data)

    do this:

        >>> log.debug(data=lazy_safe_encode(data))
    """

    def __init__(self, data):
        self.data = data

    def __str__(self):
        if not isinstance(self.data, (str, unicode)):
            return repr(self.data)
        else:
            return encode_hex(self.data)

    def __repr__(self):
        return str(self)


def apply_transaction(block, tx):
    validate_transaction(block, tx)

    # print block.get_nonce(tx.sender), '@@@'

    def rp(what, actual, target):
        return '%r: %r actual:%r target:%r' % (tx, what, actual, target)

    intrinsic_gas = tx.intrinsic_gas_used
    if block.number >= block.config['HOMESTEAD_FORK_BLKNUM']:
        assert tx.s * 2 < transactions.secpk1n
        if not tx.to or tx.to == CREATE_CONTRACT_ADDRESS:
            intrinsic_gas += opcodes.CREATE[3]
            if tx.startgas < intrinsic_gas:
                raise InsufficientStartGas(rp('startgas', tx.startgas, intrinsic_gas))

    log_tx.debug('TX NEW', tx_dict=tx.log_dict())
    # start transacting #################
    block.increment_nonce(tx.sender)

    # buy startgas
    assert block.get_balance(tx.sender) >= tx.startgas * tx.gasprice
    block.delta_balance(tx.sender, -tx.startgas * tx.gasprice)
    message_gas = tx.startgas - intrinsic_gas
    message_data = vm.CallData([safe_ord(x) for x in tx.data], 0, len(tx.data))
    message = vm.Message(tx.sender, tx.to, tx.value, message_gas, message_data, code_address=tx.to)

    # MESSAGE
    ext = VMExt(block, tx)
    if tx.to and tx.to != CREATE_CONTRACT_ADDRESS:
        result, gas_remained, data = apply_msg(ext, message)
        log_tx.debug('_res_', result=result, gas_remained=gas_remained, data=lazy_safe_encode(data))
    else:  # CREATE
        result, gas_remained, data = create_contract(ext, message)
        assert utils.is_numeric(gas_remained)
        log_tx.debug('_create_', result=result, gas_remained=gas_remained, data=lazy_safe_encode(data))

    assert gas_remained >= 0

    log_tx.debug("TX APPLIED", result=result, gas_remained=gas_remained,
                 data=lazy_safe_encode(data))

    if not result:  # 0 = OOG failure in both cases
        log_tx.debug('TX FAILED', reason='out of gas',
                     startgas=tx.startgas, gas_remained=gas_remained)
        block.gas_used += tx.startgas
        block.delta_balance(block.coinbase, tx.gasprice * tx.startgas)
        output = b''
        success = 0
    else:
        log_tx.debug('TX SUCCESS', data=lazy_safe_encode(data))
        gas_used = tx.startgas - gas_remained
        block.refunds += len(set(block.suicides)) * opcodes.GSUICIDEREFUND
        if block.refunds > 0:
            log_tx.debug('Refunding', gas_refunded=min(block.refunds, gas_used // 2))
            gas_remained += min(block.refunds, gas_used // 2)
            gas_used -= min(block.refunds, gas_used // 2)
            block.refunds = 0
        # sell remaining gas
        block.delta_balance(tx.sender, tx.gasprice * gas_remained)
        block.delta_balance(block.coinbase, tx.gasprice * gas_used)
        block.gas_used += gas_used
        if tx.to:
            output = b''.join(map(ascii_chr, data))
        else:
            output = data
        success = 1
    block.commit_state()
    suicides = block.suicides
    block.suicides = []
    for s in suicides:
        block.ether_delta -= block.get_balance(s)
        block.set_balance(s, 0)
        block.del_account(s)
    block.add_transaction_to_list(tx)
    block.logs = []
    return success, output


# External calls that can be made from inside the VM. To use the EVM with a
# different blockchain system, database, set parameters for testing, just
# swap out the functions here
class VMExt():

    def __init__(self, block, tx):
        self._block = block
        self.get_code = block.get_code
        self.get_balance = block.get_balance
        self.set_balance = block.set_balance
        self.set_storage_data = block.set_storage_data
        self.get_storage_data = block.get_storage_data
        self.log_storage = lambda x: block.account_to_dict(x)['storage']
        self.add_suicide = lambda x: block.suicides.append(x)
        self.add_refund = lambda x: \
            setattr(block, 'refunds', block.refunds + x)
        self.block_hash = lambda x: block.get_ancestor_hash(block.number - x) \
            if (1 <= block.number - x <= 256 and x <= block.number) else b''
        self.block_coinbase = block.coinbase
        self.block_timestamp = block.timestamp
        self.block_number = block.number
        self.block_difficulty = block.difficulty
        self.block_gas_limit = block.gas_limit
        self.log = lambda addr, topics, data: \
            block.add_log(Log(addr, topics, data))
        self.tx_origin = tx.sender
        self.tx_gasprice = tx.gasprice
        self.create = lambda msg: create_contract(self, msg)
        self.msg = lambda msg: _apply_msg(self, msg, self.get_code(msg.code_address))
        self.account_exists = block.account_exists
        self.post_homestead_hardfork = lambda: block.number >= block.config['HOMESTEAD_FORK_BLKNUM']


def apply_msg(ext, msg):
    return _apply_msg(ext, msg, ext.get_code(msg.code_address))


def _apply_msg(ext, msg, code):
    trace_msg = log_msg.is_active('trace')
    if trace_msg:
        log_msg.debug("MSG APPLY", sender=encode_hex(msg.sender), to=encode_hex(msg.to),
                      gas=msg.gas, value=msg.value,
                      data=encode_hex(msg.data.extract_all()))
        if log_state.is_active('trace'):
            log_state.trace('MSG PRE STATE SENDER', account=msg.sender.encode('hex'),
                            bal=ext.get_balance(msg.sender),
                            state=ext.log_storage(msg.sender))
            log_state.trace('MSG PRE STATE RECIPIENT', account=msg.to.encode('hex'),
                            bal=ext.get_balance(msg.to),
                            state=ext.log_storage(msg.to))
        # log_state.trace('CODE', code=code)
    # Transfer value, instaquit if not enough
    snapshot = ext._block.snapshot()
    if msg.transfers_value:
        if not ext._block.transfer_value(msg.sender, msg.to, msg.value):
            log_msg.debug('MSG TRANSFER FAILED', have=ext.get_balance(msg.to),
                          want=msg.value)
            return 1, msg.gas, []
    # Main loop
    if msg.code_address in specials.specials:
        res, gas, dat = specials.specials[msg.code_address](ext, msg)
    else:
        res, gas, dat = vm.vm_execute(ext, msg, code)
    # gas = int(gas)
    # assert utils.is_numeric(gas)
    if trace_msg:
        log_msg.debug('MSG APPLIED', gas_remained=gas,
                      sender=encode_hex(msg.sender), to=encode_hex(msg.to), data=dat)
        if log_state.is_active('trace'):
            log_state.trace('MSG POST STATE SENDER', account=msg.sender.encode('hex'),
                            bal=ext.get_balance(msg.sender),
                            state=ext.log_storage(msg.sender))
            log_state.trace('MSG POST STATE RECIPIENT', account=msg.to.encode('hex'),
                            bal=ext.get_balance(msg.to),
                            state=ext.log_storage(msg.to))

    if res == 0:
        log_msg.debug('REVERTING')
        ext._block.revert(snapshot)

    return res, gas, dat


def create_contract(ext, msg):
    log_msg.debug('CONTRACT CREATION')
    #print('CREATING WITH GAS', msg.gas)
    sender = decode_hex(msg.sender) if len(msg.sender) == 40 else msg.sender
    if ext.tx_origin != msg.sender:
        ext._block.increment_nonce(msg.sender)
    nonce = utils.encode_int(ext._block.get_nonce(msg.sender) - 1)
    msg.to = mk_contract_address(sender, nonce)
    b = ext.get_balance(msg.to)
    if b > 0:
        ext.set_balance(msg.to, b)
        ext._block.set_nonce(msg.to, 0)
        ext._block.set_code(msg.to, b'')
        ext._block.reset_storage(msg.to)
    msg.is_create = True
    # assert not ext.get_code(msg.to)
    code = msg.data.extract_all()
    msg.data = vm.CallData([], 0, 0)
    snapshot = ext._block.snapshot()
    res, gas, dat = _apply_msg(ext, msg, code)
    assert utils.is_numeric(gas)

    if res:
        if not len(dat):
            return 1, gas, msg.to
        gcost = len(dat) * opcodes.GCONTRACTBYTE
        if gas >= gcost:
            gas -= gcost
        else:
            dat = []
            log_msg.debug('CONTRACT CREATION OOG', have=gas, want=gcost, block_number=ext._block.number)
            if ext._block.number >= ext._block.config['HOMESTEAD_FORK_BLKNUM']:
                ext._block.revert(snapshot)
                return 0, 0, b''
        ext._block.set_code(msg.to, b''.join(map(ascii_chr, dat)))
        return 1, gas, msg.to
    else:
        return 0, gas, b''
