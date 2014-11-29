import rlp
from opcodes import opcodes

import utils
import time
import blocks
import transactions
import trie
import sys
import logging
import json
import fastvm
import copy
import specials
logger = logging.getLogger(__name__)
sys.setrecursionlimit(100000)


class PBLogger(object):
    log_apply_op = False    # general flag for logging inside apply_op
    log_op = False          # log op, gas, stack before each op
    log_pre_state = False   # dump storage at account before execution
    log_post_state = False  # dump storage at account after execution
    log_block = False       # dump block after TX was applied
    log_memory = False      # dump memory before each op
    log_stack = False       # dump stack before each op
    log_storage = False     # dump storage before each op
    log_json = False        # generate machine readable output
    log_state_delta = False  # dump state delta post tx execution

    def __init__(self):
        self.listeners = []  # register callbacks here

    def log(self, name, **kargs):
        # call callbacks
        for l in self.listeners:
            l({name: kargs})
        if self.log_json:
            logger.debug(json.dumps({name: kargs}))
        else:
            order = dict(pc=-2, op=-1, stackargs=1, data=2, code=3)
            items = sorted(kargs.items(), key=lambda x: order.get(x[0], 0))
            msg = ", ".join("%s=%s" % (k, v) for k, v in items)
            logger.debug("%s: %s", name.ljust(15), msg)

    def multilog(self, data):
        for l in self.listeners:
            l(data)
        if self.log_json:
            logger.debug(json.dumps(data))
        else:
            for key, datum in data.iteritems():
                if isinstance(datum, dict):
                    order = dict(pc=-2, op=-1, stackargs=1, data=2, code=3)
                    items = sorted(datum.items(), key=lambda x: order.get(x[0], 0))
                    msg = ", ".join("%s=%s" % (k, v) for k, v in items)
                elif isinstance(datum, list):
                    msg = ", ".join(map(str, datum))
                else:
                    msg = str(datum)
                logger.debug("%s: %s", key.ljust(15), msg)
            logger.debug("")


pblogger = PBLogger()

code_cache = {}


GDEFAULT = 1
GMEMORY = 1
GSTORAGEKILL = -100
GSTORAGEMOD = 100
GSTORAGEADD = 300
GTXDATA = 5
GTXCOST = 500
TT255 = 2**255
TT256 = 2**256
TT256M1 = 2**256 - 1

OUT_OF_GAS = -1

# contract creating transactions send to an empty address
CREATE_CONTRACT_ADDRESS = ''


class VerificationFailed(Exception):
    pass


def must_equal(what, a, b):
    if a != b:
        raise VerificationFailed(what, a, '==', b)


def must_ge(what, a, b):
    if not (a >= b):
        raise VerificationFailed(what, a, '>=', b)


def must_le(what, a, b):
    if not (a <= b):
        raise VerificationFailed(what, a, '<=', b)


def verify(block, parent):
    try:
        parent.deserialize_child(block.serialize())
        return True
    except:
        return False


class Message(object):

    def __init__(self, sender, to, value, gas, data, depth=0):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data
        self.depth = depth

    def __repr__(self):
        return '<Message(to:%s...)>' % self.to[:8]


class Log(object):

    def __init__(self, address, topics, data):
        self.address = address
        self.topics = topics
        self.data = data

    def serialize(self):
        return [
            self.address.decode('hex'),
            [utils.encode_int(x) for x in self.topics],
            self.data
        ]

    def bloomables(self):
        return [self.address.decode('hex')] + \
            [utils.encode_int(x) for x in self.topics]


class InvalidTransaction(Exception):
    pass

class UnsignedTransaction(InvalidTransaction):
    pass

class InvalidNonce(InvalidTransaction):
    pass

class InsufficientBalance(InvalidTransaction):
    pass

class InsufficientStartGas(InvalidTransaction):
    pass

class BlockGasLimitReached(InvalidTransaction):
    pass

