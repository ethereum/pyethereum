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
import time
logger = logging.getLogger(__name__)



class PBLogger(object):
    log_op = True           # log op, gas, stack before each op
    log_pre_state = True   # dump storage at account before execution
    log_post_state = True  # dump storage at account after execution
    log_block = True       # dump block after TX was applied
    log_memory = True      # dump memory before each op
    log_json = True        # generate machine readable output

    def __init__(self):
        self.listeners = [] # register callbacks here

    def log(self, name, **kargs):
        # call callbacks
        for l in self.listeners:
            l(name, kargs)
        if self.log_json:
            logger.debug(json.dumps({name:kargs}))
        else:
            order = dict(pc=-2, op=-1, stackargs=1, data=2, code=3)
            items = sorted(kargs.items(), key=lambda x: order.get(x[0], 0))
            msg = ", ".join("%s=%s" % (k,v) for k,v in items)
            logger.debug("%s: %s", name.ljust(15), msg)

pblogger = PBLogger()


GDEFAULT = 1
GMEMORY = 1
GTXDATA = 5
GTXCOST = 500

OUT_OF_GAS = -1

# contract creating transactions send to an empty address
CREATE_CONTRACT_ADDRESS = ''

class VerificationFailed(Exception):
    pass

def verify(block, parent):
    def must_equal(what, a, b):
        if not a == b: raise VerificationFailed(what, a, '==', b)

    if not block.timestamp >= parent.timestamp:
        raise VerificationFailed('timestamp', block.timestamp, '>=', parent.timestamp)
    if not block.timestamp <= time.time() + 900:
        raise VerificationFailed('timestamps', block.timestamp, '<=', time.time() + 900)

    block2 = blocks.Block.init_from_parent(parent,
                                           block.coinbase,
                                           extra_data=block.extra_data,
                                           timestamp=block.timestamp,
                                           uncles=block.uncles)
    must_equal('difficulty', block2.difficulty, block.difficulty)
    must_equal('gas limit', block2.gas_limit, block.gas_limit)
    for i in range(block.transaction_count):
        tx, s, g = rlp.decode(
            block.transactions.get(rlp.encode(utils.encode_int(i))))
        tx = transactions.Transaction.create(tx)
        if not tx.startgas + block2.gas_used <= block.gas_limit:
            raise VerificationFailed('gas_limit', tx.startgas + block2.gas_used, '<=', block.gas_limit)
        apply_transaction(block2, tx)
        must_equal('tx state root', s, block2.state.root_hash)
        must_equal('tx gas used', g, utils.encode_int(block2.gas_used))
    block2.finalize()
    must_equal('block state root', block2.state.root_hash, block.state.root_hash)
    must_equal('block gas used', block2.gas_used, block.gas_used)
    return True


class Message(object):

    def __init__(self, sender, to, value, gas, data):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data

    def __repr__(self):
        return '<Message(to:%s...)>' % self.to[:8]


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
    if tx.gasprice < block.min_gas_price:
        raise GasPriceTooLow(rp(tx.gasprice, block.min_gas_price))

    # check block gas limit
    if block.gas_used + tx.startgas > block.gas_limit:
        raise BlockGasLimitReached(rp(block.gas_used + tx.startgas, block.gas_limit))


    pblogger.log('TX NEW', tx=tx.hex_hash(), tx_dict=tx.to_dict())
    # start transacting #################
    block.increment_nonce(tx.sender)

    # buy startgas
    success = block.transfer_value(tx.sender, block.coinbase,
                                   tx.gasprice * tx.startgas)
    assert success

    message_gas = tx.startgas - intrinsic_gas_used
    message = Message(tx.sender, tx.to, tx.value, message_gas, tx.data)

    block.postqueue = [ message ]
    primary_result = None
    while len(block.postqueue):
        message = block.postqueue.pop(0)
        # MESSAGE
        if tx.to and tx.to != CREATE_CONTRACT_ADDRESS:
            result, gas_remained, data = apply_msg_send(block, tx, message)
        else:  # CREATE
            result, gas_remained, data = create_contract(block, tx, message)
            if result > 0:
                result = utils.coerce_addr_to_hex(result)
        if not primary_result:
            primary_result = result, gas_remained, data

    result, gas_remained, data = primary_result

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


