import rlp
from opcodes import opcodes

from utils import big_endian_to_int as decode_int
from utils import int_to_big_endian as encode_int
from utils import sha3
import utils
import time
import blocks
import transactions


debug = 0

# params

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


def process(block, txs):
    for tx in txs:
        apply_tx(block, tx)
    finalize(block)


def finalize(block):
    block.delta_balance(block.coinbase, block.reward)


def verify(block, parent):
    assert block.timestamp >= parent.timestamp
    assert block.timestamp <= time.time() + 900
    block2 = blocks.init_from_parent(parent,
                                     block.coinbase,
                                     block.extra_data,
                                     block.timestamp)
    assert block2.difficulty == block.difficulty
    assert block2.gas_limit == block.gas_limit
    for i in range(block.transaction_count):
        tx, s, g = block.transactions.get(utils.encode_int(i))
        tx = transactions.Transaction.deserialize(tx)
        assert tx.startgas + block2.gas_used <= block.gas_limit
        block2.apply_tx(tx)
        assert s == block2.state.root
        assert g == utils.encode_int(block2.gas_used)
    finalize(block2)
    assert block2.state.root == block.state.root
    assert block2.gas_consumed == block.gas_consumed
    return True


class Message(object):

    def __init__(self, sender, to, value, gas, data):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data


def apply_tx(block, tx):
    if not tx.sender:
        raise Exception("Trying to apply unsigned transaction!")
    acctnonce = block.get_nonce(tx.sender)
    if acctnonce != tx.nonce:
        raise Exception("Invalid nonce! Sender %s tx %s" %
                        (acctnonce, tx.nonce))
    o = block.delta_balance(tx.sender, -tx.gasprice * tx.startgas)
    if not o:
        raise Exception("Insufficient balance to pay fee!")
    block.increment_nonce(tx.sender)
    snapshot = block.snapshot()
    message_gas = tx.startgas - GTXDATA * len(tx.serialize()) - GTXCOST
    message = Message(tx.sender, tx.to, tx.value, message_gas, tx.data)
    if tx.to:
        result, gas, data = apply_msg(block, tx, message)
    else:
        result, gas = create_contract(block, tx, message)
    if not result:  # 0 = OOG failure in both cases
        block.revert(snapshot)
        block.gas_used += tx.startgas
        block.delta_balance(block.coinbase, tx.gasprice * tx.startgas)
        output = OUT_OF_GAS
    else:
        block.delta_balance(tx.sender, tx.gasprice * gas)
        block.delta_balance(block.coinbase, tx.gasprice * (tx.startgas - gas))
        block.gas_used += tx.startgas - gas
        output = ''.join(map(chr, data)) if tx.to else result.encode('hex')
    tx_data = [tx.serialize(), block.state.root, encode_int(block.gas_used)]
    block.add_transaction_to_list(tx_data)
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
        o.append(decode_int(arr[i:i + 32]))
    return o


def apply_msg(block, tx, msg):
    snapshot = block.snapshot()
    code = block.get_code(msg.to)
    # Transfer value, instaquit if not enough
    block.delta_balance(msg.to, msg.value)
    o = block.delta_balance(msg.sender, -msg.value)
    if not o:
        return 0, msg.gas, []
    compustate = Compustate(gas=msg.gas)
    # Main loop
    while 1:
        if debug:
            print({
                "Stack": compustate.stack,
                "PC": compustate.pc,
                "Gas": compustate.gas,
                "Memory": decode_datalist(compustate.memory),
                "Storage": block.get_storage(msg.to).to_dict(),
            })
        o = apply_op(block, tx, msg, code, compustate)
        if o is not None:
            if debug:
                print('done', o)
            if o == OUT_OF_GAS:
                block.revert(snapshot)
                return 0, 0, []
            else:
                return 1, compustate.gas, o


def create_contract(block, tx, msg):
    snapshot = block.snapshot()
    sender = msg.sender.decode('hex') if len(msg.sender) == 40 else msg.sender
    nonce = encode_int(block.get_nonce(msg.sender))
    recvaddr = sha3(rlp.encode([sender, nonce]))[12:]
    # Transfer value, instaquit if not enough
    block.delta_balance(recvaddr, msg.value)
    o = block.delta_balance(msg.sender, msg.value)
    if not o:
        return 0, msg.gas
    block.set_code(recvaddr, msg.data)
    compustate = Compustate(gas=msg.gas)
    # Main loop
    while 1:
        o = apply_op(block, tx, msg, msg.data, compustate)
        if o is not None:
            if o == OUT_OF_GAS:
                block.revert(snapshot)
                return 0, 0
            else:
                block.set_code(recvaddr, ''.join(map(chr, o)))
                return recvaddr, compustate.gas


def get_op_data(code, index):
    opcode = ord(code[index]) if index < len(code) else 0
    if opcode < 96 or (opcode > 240 and opcode <= 255):
        if opcode in opcodes:
            return opcodes[opcode]
        else:
            return 'INVALID', 0, 0
    elif opcode < 128:
        return 'PUSH' + str(opcode - 95), 0, 1
    else:
        return 'INVALID', 0, 0


