import copy
import json
import sys
import time
import rlp
from rlp.sedes import CountableList, binary
from rlp.utils import decode_hex, encode_hex, ascii_chr, bytes_to_str, str_to_bytes
from pyethereum import opcodes
from pyethereum import utils
from pyethereum import transactions
from pyethereum import trie
from pyethereum import fastvm
from pyethereum import specials
from pyethereum import bloom
from pyethereum import vm
from pyethereum.exceptions import *
from pyethereum.utils import safe_ord

sys.setrecursionlimit(100000)

from pyethereum.slogging import get_logger
log_tx = get_logger('eth.tx')
log_msg = get_logger('eth.msg')
log_state = get_logger('eth.msg.state')

TT255 = 2 ** 255
TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1

OUT_OF_GAS = -1

# contract creating transactions send to an empty address
CREATE_CONTRACT_ADDRESS = b''


def verify(block, parent):
    from pyethereum import blocks
    try:
        block2 = rlp.decode(rlp.encode(block), blocks.Block,
                            db=parent.db, parent=parent)
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


def apply_transaction(block, tx):

    def rp(actual, target):
        return '%r, actual:%r target:%r' % (tx, actual, target)

    # (1) The transaction signature is valid;
    if not tx.sender:
        raise UnsignedTransaction(tx)

    # (2) the transaction nonce is valid (equivalent to the
    #     sender account's current nonce);
    acctnonce = block.get_nonce(tx.sender)
    if acctnonce != tx.nonce:
        raise InvalidNonce(rp(tx.nonce, acctnonce))

    # (3) the gas limit is no smaller than the intrinsic gas,
    # g0, used by the transaction;
    num_zero_bytes = str_to_bytes(tx.data).count(ascii_chr(0))
    num_non_zero_bytes = len(tx.data) - num_zero_bytes
    intrinsic_gas_used = (opcodes.GTXCOST
                          + opcodes.GTXDATAZERO * num_zero_bytes
                          + opcodes.GTXDATANONZERO * num_non_zero_bytes)
    if tx.startgas < intrinsic_gas_used:
        raise InsufficientStartGas(rp(tx.startgas, intrinsic_gas_used))

    # (4) the sender account balance contains at least the
    # cost, v0, required in up-front payment.
    total_cost = tx.value + tx.gasprice * tx.startgas
    if block.get_balance(tx.sender) < total_cost:
        raise InsufficientBalance(
            rp(block.get_balance(tx.sender), total_cost))

    # check block gas limit
    if block.gas_used + tx.startgas > block.gas_limit:
        raise BlockGasLimitReached(rp(block.gas_used + tx.startgas, block.gas_limit))

    log_tx.debug('TX NEW', tx=encode_hex(tx.hash), tx_dict=tx.to_dict())
    # start transacting #################
    block.increment_nonce(tx.sender)
    # print block.get_nonce(tx.sender), '@@@'

    # buy startgas
    assert block.get_balance(tx.sender) >= tx.startgas * tx.gasprice
    block.delta_balance(tx.sender, -tx.startgas * tx.gasprice)

    message_gas = tx.startgas - intrinsic_gas_used
    message_data = vm.CallData([safe_ord(x) for x in tx.data], 0, len(tx.data))
    message = vm.Message(tx.sender, tx.to, tx.value, message_gas, message_data,
                         code_address=tx.to)

    # MESSAGE
    ext = VMExt(block, tx)
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
        block.gas_used += tx.startgas
        block.delta_balance(block.coinbase, tx.gasprice * tx.startgas)
        output = b''
        success = 0
    else:
        log_tx.debug('TX SUCCESS', data=data)
        gas_used = tx.startgas - gas_remained
        block.refunds += len(block.suicides) * opcodes.GSUICIDEREFUND
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
        self.block_hash = lambda x: block.get_ancestor(block.number - x).hash \
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
        self.msg = lambda msg: apply_msg(self, msg)
        self.account_exists = block.account_exists


def apply_msg(ext, msg):
    return _apply_msg(ext, msg, ext.get_code(msg.code_address))


def _apply_msg(ext, msg, code):
    if log_msg.is_active:
        log_msg.debug("MSG APPLY", sender=encode_hex(msg.sender), to=encode_hex(msg.to),
                      gas=msg.gas, value=msg.value,
                      data=encode_hex(msg.data.extract_all()))
    if log_state.is_active:
        log_state.trace('MSG PRE STATE', account=msg.to, state=ext.log_storage(msg.to))
    # Transfer value, instaquit if not enough
    snapshot = ext._block.snapshot()
    o = ext._block.transfer_value(msg.sender, msg.to, msg.value)
    if not o:
        log_msg.debug('MSG TRANSFER FAILED', have=ext.get_balance(msg.to),
                      want=msg.value)
        return 1, msg.gas, []
    # Main loop
    if msg.code_address in specials.specials:
        res, gas, dat = specials.specials[msg.code_address](ext, msg)
    else:
        res, gas, dat = vm.vm_execute(ext, msg, code)
    gas = int(gas)
    assert utils.is_numeric(gas)
    if log_msg.is_active:
        log_msg.debug('MSG APPLIED', result=o, gas_remained=gas, sender=msg.sender, to=msg.to, data=dat)
    if log_state.is_active:
        log_state.trace('MSG POST STATE', account=msg.to, state=ext.log_storage(msg.to))

    if res == 0:
        log_msg.debug('REVERTING')
        ext._block.revert(snapshot)

    return res, gas, dat


def create_contract(ext, msg):
    print('CREATING WITH GAS', msg.gas)
    sender = decode_hex(msg.sender) if len(msg.sender) == 40 else msg.sender
    if ext.tx_origin != msg.sender:
        ext._block.increment_nonce(msg.sender)
    nonce = utils.encode_int(ext._block.get_nonce(msg.sender) - 1)
    msg.to = utils.sha3(rlp.encode([sender, nonce]))[12:]
    b = ext.get_balance(msg.to)
    if b > 0:
        ext.set_balance(msg.to, b)
        ext._block.set_nonce(msg.to, 0)
        ext._block.set_code(msg.to, b'')
        ext._block.reset_storage(msg.to)
    msg.is_create = True
    # assert not ext.get_code(msg.to)
    res, gas, dat = _apply_msg(ext, msg, msg.data.extract_all())
    assert utils.is_numeric(gas)

    if res:
        if not len(dat):
            return 1, gas, msg.to
        gcost = len(dat) * opcodes.GCONTRACTBYTE
        if gas >= gcost:
            gas -= gcost
        else:
            dat = []
            print('CONTRACT CREATION OOG', 'have', gas, 'want', gcost)
            log_msg.debug('CONTRACT CREATION OOG', have=gas, want=gcost)
        ext._block.set_code(msg.to, b''.join(map(ascii_chr, dat)))
        return 1, gas, msg.to
    else:
        return 0, gas, b''
