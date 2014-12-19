import rlp
import opcodes
import utils
import time
import blocks
import transactions
import trie
import sys
import json
import fastvm
import copy
import specials
import bloom
import vm
from exceptions import *

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
CREATE_CONTRACT_ADDRESS = ''


def verify(block, parent):
    try:
        parent.deserialize_child(block.serialize())
        return True
    except blocks.VerificationFailed:
        return False


class Log(object):

    def __init__(self, address, topics, data):
        self.address = address
        self.topics = topics
        self.data = data

    def serialize(self):
        return [
            self.address.decode('hex'),
            [utils.zpad(utils.encode_int(x), 32) for x in self.topics],  # why zpad?
            self.data
        ]

    def bloomables(self):
        return [self.address.decode('hex')] + \
            [utils.zpad(utils.encode_int(x), 32) for x in self.topics]  # why zpad?

    def __repr__(self):
        return '<Log(address=%r, topics=%r, data=%r)>' % \
            (self.address, self.topics, self.data)

    def to_dict(self):
        return dict(address=self.address,
                    topics=[utils.zpad(utils.int_to_big_endian(x), 32).encode('hex')
                            for x in self.topics],
                    data='0x' + self.data.encode('hex'))


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
    num_zero_bytes = tx.data.count(chr(0))
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

    log_tx.debug('TX NEW', tx=tx.hex_hash(), tx_dict=tx.to_dict())
    # start transacting #################
    block.increment_nonce(tx.sender)
    # print block.get_nonce(tx.sender), '@@@'

    # buy startgas
    success = block.transfer_value(tx.sender, block.coinbase,
                                   tx.gasprice * tx.startgas)
    assert success

    message_gas = tx.startgas - intrinsic_gas_used
    message = vm.Message(tx.sender, tx.to, tx.value, message_gas, tx.data)

    # MESSAGE
    ext = VMExt(block, tx)
    if tx.to and tx.to != CREATE_CONTRACT_ADDRESS:
        result, gas_remained, data = apply_msg_send(ext, message)
    else:  # CREATE
        result, gas_remained, data = create_contract(ext, message)

    assert gas_remained >= 0

    log_tx.debug("TX APPLIED", result=result, gas_remained=gas_remained,
                 data=data)

    if not result:  # 0 = OOG failure in both cases
        log_tx.debug('TX FAILED', reason='out of gas',
                     startgas=tx.startgas, gas_remained=gas_remained)
        block.gas_used += tx.startgas
        output = ''
        success = 0
    else:
        log_tx.debug('TX SUCCESS')
        gas_used = tx.startgas - gas_remained
        if block.refunds > 0:
            log_tx.debug('Refunding', gas_refunded=min(block.refunds, gas_used // 2))
            gas_remained += min(block.refunds, gas_used // 2)
            gas_used -= min(block.refunds, gas_used // 2)
        # sell remaining gas
        block.transfer_value(
            block.coinbase, tx.sender, tx.gasprice * gas_remained)
        block.gas_used += gas_used
        if tx.to:
            output = ''.join(map(chr, data))
        else:
            output = data
        success = 1
    block.commit_state()
    suicides = block.suicides
    block.suicides = []
    for s in suicides:
        block.del_account(s)
    block.add_transaction_to_list(tx)
    return success, output


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
        self.block_prevhash = block.prevhash
        self.block_coinbase = block.coinbase
        self.block_timestamp = block.timestamp
        self.block_number = block.number
        self.block_difficulty = block.difficulty
        self.block_gas_limit = block.gas_limit
        self.log = lambda addr, topics, data: \
            tx.logs.append(Log(addr, topics, data))
        self.tx_origin = tx.sender
        self.tx_gasprice = tx.gasprice
        self.create = lambda msg: create_contract(self, msg)
        self.call = lambda msg: apply_msg_send(self, msg)
        self.sendmsg = lambda msg, code: apply_msg(self, msg, code)


def apply_msg(ext, msg, code):
    # print 'init', map(ord, msg.data), msg.gas, \
    #     msg.sender, block.get_nonce(msg.sender)

    log_msg.debug("MSG APPLY", sender=msg.sender, to=msg.to,
            gas=msg.gas, value=msg.value, data=msg.data.encode('hex'))
    if log_state.is_active:
        log_state.trace('MSG PRE STATE', account=msg.to, state=ext.log_storage(msg.to))
    # Transfer value, instaquit if not enough
    o = ext._block.transfer_value(msg.sender, msg.to, msg.value)
    if not o:
        log_msg.debug('MSG TRANSFER FAILED', have=ext.get_balance(msg.to),
                      want=msg.value)
        return 1, msg.gas, []
    if msg.depth >= 1024:
        return 0, 0, []
    snapshot = ext._block.snapshot()

    # Main loop
    res, gas, dat = vm.vm_execute(ext, msg, code)
    log_msg.debug('MSG APPLIED', result=o, gas_remained=gas, sender=msg.sender, to=msg.to, data=dat)
    if log_state.is_active:
        log_state.trace('MSG POST STATE', account=msg.to, state=ext.log_storage(msg.to))

    if res == 0:
        log_msg.debug('REVERTING')
        ext._block.revert(snapshot)

    return res, gas, dat


def apply_msg_send(ext, msg):
    # special pseudo-contracts for ecrecover, sha256, ripemd160
    if msg.to in specials.specials:
        o = ext._block.transfer_value(msg.sender, msg.to, msg.value)
        if not o:
            return 1, msg.gas, []
        return specials.specials[msg.to](ext, msg)
    else:
        return apply_msg(ext, msg, ext.get_code(msg.to))


def create_contract(ext, msg):
    sender = msg.sender.decode('hex') if len(msg.sender) == 40 else msg.sender
    if ext.tx_origin != msg.sender:
        ext._block.increment_nonce(msg.sender)
    nonce = utils.encode_int(ext._block.get_nonce(msg.sender) - 1)
    msg.to = utils.sha3(rlp.encode([sender, nonce]))[12:].encode('hex')
    assert not ext.get_code(msg.to)
    res, gas, dat = apply_msg(ext, msg, msg.data)
    if res:
        if not len(dat):
            return 1, gas, ''
        gcost = len(dat) * opcodes.GCONTRACTBYTE
        if gas >= gcost:
            gas -= gcost
        else:
            dat = []
            log_msg.debug('CONTRACT CREATION OOG', have=gas, want=gcost)
        ext._block.set_code(msg.to, ''.join(map(chr, dat)))
        return 1, gas, msg.to
    else:
        return 0, gas, ''
