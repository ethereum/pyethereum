import rlp
from opcodes import opcodes

import utils
import time
import blocks
import transactions
import trie
import logging
logger = logging.getLogger(__name__)

print_debug = 0


def enable_debug():
    global print_debug
    print_debug = 1


def disable_debug():
    global print_debug
    print_debug = 0


def logger_debug(*args):
    logger.debug(*args)
    if print_debug:
        print(args[0] % tuple(args[1:]))

GSTEP = 1
GSTOP = 0
GSHA3 = 20
GSLOAD = 20
GSSTORE = 100
GBALANCE = 20
GCREATE = 100
GCALL = 20
GMEMORY = 1
GTXDATA = 5
GTXCOST = 500

OUT_OF_GAS = -1

CREATE_CONTRACT_ADDRESS = '0000000000000000000000000000000000000000'


def verify(block, parent):
    assert block.timestamp >= parent.timestamp
    assert block.timestamp <= time.time() + 900
    block2 = blocks.Block.init_from_parent(parent,
                                           block.coinbase,
                                           extra_data=block.extra_data,
                                           timestamp=block.timestamp,
                                           uncles=block.uncles)
    assert block2.difficulty == block.difficulty
    assert block2.gas_limit == block.gas_limit
    block2.finalize()
    for i in range(block.transaction_count):
        tx, s, g = rlp.decode(block.transactions.get(utils.encode_int(i)))
        tx = transactions.Transaction.create(tx)
        assert tx.startgas + block2.gas_used <= block.gas_limit
        apply_transaction(block2, tx)
        assert s == block2.state.root_hash
        assert g == utils.encode_int(block2.gas_used)
    assert block2.state.root_hash == block.state.root_hash
    assert block2.gas_used == block.gas_used
    return True


class Message(object):

    def __init__(self, sender, to, value, gas, data):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data


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
        BlockGasLimitReached(
            rp(block.gas_used + tx.startgas, block.gas_limit))

    # start transacting #################
    if tx.to:
        block.increment_nonce(tx.sender)

    # buy startgas
    success = block.transfer_value(tx.sender, block.coinbase,
                                   tx.gasprice * tx.startgas)
    assert success

    snapshot = block.snapshot()
    message_gas = tx.startgas - intrinsic_gas_used
    message = Message(tx.sender, tx.to, tx.value, message_gas, tx.data)
    # MESSAGE
    if tx.to and tx.to != CREATE_CONTRACT_ADDRESS:
        result, gas_remained, data = apply_msg(block, tx, message)
    else:  # CREATE
        result, gas_remained, data = create_contract(block, tx, message)
    assert gas_remained >= 0
    logger.debug(
        'applied tx, result %s gas remained %s data/code %s', result,
        gas_remained, ''.join(map(chr, data)).encode('hex'))
    if not result:  # 0 = OOG failure in both cases
        block.revert(snapshot)
        block.gas_used += tx.startgas
        output = OUT_OF_GAS
    else:
        gas_used = tx.startgas - gas_remained
        # sell remaining gas
        block.transfer_value(
            block.coinbase, tx.sender, tx.gasprice * gas_remained)
        block.gas_used += gas_used
        output = ''.join(map(chr, data)) if tx.to else result.encode('hex')
    for s in block.suicides:
        block.state.delete(s)
        block.suicides = []
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


def apply_msg(block, tx, msg):
    logger.debug("apply_msg:%r %r", tx, msg)
    snapshot = block.snapshot()
    code = block.get_code(msg.to)
    # Transfer value, instaquit if not enough
    o = block.transfer_value(msg.sender, msg.to, msg.value)
    if not o:
        return 0, msg.gas, []
    compustate = Compustate(gas=msg.gas)
    # Main loop
    while 1:
        logger.debug({
            "Stack": compustate.stack,
            "PC": compustate.pc,
            "Gas": compustate.gas,
            "Memory": decode_datalist(compustate.memory),
            "Storage": block.get_storage(msg.to).to_dict(),
        })
        o = apply_op(block, tx, msg, code, compustate)
        if o is not None:
            logger.debug('done %s', o)
            if o == OUT_OF_GAS:
                block.revert(snapshot)
                return 0, 0, []
            else:
                return 1, compustate.gas, o