def calcfee(block, tx, msg, compustate, op):
    stk, mem = compustate.stack, compustate.memory
    if op == 'SHA3':
        m_extend = max(0, stk[-1] + stk[-2] - len(mem))
        return GSHA3 + m_extend * GMEMORY
    elif op == 'SLOAD':
        return GSLOAD
    elif op == 'SSTORE':
        return GSSTORE
    elif op == 'MLOAD':
        m_extend = max(0, stk[-1] + 32 - len(mem))
        return GSTEP + m_extend * GMEMORY
    elif op == 'MSTORE':
        m_extend = max(0, stk[-1] + 32 - len(mem))
        return GSTEP + m_extend * GMEMORY
    elif op == 'MSTORE8':
        m_extend = max(0, stk[-1] + 1 - len(mem))
        return GSTEP + m_extend * GMEMORY
    elif op == 'CALL':
        m_extend = max(
            0, stk[-4] + stk[-5] - len(mem), stk[-6] + stk[-7] - len(mem))
        return GCALL + stk[-1] + m_extend * GMEMORY
    elif op == 'CREATE':
        m_extend = max(0, stk[-3] + stk[-4] - len(mem))
        return GCREATE + stk[-2] + m_extend * GMEMORY
    elif op == 'RETURN':
        m_extend = max(0, stk[-1] + stk[-2] - len(mem))
        return GSTEP + m_extend * GMEMORY
    elif op == 'CALLDATACOPY':
        m_extend = max(0, stk[-1] + stk[-3] - len(mem))
        return GSTEP + m_extend * GMEMORY
    elif op == 'STOP' or op == 'INVALID':
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
        if debug:
            print("Out of gas", compustate.gas, "need", fee)
            print(op, list(reversed(compustate.stack)))
        return OUT_OF_GAS
    stackargs = []
    for i in range(in_args):
        stackargs.append(compustate.stack.pop())
    if debug:
        import serpent
        if op[:4] == 'PUSH':
            start, n = compustate.pc + 1, int(op[4:])
            print(op, decode_int(code[start:start + n]))
        else:
            print(op, ' '.join(map(str, stackargs)),
                  serpent.decode_datalist(compustate.memory))
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
        if len(mem) < stackargs[0] + stackargs[1]:
            mem.extend([0] * (stackargs[0] + stackargs[1] - len(mem)))
        data = ''.join(map(chr, mem[stackargs[0]:stackargs[0] + stackargs[1]]))
        stk.append(rlp.decode(sha3(data), 256))
    elif op == 'ADDRESS':
        stk.append(msg.to)
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
            stk.append(decode_int(dat + '\x00' * (32 - len(dat))))
    elif op == 'CALLDATASIZE':
        stk.append(len(msg.data))
    elif op == 'CALLDATACOPY':
        if len(mem) < stackargs[0] + stackargs[2]:
            mem.extend([0] * (stackargs[0] + stackargs[2] - len(mem)))
        for i in range(stackargs[2]):
            if stackargs[0] + i < len(msg.data):
                mem[stackargs[1] + i] = ord(msg.data[stackargs[0] + i])
            else:
                mem[stackargs[1] + i] = 0
    elif op == 'GASPRICE':
        stk.append(tx.gasprice)
    elif op == 'PREVHASH':
        stk.append(decode_int(block.prevhash))
    elif op == 'COINBASE':
        stk.append(decode_int(block.coinbase.decode('hex')))
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
        stk.append(stackargs[0])
        stk.append(stackargs[0])
    elif op == 'SWAP':
        stk.append(stackargs[0])
        stk.append(stackargs[1])
    elif op == 'MLOAD':
        if len(mem) < stackargs[0] + 32:
            mem.extend([0] * (stackargs[0] + 32 - len(mem)))
        data = ''.join(map(chr, mem[stackargs[0]:stackargs[0] + 32]))
        stk.append(decode_int(data))
    elif op == 'MSTORE':
        if len(mem) < stackargs[0] + 32:
            mem.extend([0] * (stackargs[0] + 32 - len(mem)))
        v = stackargs[1]
        for i in range(31, -1, -1):
            mem[stackargs[0] + i] = v % 256
            v /= 256
    elif op == 'MSTORE8':
        if len(mem) < stackargs[0] + 1:
            mem.extend([0] * (stackargs[0] + 1 - len(mem)))
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
        stk.append(decode_int(dat))
    elif op == 'CREATE':
        if len(mem) < stackargs[2] + stackargs[3]:
            mem.extend([0] * (stackargs[2] + stackargs[3] - len(mem)))
        gas = stackargs[0]
        value = stackargs[1]
        data = ''.join(map(chr, mem[stackargs[2]:stackargs[2] + stackargs[3]]))
        if debug:
            print("Sub-contract:", msg.to, value, gas, data)
        create_contract(block, tx, Message(msg.to, '', value, gas, data))
    elif op == 'CALL':
        if len(mem) < stackargs[3] + stackargs[4]:
            mem.extend([0] * (stackargs[3] + stackargs[4] - len(mem)))
        if len(mem) < stackargs[5] + stackargs[6]:
            mem.extend([0] * (stackargs[5] + stackargs[6] - len(mem)))
        gas = stackargs[0]
        to = encode_int(stackargs[1])
        to = (('\x00' * (32 - len(to))) + to)[12:]
        value = stackargs[2]
        data = ''.join(map(chr, mem[stackargs[3]:stackargs[3] + stackargs[4]]))
        if debug:
            print("Sub-call:", utils.coerce_addr_to_hex(msg.to),
                  utils.coerce_addr_to_hex(to), value, gas, data)
        result, gas, data = apply_msg(
            block, tx, Message(msg.to, to, value, gas, data))
        if debug:
            print("Output of sub-call:", result, data, "length", len(data),
                  "expected", stackargs[6])
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
        if len(mem) < stackargs[0] + stackargs[1]:
            mem.extend([0] * (stackargs[0] + stackargs[1] - len(mem)))
        return mem[stackargs[0]:stackargs[0] + stackargs[1]]
    elif op == 'SUICIDE':
        to = encode_int(stackargs[0])
        to = (('\x00' * (32 - len(to))) + to)[12:]
        block.delta_balance(to, block.get_balance(msg.to))
        block.state.update(msg.to, '')
        return []