def decode_datalist(arr):
    if isinstance(arr, list):
        arr = ''.join(map(chr, arr))
    o = []
    for i in range(0, len(arr), 32):
        o.append(utils.big_endian_to_int(arr[i:i + 32]))
    return o


def apply_msg(block, tx, msg, code):
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
    t, ops = time.time(), 0
    # Main loop
    while 1:
        o = apply_op(block, tx, msg, code, compustate)
        ops += 1
        if o is not None:
            pblogger.log('MSG APPLIED', result=o, gas_remained=compustate.gas,
                        ops=ops, time_per_op=(time.time() - t) / ops)
            if pblogger.log_post_state:
                    pblogger.log('MSG POST STATE', account=msg.to,
                        state=block.account_to_dict(msg.to))

            if o == OUT_OF_GAS:
                block.revert(snapshot)
                return 0, compustate.gas, []
            else:
                return 1, compustate.gas, o


def apply_msg_send(block, tx, msg):
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
        if tx.sender != msg.sender:
            block.decrement_nonce(msg.sender)
        block.del_account(msg.to)
        return res, gas, dat


def get_opcode(code, index):
    return ord(code[index]) if index < len(code) else 0


def get_op_data(code, index):
    opcode = ord(code[index]) if index < len(code) else 0
    return opcodes.get(opcode, ['INVALID', 0, 0, [], 0])


def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)


def calcfee(block, tx, msg, compustate, op_data):
    stk, mem = compustate.stack, compustate.memory
    op, ins, outs, memuse, base_gas = op_data
    m_extend = 0
    for start, sz in memuse:
        start = start if start >= 0 else stk[start]
        sz = sz if sz >= 0 else stk[sz]
        m_extend = max(m_extend, ceil32(start + sz) - len(mem))
    COST = m_extend / 32 * GMEMORY + base_gas

    if op == 'CALL' or op == 'POST' or op == 'CALL_STATELESS':
        return COST + stk[-1]
    elif op == 'SSTORE':
        pre_occupied = COST if block.get_storage_data(msg.to, stk[-1]) else 0
        post_occupied = COST if stk[-2] else 0
        return COST + post_occupied - pre_occupied
    else:
        return COST