def create_contract(block, tx, msg):
    snapshot = block.snapshot()

    sender = msg.sender.decode('hex') if len(msg.sender) == 40 else msg.sender
    nonce = utils.encode_int(block.get_nonce(msg.sender))
    recvaddr = utils.sha3(rlp.encode([sender, nonce]))[12:]
    assert not block.get_code(recvaddr)
    msg.to = recvaddr
    block.increment_nonce(msg.sender)
    # Transfer value, instaquit if not enough
    o = block.transfer_value(msg.sender, msg.to, msg.value)
    if not o:
        return 0, msg.gas
    compustate = Compustate(gas=msg.gas)
    # Main loop
    while 1:
        o = apply_op(block, tx, msg, msg.data, compustate)
        if o is not None:
            if o == OUT_OF_GAS:
                block.revert(snapshot)
                return 0, 0, []
            else:
                block.set_code(recvaddr, ''.join(map(chr, o)))
                return recvaddr, compustate.gas, o


def get_op_data(code, index):
    opcode = ord(code[index]) if index < len(code) else 0
    if opcode < 96 or (opcode >= 240 and opcode <= 255):
        if opcode in opcodes:
            return opcodes[opcode]
        else:
            return 'INVALID', 0, 0
    elif opcode < 128:
        return 'PUSH' + str(opcode - 95), 0, 1
    else:
        return 'INVALID', 0, 0


def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)


def calcfee(block, tx, msg, compustate, op):
    stk, mem = compustate.stack, compustate.memory
    if op == 'SHA3':
        m_extend = max(0, ceil32(stk[-1] + stk[-2]) - len(mem))
        return GSHA3 + m_extend / 32 * GMEMORY
    elif op == 'SLOAD':
        return GSTEP + GSLOAD
    elif op == 'SSTORE':
        if not block.get_storage_data(msg.to, stk[-1]) and stk[-2]:
            return 2 * GSSTORE
        elif block.get_storage_data(msg.to, stk[-1]) and not stk[-2]:
            return 0
        else:
            return GSSTORE
    elif op == 'MLOAD':
        m_extend = max(0, ceil32(stk[-1] + 32) - len(mem))
        return GSTEP + m_extend / 32 * GMEMORY
    elif op == 'MSTORE':
        m_extend = max(0, ceil32(stk[-1] + 32) - len(mem))
        return GSTEP + m_extend / 32 * GMEMORY
    elif op == 'MSTORE8':
        m_extend = max(0, ceil32(stk[-1] + 1) - len(mem))
        return GSTEP + m_extend / 32 * GMEMORY
    elif op == 'CALL':
        m_extend = max(0,
                       ceil32(stk[-4] + stk[-5]) - len(mem),
                       ceil32(stk[-6] + stk[-7]) - len(mem))
        return GCALL + stk[-1] + m_extend / 32 * GMEMORY
    elif op == 'CREATE':
        m_extend = max(0, ceil32(stk[-2] + stk[-3]) - len(mem))
        return GSTEP + GCREATE + m_extend / 32 * GMEMORY
    elif op == 'RETURN':
        m_extend = max(0, ceil32(stk[-1] + stk[-2]) - len(mem))
        return GSTEP + m_extend / 32 * GMEMORY
    elif op == 'CALLDATACOPY':
        m_extend = max(0, ceil32(stk[-1] + stk[-3]) - len(mem))
        return GSTEP + m_extend / 32 * GMEMORY
    elif op == 'CODECOPY':
        m_extend = max(0, ceil32(stk[-1] + stk[-3]) - len(mem))
        return GSTEP + m_extend / 32 * GMEMORY
    elif op == 'BALANCE':
        return GBALANCE
    elif op == 'STOP' or op == 'INVALID' or op == 'SUICIDE':
        return GSTOP
    else:
        return GSTEP