class GasPriceTooLow(InvalidTransaction):
    pass


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
    intrinsic_gas_used = GTXDATA * len(tx.data) + GTXCOST
    if tx.startgas < intrinsic_gas_used:
        raise InsufficientStartGas(rp(tx.startgas, intrinsic_gas_used))

    # (4) the sender account balance contains at least the
    # cost, v0, required in up-front payment.
    total_cost = tx.value + tx.gasprice * tx.startgas
    if block.get_balance(tx.sender) < total_cost:
        raise InsufficientBalance(
            rp(block.get_balance(tx.sender), total_cost))

    # check offered gas price is enough
    # if tx.gasprice < block.min_gas_price:
        # raise GasPriceTooLow(rp(tx.gasprice, block.min_gas_price))

    # check block gas limit
    if block.gas_used + tx.startgas > block.gas_limit:
        raise BlockGasLimitReached(rp(block.gas_used + tx.startgas, block.gas_limit))

    pblogger.log('TX NEW', tx=tx.hex_hash(), tx_dict=tx.to_dict())
    # start transacting #################
    block.increment_nonce(tx.sender)
    print block.get_nonce(tx.sender), '@@@'

    # buy startgas
    success = block.transfer_value(tx.sender, block.coinbase,
                                   tx.gasprice * tx.startgas)
    assert success

    message_gas = tx.startgas - intrinsic_gas_used
    message = Message(tx.sender, tx.to, tx.value, message_gas, tx.data)

    # MESSAGE
    if tx.to and tx.to != CREATE_CONTRACT_ADDRESS:
        result, gas_remained, data = apply_msg_send(block, tx, message)
    else:  # CREATE
        result, gas_remained, data = create_contract(block, tx, message)
        if result > 0:
            result = utils.coerce_addr_to_hex(result)

    assert gas_remained >= 0

    pblogger.log("TX APPLIED", result=result, gas_remained=gas_remained,
                 data=''.join(map(chr, data)).encode('hex'))
    if pblogger.log_block:
        pblogger.log('BLOCK', block=block.to_dict(with_state=True, full_transactions=True))

    if not result:  # 0 = OOG failure in both cases
        pblogger.log('TX FAILED', reason='out of gas', startgas=tx.startgas, gas_remained=gas_remained)
        block.gas_used += tx.startgas
        output = OUT_OF_GAS
    else:
        pblogger.log('TX SUCCESS')
        gas_used = tx.startgas - gas_remained
        if block.refunds > 0:
            print 'Refunding: %r gas' % min(block.refunds, gas_used // 2)
            gas_used -= min(block.refunds, gas_used // 2)
        # sell remaining gas
        block.transfer_value(
            block.coinbase, tx.sender, tx.gasprice * gas_remained)
        block.gas_used += gas_used
        if tx.to:
            output = ''.join(map(chr, data))
        else:
            output = result
    block.commit_state()
    suicides = block.suicides
    block.suicides = []
    for s in suicides:
        block.del_account(s)
    block.add_transaction_to_list(tx)
    success = output is not OUT_OF_GAS
    return success, output if success else ''


class Compustate():

    def __init__(self, **kwargs):
        self.memory = []
        self.stack = []
        self.pc = 0
        self.gas = 0
        for kw in kwargs:
            setattr(self, kw, kwargs[kw])


# Preprocesses code, and determines which locations are in the middle
# of pushdata and thus invalid
def preprocess_code(code):
    i = 0
    ops = []
    last_push = False
    while i < len(code):
        o = copy.copy(opcodes.get(ord(code[i]), ['INVALID', 0, 0, 0]) +
                      [ord(code[i]), 0])
        if last_push:
            last_push = False
            if o[0] == 'JUMP' or o[0] == 'JUMPI':
                o[0] += 'STATIC'
        ops.append(o)
        if o[0][:4] == 'PUSH':
            last_push = True
            for j in range(int(o[0][4:])):
                i += 1
                byte = ord(code[i]) if i < len(code) else 0
                o[-1] = (o[-1] << 8) + byte
                if i < len(code):
                    ops.append(['INVALID', 0, 0, 0, byte, 0])
        i += 1
    return ops


def apply_msg(block, tx, msg, code):
    #print 'init', map(ord, msg.data), msg.gas, msg.sender, block.get_nonce(msg.sender)
    pblogger.log("MSG APPLY", tx=tx.hex_hash(), sender=msg.sender, to=msg.to,
                 gas=msg.gas, value=msg.value, data=msg.data.encode('hex'))
    if pblogger.log_pre_state:
        pblogger.log('MSG PRE STATE', account=msg.to, state=block.account_to_dict(msg.to))
    # Transfer value, instaquit if not enough
    o = block.transfer_value(msg.sender, msg.to, msg.value)
    if not o:
        return 1, msg.gas, []
    snapshot = block.snapshot()
    compustate = Compustate(gas=msg.gas)
    if msg.depth >= 1024:
        return 0, 0, []
    t, ops = time.time(), 0
    if code in code_cache:
        processed_code = code_cache[code]
    else:
        processed_code = preprocess_code(code)
        code_cache[code] = processed_code
    #if block.get_code(msg.to) == '' and msg.to != CREATE_CONTRACT_ADDRESS and msg.value > 0:
    #    topics = [utils.coerce_to_int(msg.sender) + 1]
    #    data = ''  # utils.zpad(utils.encode_int(msg.value), 32)
    #    block.logs.append(Log(msg.to, topics, data))
    #    pblogger.log('LOG', to=msg.to, topics=topics, data=data)
    #    return 1, compustate.gas, []

    # Main loop
    while 1:
        o = apply_op(block, tx, msg, processed_code, compustate)
        ops += 1
        if o is not None:
            # print 'dropping', o
            pblogger.log('MSG APPLIED', result=o, gas_remained=compustate.gas,
                         sender=msg.sender, to=msg.to, ops=ops,
                         time_per_op=(time.time() - t) / ops)
            if pblogger.log_post_state:
                    pblogger.log('MSG POST STATE', account=msg.to,
                                 state=block.account_to_dict(msg.to))

            if o == OUT_OF_GAS:
                block.revert(snapshot)
                return 0, 0, []
            else:
                return 1, compustate.gas, o


def apply_msg_send(block, tx, msg):
    # special pseudo-contracts for ecrecover, sha256, ripemd160
    if msg.to in specials.specials:
        o = block.transfer_value(msg.sender, msg.to, msg.value)
        if not o:
            return 1, msg.gas, []
        return specials.specials[msg.to](block, tx, msg)
    else:
        return apply_msg(block, tx, msg, block.get_code(msg.to))


def create_contract(block, tx, msg):
    sender = msg.sender.decode('hex') if len(msg.sender) == 40 else msg.sender
    if tx.sender != msg.sender:
        block.increment_nonce(msg.sender)
    nonce = utils.encode_int(block.get_nonce(msg.sender) - 1)
    msg.to = utils.sha3(rlp.encode([sender, nonce]))[12:].encode('hex')
    assert not block.get_code(msg.to)
    res, gas, dat = apply_msg(block, tx, msg, msg.data)
    if res:
        block.set_code(msg.to, ''.join(map(chr, dat)))
        return utils.coerce_to_int(msg.to), gas, dat
    else:
        block.del_account(msg.to)
        return res, gas, dat


def get_opcode(code, index):
    return ord(code[index]) if index < len(code) else 0


def get_op_data(code, index):
    opcode = ord(code[index]) if index < len(code) else 0
    return opcodes.get(opcode, ['INVALID', 0, 0, 0])


def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)


def vm_exception(error, **kargs):
    pblogger.log('EXCEPTION', cause=error, **kargs)
    return OUT_OF_GAS


def mem_extend(mem, compustate, op, start, sz):
    if sz:
        newsize = start + sz
        if len(mem) < ceil32(newsize):
            m_extend = ceil32(newsize) - len(mem)
            memfee = GMEMORY * (m_extend / 32)
            if compustate.gas < memfee:
                compustate.gas = 0
                return False
            compustate.gas -= memfee
            mem.extend([0] * m_extend)
    return True


def to_signed(i):
    return i if i < TT255 else i - TT256


# Does not include paying opfee
def apply_op(block, tx, msg, processed_code, compustate):

    if compustate.pc >= len(processed_code):
        return []

    op, in_args, out_args, fee, opcode, pushval = processed_code[compustate.pc]

    # print 'op', opcode, compustate.stack, compustate.gas

    # out of gas error
    if fee > compustate.gas:
        return vm_exception('OUT OF GAS')

    # empty stack error
    if in_args > len(compustate.stack):
        return vm_exception('INSUFFICIENT STACK', op=op, needed=str(in_args),
                            available=str(len(compustate.stack)))


    # Apply operation
    compustate.gas -= fee
    compustate.pc += 1
    stk = compustate.stack
    mem = compustate.memory

    if pblogger.log_apply_op:
        trace_data = {}
        if pblogger.log_stack:
            trace_data['stack'] = map(str, list(compustate.stack))
        if pblogger.log_memory:
            trace_data['memory'] = ''.join([chr(x).encode('hex') for x in compustate.memory])
        if pblogger.log_storage:
            trace_data['storage'] = block.account_to_dict(msg.to)['storage']
        if pblogger.log_op:
            trace_data['gas'] = str(compustate.gas + fee)
            trace_data['pc'] = str(compustate.pc - 1)
            trace_data['op'] = op
            if op[:4] == 'PUSH':
                trace_data['pushvalue'] = pushval

        pblogger.multilog(trace_data)

    if op == 'STOP':
        return []
    elif op == 'INVALID':
        return vm_exception('INVALID OP', opcode=opcode)
    elif op == 'ADD':
        stk.append((stk.pop() + stk.pop()) & TT256M1)
    elif op == 'SUB':
        stk.append((stk.pop() - stk.pop()) & TT256M1)
    elif op == 'MUL':
        stk.append((stk.pop() * stk.pop()) & TT256M1)
    elif op == 'DIV':
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 / s1)
    elif op == 'MOD':
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 % s1)
    elif op == 'SDIV':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (abs(s0) // abs(s1) * (-1 if s0*s1 < 0 else 1)) & TT256M1)
    elif op == 'SMOD':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (abs(s0) % abs(s1) * (-1 if s0 < 0 else 1)) & TT256M1)
    elif op == 'ADDMOD':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 + s1) % s2 if s2 else 0)
    elif op == 'MULMOD':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 * s1) % s2 if s2 else 0)
    elif op == 'EXP':
        stk.append(pow(stk.pop(), stk.pop(), TT256))
    elif op == 'SIGNEXTEND':
        s0, s1 = stk.pop(), stk.pop()
        if s0 <= 31:
            testbit = s0 * 8 + 7
            if s1 & (1 << testbit):
                stk.append(s1 | (TT256 - (1 << testbit)))
            else:
                stk.append(s1 & ((1 << testbit) - 1))
        else:
            stk.append(s1)
    elif op == 'LT':
        stk.append(1 if stk.pop() < stk.pop() else 0)
    elif op == 'GT':
        stk.append(1 if stk.pop() > stk.pop() else 0)
    elif op == 'SLT':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(1 if s0 < s1 else 0)
    elif op == 'SGT':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(1 if s0 > s1 else 0)
    elif op == 'EQ':
        stk.append(1 if stk.pop() == stk.pop() else 0)
    elif op == 'ISZERO':
        stk.append(0 if stk.pop() else 1)
    elif op == 'AND':
        stk.append(stk.pop() & stk.pop())
    elif op == 'OR':
        stk.append(stk.pop() | stk.pop())
    elif op == 'XOR':
        stk.append(stk.pop() ^ stk.pop())
    elif op == 'NOT':
        stk.append(TT256M1 - stk.pop())
    elif op == 'BYTE':
        s0, s1 = stk.pop(), stk.pop()
        if s0 >= 32:
            stk.append(0)
        else:
            stk.append((s1 / 256 ** (31 - s0)) % 256)

    elif op == 'SHA3':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, s1):
            return vm_exception('OOG EXTENDING MEMORY')
        data = ''.join(map(chr, mem[s0: s0 + s1]))
        stk.append(utils.big_endian_to_int(utils.sha3(data)))
    elif op == 'ADDRESS':
        stk.append(utils.coerce_to_int(msg.to))
    elif op == 'BALANCE':
        stk.append(block.get_balance(utils.coerce_addr_to_hex(stk.pop())))
    elif op == 'ORIGIN':
        stk.append(utils.coerce_to_int(tx.sender))
    elif op == 'CALLER':
        stk.append(utils.coerce_to_int(msg.sender))
    elif op == 'CALLVALUE':
        stk.append(msg.value)
    elif op == 'CALLDATALOAD':
        s0 = stk.pop()
        if s0 >= len(msg.data):
            stk.append(0)
        else:
            dat = msg.data[s0: s0 + 32]
            stk.append(utils.big_endian_to_int(dat + '\x00' * (32 - len(dat))))
    elif op == 'CALLDATASIZE':
        stk.append(len(msg.data))
    elif op == 'CALLDATACOPY':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, s2):
            return vm_exception('OOG EXTENDING MEMORY')
        for i in range(s2):
            if s1 + i < len(msg.data):
                mem[s0 + i] = ord(msg.data[s1 + i])
            else:
                mem[s0 + i] = 0
    elif op == 'CODESIZE':
        stk.append(len(processed_code))
    elif op == 'CODECOPY':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, s2):
            return vm_exception('OOG EXTENDING MEMORY')
        for i in range(s2):
            if s1 + i < len(processed_code):
                mem[s0 + i] = processed_code[s1 + i][4]
            else:
                mem[s0 + i] = 0
    elif op == 'GASPRICE':
        stk.append(tx.gasprice)
    elif op == 'EXTCODESIZE':
        stk.append(len(block.get_code(utils.coerce_addr_to_hex(stk.pop())) or ''))
    elif op == 'EXTCODECOPY':
        addr, s1, s2, s3 = stk.pop(), stk.pop(), stk.pop(), stk.pop()
        extcode = block.get_code(utils.coerce_addr_to_hex(addr)) or ''
        if not mem_extend(mem, compustate, op, s1, s3):
            return vm_exception('OOG EXTENDING MEMORY')
        for i in range(s3):
            if s2 + i < len(extcode):
                mem[s1 + i] = ord(extcode[s2 + i])
            else:
                mem[s1 + i] = 0
    elif op == 'PREVHASH':
        stk.append(utils.big_endian_to_int(block.prevhash))
    elif op == 'COINBASE':
        stk.append(utils.big_endian_to_int(block.coinbase.decode('hex')))
    elif op == 'TIMESTAMP':
        stk.append(block.timestamp)
    elif op == 'NUMBER':
        stk.append(block.number)
    elif op == 'DIFFICULTY':
        stk.append(block.difficulty)
    elif op == 'GASLIMIT':
        stk.append(block.gas_limit)
    elif op == 'POP':
        stk.pop()
    elif op == 'MLOAD':
        s0 = stk.pop()
        if not mem_extend(mem, compustate, op, s0, 32):
            return vm_exception('OOG EXTENDING MEMORY')
        data = ''.join(map(chr, mem[s0: s0 + 32]))
        stk.append(utils.big_endian_to_int(data))
    elif op == 'MSTORE':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, 32):
            return vm_exception('OOG EXTENDING MEMORY')
        v = s1
        for i in range(31, -1, -1):
            mem[s0 + i] = v % 256
            v /= 256
    elif op == 'MSTORE8':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, 1):
            return vm_exception('OOG EXTENDING MEMORY')
        mem[s0] = s1 % 256
    elif op == 'SLOAD':
        stk.append(block.get_storage_data(msg.to, stk.pop()))
    elif op == 'SSTORE':
        s0, s1 = stk.pop(), stk.pop()
        if block.get_storage_data(msg.to, s0):
            gascost = GSTORAGEMOD if s1 else GSTORAGEKILL
        else:
            gascost = GSTORAGEADD if s1 else GSTORAGEMOD
        if compustate.gas < gascost:
            return vm_exception('OUT OF GAS')
        compustate.gas -= max(gascost, 0)
        block.refunds -= min(gascost, 0)  # adds neg gascost as a refund if below zero
        block.set_storage_data(msg.to, s0, s1)
    elif op == 'JUMP' or op == 'JUMPSTATIC':
        compustate.pc = stk.pop()
        opnew = processed_code[compustate.pc][0] if \
            compustate.pc < len(processed_code) else 'STOP'
        if (op != 'JUMPSTATIC' and opnew != 'JUMPDEST') or \
                opnew in ['JUMP', 'JUMPI', 'JUMPSTATIC', 'JUMPISTATIC']:
            return vm_exception('BAD JUMPDEST')
    elif op == 'JUMPI' or op == 'JUMPISTATIC':
        s0, s1 = stk.pop(), stk.pop()
        if s1:
            compustate.pc = s0
            opnew = processed_code[compustate.pc][0] if \
                compustate.pc < len(processed_code) else 'STOP'
            if (op != 'JUMPISTATIC' and opnew != 'JUMPDEST') or \
                    opnew in ['JUMP', 'JUMPI', 'JUMPSTATIC', 'JUMPISTATIC']:
                return vm_exception('BAD JUMPDEST')
    elif op == 'PC':
        stk.append(compustate.pc - 1)
    elif op == 'MSIZE':
        stk.append(len(mem))
    elif op == 'GAS':
        stk.append(compustate.gas)  # AFTER subtracting cost 1
    elif op[:4] == 'PUSH':
        pushnum = int(op[4:])
        compustate.pc += pushnum
        stk.append(pushval)
    elif op[:3] == 'DUP':
        depth = int(op[3:])
        stk.append(stk[-depth])
    elif op[:4] == 'SWAP':
        depth = int(op[4:])
        temp = stk[-depth-1]
        stk[-depth-1] = stk[-1]
        stk[-1] = temp
    elif op[:3] == 'LOG':
        depth = int(op[3:])
        mstart, msz = stk.pop(), stk.pop()
        topics = [stk.pop() for x in range(depth)]
        compustate.gas -= msz
        if not mem_extend(mem, compustate, op, mstart, msz):
            return vm_exception('OOG EXTENDING MEMORY')

        data = ''.join(map(chr, mem[mstart: mstart + msz]))
        block.logs.append(Log(msg.to, topics, data))
        pblogger.log('LOG', to=msg.to, topics=topics, data=map(ord, data))
    elif op == 'CREATE':
        value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, mstart, msz):
            return vm_exception('OOG EXTENDING MEMORY')
        if block.get_balance(msg.to) >= value:
            data = ''.join(map(chr, mem[mstart: mstart + msz]))
            pblogger.log('SUB CONTRACT NEW', sender=msg.to, value=value, data=data.encode('hex'))
            create_msg = Message(msg.to, '', value, compustate.gas, data, msg.depth + 1)
            addr, gas, code = create_contract(block, tx, create_msg)
            pblogger.log('SUB CONTRACT OUT',
                         address=utils.int_to_addr(addr),
                         code=''.join([chr(x).encode('hex') for x in code]))
            if addr:
                stk.append(addr)
                compustate.gas = gas
            else:
                stk.append(0)
                compustate.gas = 0
        else:
            stk.append(0)
    elif op == 'CALL':
        gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                not mem_extend(mem, compustate, op, memoutstart, memoutsz):
            return vm_exception('OOG EXTENDING MEMORY')
        if compustate.gas < gas:
            return vm_exception('OUT OF GAS')
        compustate.gas -= gas
        if block.get_balance(msg.to) >= value:
            to = utils.encode_int(to)
            to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
            data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
            pblogger.log('SUB CALL NEW', sender=msg.to, to=to, value=str(value),
                         gas=str(gas), data=data.encode('hex'),
                         parentgas=str(compustate.gas), depth=str(msg.depth + 1))
            call_msg = Message(msg.to, to, value, gas, data, msg.depth + 1)
            result, gas, data = apply_msg_send(block, tx, call_msg)
            pblogger.log('SUB CALL OUT', result=result, data=data, length=len(data),
                         expected=memoutsz, csg=compustate.gas)
            if result == 0:
                stk.append(0)
            else:
                stk.append(1)
                compustate.gas += gas
                for i in range(min(len(data), memoutsz)):
                    mem[memoutstart + i] = data[i]
        else:
            stk.append(0)
    elif op == 'RETURN':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, s1):
            return vm_exception('OOG EXTENDING MEMORY')
        return mem[s0: s0 + s1]
    elif op == 'CALL_CODE':
        gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                not mem_extend(mem, compustate, op, memoutstart, memoutsz):
            return vm_exception('OOG EXTENDING MEMORY')
        if compustate.gas < gas:
            return vm_exception('OUT OF GAS')
        compustate.gas -= gas
        to = utils.encode_int(to)
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        pblogger.log('SUB CALL NEW', sender=msg.to, to=to, value=value, gas=gas, data=data.encode('hex'))
        call_msg = Message(msg.to, msg.to, value, gas, data, msg.depth + 1)
        result, gas, data = apply_msg(block, tx, call_msg, block.get_code(to))
        pblogger.log('SUB CALL OUT', result=result, data=data, length=len(data), expected=memoutsz)
        if result == 0:
            stk.append(0)
        else:
            stk.append(1)
            compustate.gas += gas
            for i in range(min(len(data), memoutsz)):
                mem[memoutstart + i] = data[i]
    elif op == 'SUICIDE':
        to = utils.encode_int(stk.pop())
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        block.transfer_value(msg.to, to, block.get_balance(msg.to))
        block.suicides.append(msg.to)
        return []
    for a in stk:
        assert isinstance(a, (int, long))

# apply_msg = fastvm.apply_msg