# Does not include paying opfee
def apply_op(block, tx, msg, code, compustate):
    op, in_args, out_args, mem_grabs, base_gas = opdata = get_op_data(code, compustate.pc)
    # empty stack error
    if in_args > len(compustate.stack):
        pblogger.log('INSUFFICIENT STACK ERROR', op=op, needed=in_args,
                     available=len(compustate.stack))
        return []
    # out of gas error
    fee = calcfee(block, tx, msg, compustate, opdata)
    if fee > compustate.gas:
        pblogger.log('OUT OF GAS', needed=fee, available=compustate.gas,
                            op=op, stack=list(reversed(compustate.stack)))
        return OUT_OF_GAS
    stackargs = []
    for i in range(in_args):
        stackargs.append(compustate.stack.pop())

    if pblogger.log_op:
        log_args = dict(pc=compustate.pc, op=op, stackargs=stackargs, gas=compustate.gas)
        if op[:4] == 'PUSH':
            ind = compustate.pc + 1
            log_args['value'] = utils.big_endian_to_int(code[ind: ind + int(op[4:])])
        elif op == 'CALLDATACOPY':
            log_args['data'] = msg.data.encode('hex')
        pblogger.log('OP', **log_args)

    if pblogger.log_memory:
        for i in range(0, len(compustate.memory), 16):
            memblk = compustate.memory[i:i+16]
            memline = ' '.join([chr(x).encode('hex') for x in memblk])
            pblogger.log('MEM', mem=memline)

    # Apply operation
    oldpc = compustate.pc
    compustate.gas -= fee
    compustate.pc += 1
    stk = compustate.stack
    mem = compustate.memory
    if op == 'STOP' or op == 'INVALID':
        return []
    elif op == 'ADD':
        stk.append((stackargs[0] + stackargs[1]) % 2 ** 256)
    elif op == 'SUB':
        stk.append((stackargs[0] - stackargs[1]) % 2 ** 256)
    elif op == 'MUL':
        stk.append((stackargs[0] * stackargs[1]) % 2 ** 256)
    elif op == 'DIV':
        stk.append(0 if stackargs[1] == 0 else stackargs[0] / stackargs[1])
    elif op == 'MOD':
        stk.append(0 if stackargs[1] == 0 else stackargs[0] % stackargs[1])
    elif op == 'SDIV':
        if stackargs[0] >= 2 ** 255:
            stackargs[0] -= 2 ** 256
        if stackargs[1] >= 2 ** 255:
            stackargs[1] -= 2 ** 256
        stk.append(0 if stackargs[1] == 0 else
                   (stackargs[0] / stackargs[1]) % 2 ** 256)
    elif op == 'SMOD':
        if stackargs[0] >= 2 ** 255:
            stackargs[0] -= 2 ** 256
        if stackargs[1] >= 2 ** 255:
            stackargs[1] -= 2 ** 256
        stk.append(0 if stackargs[1] == 0 else
                   (stackargs[0] % stackargs[1]) % 2 ** 256)
    elif op == 'EXP':
        stk.append(pow(stackargs[0], stackargs[1], 2 ** 256))
    elif op == 'NEG':
        stk.append(-stackargs[0] % 2**256)
    elif op == 'LT':
        stk.append(1 if stackargs[0] < stackargs[1] else 0)
    elif op == 'GT':
        stk.append(1 if stackargs[0] > stackargs[1] else 0)
    elif op == 'SLT':
        if stackargs[0] >= 2 ** 255:
            stackargs[0] -= 2 ** 256
        if stackargs[1] >= 2 ** 255:
            stackargs[1] -= 2 ** 256
        stk.append(1 if stackargs[0] < stackargs[1] else 0)
    elif op == 'SGT':
        if stackargs[0] >= 2 ** 255:
            stackargs[0] -= 2 ** 256
        if stackargs[1] >= 2 ** 255:
            stackargs[1] -= 2 ** 256
        stk.append(1 if stackargs[0] > stackargs[1] else 0)
    elif op == 'EQ':
        stk.append(1 if stackargs[0] == stackargs[1] else 0)
    elif op == 'NOT':
        stk.append(0 if stackargs[0] else 1)
    elif op == 'AND':
        stk.append(stackargs[0] & stackargs[1])
    elif op == 'OR':
        stk.append(stackargs[0] | stackargs[1])
    elif op == 'XOR':
        stk.append(stackargs[0] ^ stackargs[1])
    elif op == 'BYTE':
        if stackargs[0] >= 32:
            stk.append(0)
        else:
            stk.append((stackargs[1] / 256 ** (31 - stackargs[0])) % 256)
    elif op == 'ADDMOD':
        stk.append((stackargs[0] + stackargs[1]) % stackargs[2]
                   if stackargs[2] else 0)
    elif op == 'MULMOD':
        stk.append((stackargs[0] * stackargs[1]) % stackargs[2]
                   if stackargs[2] else 0)
    elif op == 'SHA3':
        if stackargs[1] and len(mem) < ceil32(stackargs[0] + stackargs[1]):
            mem.extend([0] * (ceil32(stackargs[0] + stackargs[1]) - len(mem)))
        data = ''.join(map(chr, mem[stackargs[0]:stackargs[0] + stackargs[1]]))
        stk.append(utils.big_endian_to_int(utils.sha3(data)))
    elif op == 'ADDRESS':
        stk.append(utils.coerce_to_int(msg.to))
    elif op == 'BALANCE':
        stk.append(block.get_balance(utils.coerce_addr_to_hex(stackargs[0])))
    elif op == 'ORIGIN':
        stk.append(utils.coerce_to_int(tx.sender))
    elif op == 'CALLER':
        stk.append(utils.coerce_to_int(msg.sender))
    elif op == 'CALLVALUE':
        stk.append(msg.value)
    elif op == 'CALLDATALOAD':
        if stackargs[0] >= len(msg.data):
            stk.append(0)
        else:
            dat = msg.data[stackargs[0]:stackargs[0] + 32]
            stk.append(utils.big_endian_to_int(dat + '\x00' * (32 - len(dat))))
    elif op == 'CALLDATASIZE':
        stk.append(len(msg.data))
    elif op == 'CALLDATACOPY':
        if stackargs[2] and len(mem) < ceil32(stackargs[0] + stackargs[2]):
            mem.extend([0] * (ceil32(stackargs[0] + stackargs[2]) - len(mem)))
        for i in range(stackargs[2]):
            if stackargs[1] + i < len(msg.data):
                mem[stackargs[0] + i] = ord(msg.data[stackargs[1] + i])
            else:
                mem[stackargs[0] + i] = 0
    elif op == 'GASPRICE':
        stk.append(tx.gasprice)
    elif op == 'CODECOPY':
        if stackargs[2] and len(mem) < ceil32(stackargs[0] + stackargs[2]):
            mem.extend([0] * (ceil32(stackargs[0] + stackargs[2]) - len(mem)))
        for i in range(stackargs[2]):
            if stackargs[1] + i < len(code):
                mem[stackargs[0] + i] = ord(code[stackargs[1] + i])
            else:
                mem[stackargs[0] + i] = 0
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
        pass
    elif op == 'SWAP':
        stk.append(stackargs[0])
        stk.append(stackargs[1])
    elif op == 'MLOAD':
        if len(mem) < ceil32(stackargs[0] + 32):
            mem.extend([0] * (ceil32(stackargs[0] + 32) - len(mem)))
        data = ''.join(map(chr, mem[stackargs[0]:stackargs[0] + 32]))
        stk.append(utils.big_endian_to_int(data))
    elif op == 'MSTORE':
        if len(mem) < ceil32(stackargs[0] + 32):
            mem.extend([0] * (ceil32(stackargs[0] + 32) - len(mem)))
        v = stackargs[1]
        for i in range(31, -1, -1):
            mem[stackargs[0] + i] = v % 256
            v /= 256
    elif op == 'MSTORE8':
        if len(mem) < ceil32(stackargs[0] + 1):
            mem.extend([0] * (ceil32(stackargs[0] + 1) - len(mem)))
        mem[stackargs[0]] = stackargs[1] % 256
    elif op == 'SLOAD':
        stk.append(block.get_storage_data(msg.to, stackargs[0]))
    elif op == 'SSTORE':
        block.set_storage_data(msg.to, stackargs[0], stackargs[1])
    elif op == 'JUMP':
        compustate.pc = stackargs[0]
    elif op == 'JUMPI':
        if stackargs[1]:
            compustate.pc = stackargs[0]
    elif op == 'PC':
        stk.append(compustate.pc)
    elif op == 'MSIZE':
        stk.append(len(mem))
    elif op == 'GAS':
        stk.append(compustate.gas)  # AFTER subtracting cost 1
    elif op[:4] == 'PUSH':
        pushnum = int(op[4:])
        compustate.pc = oldpc + 1 + pushnum
        dat = code[oldpc + 1: oldpc + 1 + pushnum]
        stk.append(utils.big_endian_to_int(dat))
    elif op[:3] == 'DUP':
        # DUP POP POP Debug hint
        is_debug = 1
        for i in range(len(stackargs)):
            if get_op_data(code, oldpc + i + 1)[0] != 'POP':
                is_debug = 0
                break
        if is_debug:
            print(' '.join(map(repr, stackargs)))
            pblogger.log('DEBUG', vals=stackargs)
            compustate.pc = oldpc + 2 + len(stackargs)
        else:
            stk.extend(reversed(stackargs))
            stk.append(stackargs[-1])
    elif op[:4] == 'SWAP':
        stk.append(stackargs[0])
        stk.extend(reversed(stackargs[1:-1]))
        stk.append(stackargs[-1])
    elif op == 'CREATE':
        if stackargs[2] and len(mem) < ceil32(stackargs[1] + stackargs[2]):
            mem.extend([0] * (ceil32(stackargs[1] + stackargs[2]) - len(mem)))
        value = stackargs[0]
        data = ''.join(map(chr, mem[stackargs[1]:stackargs[1] + stackargs[2]]))
        pblogger.log('SUB CONTRACT NEW', sender=msg.to, value=value, data=data.encode('hex'))
        create_msg = Message(msg.to, '', value, compustate.gas, data)
        addr, gas, code = create_contract(block, tx, create_msg)
        pblogger.log('SUB CONTRACT OUT', address=addr, code=code)
        if addr:
            stk.append(addr)
            compustate.gas = gas
        else:
            stk.append(0)
            compustate.gas = 0
    elif op == 'CALL':
        if stackargs[4] and len(mem) < ceil32(stackargs[3] + stackargs[4]):
            mem.extend([0] * (ceil32(stackargs[3] + stackargs[4]) - len(mem)))
        if stackargs[6] and len(mem) < ceil32(stackargs[5] + stackargs[6]):
            mem.extend([0] * (ceil32(stackargs[5] + stackargs[6]) - len(mem)))
        gas = stackargs[0]
        to = utils.encode_int(stackargs[1])
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        value = stackargs[2]
        data = ''.join(map(chr, mem[stackargs[3]:stackargs[3] + stackargs[4]]))
        pblogger.log('SUB CALL NEW', sender=msg.to, to=to, value=value, gas=gas, data=data.encode('hex'))
        call_msg = Message(msg.to, to, value, gas, data)
        result, gas, data = apply_msg_send(block, tx, call_msg)
        pblogger.log('SUB CALL OUT', result=result, data=data, length=len(data), expected=stackargs[6])
        if result == 0:
            stk.append(0)
        else:
            stk.append(1)
            compustate.gas += gas
            for i in range(min(len(data), stackargs[6])):
                mem[stackargs[5] + i] = data[i]
    elif op == 'RETURN':
        if stackargs[1] and len(mem) < ceil32(stackargs[0] + stackargs[1]):
            mem.extend([0] * (ceil32(stackargs[0] + stackargs[1]) - len(mem)))
        return mem[stackargs[0]:stackargs[0] + stackargs[1]]
    elif op == 'POST':
        if stackargs[4] and len(mem) < ceil32(stackargs[3] + stackargs[4]):
            mem.extend([0] * (ceil32(stackargs[3] + stackargs[4]) - len(mem)))
        gas = stackargs[0]
        to = utils.encode_int(stackargs[1])
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        value = stackargs[2]
        data = ''.join(map(chr, mem[stackargs[3]:stackargs[3] + stackargs[4]]))
        pblogger.log('POST NEW', sender=msg.to, to=to, value=value, gas=gas, data=data.encode('hex'))
        post_msg = Message(msg.to, to, value, gas, data)
        block.postqueue.append(post_msg)
    elif op == 'CALL_STATELESS':
        if stackargs[4] and len(mem) < ceil32(stackargs[3] + stackargs[4]):
            mem.extend([0] * (ceil32(stackargs[3] + stackargs[4]) - len(mem)))
        if stackargs[6] and len(mem) < ceil32(stackargs[5] + stackargs[6]):
            mem.extend([0] * (ceil32(stackargs[5] + stackargs[6]) - len(mem)))
        gas = stackargs[0]
        to = utils.encode_int(stackargs[1])
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        value = stackargs[2]
        data = ''.join(map(chr, mem[stackargs[3]:stackargs[3] + stackargs[4]]))
        pblogger.log('SUB CALL NEW', sender=msg.to, to=to, value=value, gas=gas, data=data.encode('hex'))
        call_msg = Message(msg.to, msg.to, value, gas, data)
        result, gas, data = apply_msg(block, tx, call_msg, block.get_code(to))
        pblogger.log('SUB CALL OUT', result=result, data=data, length=len(data), expected=stackargs[6])
        if result == 0:
            stk.append(0)
        else:
            stk.append(1)
            compustate.gas += gas
            for i in range(min(len(data), stackargs[6])):
                mem[stackargs[5] + i] = data[i]

    elif op == 'SUICIDE':
        to = utils.encode_int(stackargs[0])
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        block.transfer_value(msg.to, to, block.get_balance(msg.to))
        block.suicides.append(msg.to)
        return []
    for a in stk:
        assert isinstance(a, (int, long))