# Does not include paying opfee


def apply_op(block, tx, msg, code, compustate):
    op, in_args, out_args = get_op_data(code, compustate.pc)
    # empty stack error
    if in_args > len(compustate.stack):
        return []
    # out of gas error
    fee = calcfee(block, tx, msg, compustate, op)
    if fee > compustate.gas:
        logger.debug("Out of gas %s need %s", compustate.gas, fee)
        logger.debug('%s %s', op, list(reversed(compustate.stack)))
        return OUT_OF_GAS
    stackargs = []
    for i in range(in_args):
        stackargs.append(compustate.stack.pop())
    if op[:4] == 'PUSH':
        ind = compustate.pc + 1
        v = utils.big_endian_to_int(code[ind: ind + int(op[4:])])
        logger_debug('%s %s %s', compustate.pc, op, v)
    else:
        logger_debug('%s %s %s', compustate.pc, op, stackargs)
    # Apply operation
    oldgas = compustate.gas
    oldpc = compustate.pc
    compustate.gas -= fee
    compustate.pc += 1
    stk = compustate.stack
    mem = compustate.memory
    if op == 'STOP':
        return []
    elif op == 'ADD':
        stk.append((stackargs[0] + stackargs[1]) % 2 ** 256)
    elif op == 'SUB':
        stk.append((stackargs[0] - stackargs[1]) % 2 ** 256)
    elif op == 'MUL':
        stk.append((stackargs[0] * stackargs[1]) % 2 ** 256)
    elif op == 'DIV':
        if stackargs[1] == 0:
            return []
        stk.append(stackargs[0] / stackargs[1])
    elif op == 'MOD':
        if stackargs[1] == 0:
            return []
        stk.append(stackargs[0] % stackargs[1])
    elif op == 'SDIV':
        if stackargs[1] == 0:
            return []
        if stackargs[0] >= 2 ** 255:
            stackargs[0] -= 2 ** 256
        if stackargs[1] >= 2 ** 255:
            stackargs[1] -= 2 ** 256
        stk.append((stackargs[0] / stackargs[1]) % 2 ** 256)
    elif op == 'SMOD':
        if stackargs[1] == 0:
            return []
        if stackargs[0] >= 2 ** 255:
            stackargs[0] -= 2 ** 256
        if stackargs[1] >= 2 ** 255:
            stackargs[1] -= 2 ** 256
        stk.append((stackargs[0] % stackargs[1]) % 2 ** 256)
    elif op == 'EXP':
        stk.append(pow(stackargs[0], stackargs[1], 2 ** 256))
    elif op == 'NEG':
        stk.append(2 ** 256 - stackargs[0])
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
            stk.append((stackargs[1] / 256 ** stackargs[0]) % 256)
    elif op == 'SHA3':
        if len(mem) < ceil32(stackargs[0] + stackargs[1]):
            mem.extend([0] * (ceil32(stackargs[0] + stackargs[1]) - len(mem)))
        data = ''.join(map(chr, mem[stackargs[0]:stackargs[0] + stackargs[1]]))
        stk.append(utils.big_endian_to_int(utils.sha3(data)))
    elif op == 'ADDRESS':
        stk.append(utils.coerce_to_int(msg.to))
    elif op == 'BALANCE':
        stk.append(block.get_balance(msg.to))
    elif op == 'ORIGIN':
        stk.append(tx.sender)
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
        if len(mem) < ceil32(stackargs[1] + stackargs[2]):
            mem.extend([0] * (ceil32(stackargs[1] + stackargs[2]) - len(mem)))
        for i in range(stackargs[2]):
            if stackargs[0] + i < len(msg.data):
                mem[stackargs[1] + i] = ord(msg.data[stackargs[0] + i])
            else:
                mem[stackargs[1] + i] = 0
    elif op == 'GASPRICE':
        stk.append(tx.gasprice)
    elif op == 'CODECOPY':
        if len(mem) < ceil32(stackargs[1] + stackargs[2]):
            mem.extend([0] * (ceil32(stackargs[1] + stackargs[2]) - len(mem)))
        for i in range(stackargs[2]):
            if stackargs[0] + i < len(code):
                mem[stackargs[1] + i] = ord(code[stackargs[0] + i])
            else:
                mem[stackargs[1] + i] = 0
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
        stk.append(block.gaslimit)
    elif op == 'POP':
        pass
    elif op == 'DUP':
        # DUP POP POP Debug hint
        if get_op_data(code, oldpc + 1)[0] == 'POP' and \
           get_op_data(code, oldpc + 2)[0] == 'POP':
            o = print_debug
            enable_debug()
            logger_debug("Debug: %s", stackargs[0])
            if not o:
                disable_debug()
            compustate.pc = oldpc + 3
        else:
            stk.append(stackargs[0])
            stk.append(stackargs[0])
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
        stk.append(oldgas)
    elif op[:4] == 'PUSH':
        pushnum = int(op[4:])
        compustate.pc = oldpc + 1 + pushnum
        dat = code[oldpc + 1: oldpc + 1 + pushnum]
        stk.append(utils.big_endian_to_int(dat))
    elif op == 'CREATE':
        if len(mem) < ceil32(stackargs[1] + stackargs[2]):
            mem.extend([0] * (ceil32(stackargs[1] + stackargs[2]) - len(mem)))
        value = stackargs[0]
        data = ''.join(map(chr, mem[stackargs[1]:stackargs[1] + stackargs[2]]))
        logger_debug("Sub-contract: %s %s %s ", msg.to, value, data)
        addr, gas, code = create_contract(
            block, tx, Message(msg.to, '', value, compustate.gas, data))
        logger_debug("Output of contract creation: %s  %s ", addr, code)
        if addr:
            stk.append(utils.coerce_to_int(addr))
            compustate.gas = gas
        else:
            stk.append(0)
            compustate.gas = 0
    elif op == 'CALL':
        if len(mem) < ceil32(stackargs[3] + stackargs[4]):
            mem.extend([0] * (ceil32(stackargs[3] + stackargs[4]) - len(mem)))
        if len(mem) < ceil32(stackargs[5] + stackargs[6]):
            mem.extend([0] * (ceil32(stackargs[5] + stackargs[6]) - len(mem)))
        gas = stackargs[0]
        to = utils.encode_int(stackargs[1])
        to = (('\x00' * (32 - len(to))) + to)[12:]
        value = stackargs[2]
        data = ''.join(map(chr, mem[stackargs[3]:stackargs[3] + stackargs[4]]))
        logger_debug(
            "Sub-call: %s %s %s %s %s ", utils.coerce_addr_to_hex(msg.to),
            utils.coerce_addr_to_hex(to), value, gas, data.encode('hex'))
        result, gas, data = apply_msg(
            block, tx, Message(msg.to, to, value, gas, data))
        logger_debug(
            "Output of sub-call: %s %s length %s expected %s", result, data, len(data),
            stackargs[6])
        for i in range(stackargs[6]):
            mem[stackargs[5] + i] = 0
        if result == 0:
            stk.append(0)
        else:
            stk.append(1)
            compustate.gas += gas
            for i in range(len(data)):
                mem[stackargs[5] + i] = data[i]
    elif op == 'RETURN':
        if len(mem) < ceil32(stackargs[0] + stackargs[1]):
            mem.extend([0] * (ceil32(stackargs[0] + stackargs[1]) - len(mem)))
        return mem[stackargs[0]:stackargs[0] + stackargs[1]]
    elif op == 'SUICIDE':
        to = utils.encode_int(stackargs[0])
        to = (('\x00' * (32 - len(to))) + to)[12:]
        block.transfer_value(msg.to, to, block.get_balance(msg.to))
        block.suicides.append(msg.to)
        return []
