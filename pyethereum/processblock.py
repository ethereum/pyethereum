from transactions import Transaction
from blocks import Block
from trie import Trie, DB
import time
import sys
import rlp
import math
from opcodes import opcodes

from utils import big_endian_to_int as decode_int
from utils import int_to_big_endian as encode_int
from utils import sha3, privtoaddr

statedb = DB('statedb')

def encoded_plus(a,b):
    return encode_int(decode_int(a) + decode_int(b))

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

OUT_OF_GAS = -1

def process(block,txs):
    for tx in txs:
        apply_tx(block,tx)
    finalize(block)

def finalize(block):
    block.delta_balance(block.coinbase,block.reward)

class Message(object):
    def __init__(self,sender,to,value,gas,data):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data

def apply_tx(block,tx):
    if block.get_nonce(tx.sender) != tx.nonce:
        raise Exception("Invalid nonce!")
    o = block.delta_balance(tx.sender,-tx.gasprice * tx.startgas)
    if not o:
        raise Exception("Insufficient balance to pay fee!")
    block.increment_nonce(tx.sender)
    snapshot = block.snapshot()
    message_gas = tx.startgas - GTXDATA * len(tx.data)
    message = Message(tx.sender,tx.to,tx.value,message_gas,tx.data)
    if tx.to:
        s,g,d = apply_msg(block,tx,message)
    else:
        s,g = create_contract(block,tx,message)
    if not s:
        block.revert(snapshot)
        block.gas_consumed += tx.startgas
        block.delta_balance(block.coinbase,fee)
    else:
        block.delta_balance(tx.sender,tx.gasprice * g)
        block.delta_balance(block.coinbase,tx.gasprice * (tx.startgas - g))
        block.gas_consumed += tx.startgas - g

class Compustate():
    def __init__(self,**kwargs):
        self.memory = []
        self.stack = []
        self.pc = 0
        self.gas = 0
        for kw in kwargs:
            vars(self)[kw] = kwargs[kw]

def apply_msg(block,tx,msg):
    snapshot = block.snapshot()
    code = statedb.get(block.get_code(msg.sender))
    # Transfer value, instaquit if not enough
    block.delta_balance(msg.to,msg.value)
    o = block.delta_balance(msg.sender,-msg.value)
    if not o:
        return 0, msg.gas, []
    compustate = Compustate(gas=msg.gas)
    # Main loop
    while 1:
        o = apply_op(block,tx,msg,code,compustate)
        if o is not None:
            if o == OUT_OF_GAS:
                block.revert(snapshot)
                return 0, 0, []
            else:
                return 1, compustate.gas, o

def create_contract(block,tx,msg):
    snapshot = block.snapshot()
    sender = msg.sender.decode('hex') if len(msg.sender) == 40 else msg.sender
    nonce = encode_int(block.get_nonce(msg.sender))
    recvaddr = sha3(rlp.encode([sender,nonce]))
    code = msg.data
    # Transfer value, instaquit if not enough
    block.delta_balance(recvaddr,msg.value)
    o = block.delta_balance(msg.sender,msg.value)
    if not o:
        return 0, msg.gas
    block.set_code(recvaddr,msg.data)
    compustate = Compustate(gas=msg.gas)
    # Temporary pre-POC5: don't do the code/init thing
    return recvaddr, compustate.gas
    # Main loop
    while 1:
        o = apply_op(block,tx,msg,msg.data,compustate.op)
        if o is not None:
            if o == OUT_OF_GAS:
                block.state.root = oldroot
                return 0, 0
            else:
                block.set_code(''.join(map(chr,o)))
                return recvaddr, compustate.gas
    
def get_op_data(code,index):
    opcode = ord(code[index]) if index < len(code) else 0
    if opcode < 96 or opcode == 255:
        if opcode in opcodes: return opcodes[opcode]
        else: return 'INVALID'
    elif opcode < 128: return 'PUSH'+str(opcode-95)
    else: return 'INVALID'

def calcfee(block,tx,msg,compustate,op):
    stk, mem = compustate.stack, compustate.memory
    if op == 'SHA3':
        m_extend = max(0,stk[-1] + stk[-2] - len(mem))
        return GSHA3 + m_extend * GMEMORY
    elif op == 'SLOAD':
        return GSLOAD
    elif op == 'SSTORE':
        return GSSTORE
    elif op == 'MLOAD':
        m_extend = max(0,stk[-1] + 32 - len(mem))
        return GSTEP + m_extend * GMEMORY
    elif op == 'MSTORE':
        m_extend = max(0,stk[-1] + 32 - len(mem))
        return GSTEP + m_extend * GMEMORY
    elif op == 'MSTORE8':
        m_extend = max(0,stk[-1] + 1 - len(mem))
        return GSTEP + m_extend * GMEMORY
    elif op == 'CALL':
        m_extend = max(0,stk[-3]+stk[-4]-len(mem), stk[-5]+stk[-6]-len(mem))
        return GCALL + stk[-2] + m_extend * GMEMORY
    elif op == 'CREATE':
        m_extend = max(0,stk[-2]+stk[-3]-len(mem))
        return GCREATE + stk[-2] + m_extend * GMEMORY
    else:
        return GSTEP

# multi pop
def multipop(stack,pops):
    o = []
    for i in range(pops): o.push(stack.pop())
    return o

# Does not include paying opfee
def apply_op(block,tx,msg,code,compustate):
    op, in_args, out_args = get_op_data(code,compustate.pc)
    # empty stack error
    if in_args > len(compustate.stack):
        return []
    stackargs = []
    for i in range(in_args):
        stackargs.push(stack.pop())
    # out of gas error
    fee = calcfee(block,tx,msg,compustate,op)
    if fee > compustate.gas:
        return OUT_OF_GAS
    # Apply operation
    newgas = compustate.gas - fee
    newpc = compustate.pc + 1
    stk = compustate.stack
    mem = compustate.memory
    if op == 'ADD':
        stk.push((stackargs[0] + stackargs[1]) % 2**256)
    elif op == 'SUB':
        stk.push((stackargs[0] - stackargs[1]) % 2**256)
    elif op == 'MUL':
        stk.push((stackargs[0] * stackargs[1]) % 2**256)
    elif op == 'DIV':
        stk.push(stackargs[0] / stackargs[1])
    elif op == 'MOD':
        stk.push(stackargs[0] % stackargs[1])
    elif op == 'SDIV':
        if stackargs[0] >= 2**255: stackargs[0] -= 2**256
        if stackargs[1] >= 2**255: stackargs[1] -= 2**256
        stk.push((stackargs[0] / stackargs[1]) % 2**256)
    elif op == 'SMOD':
        if stackargs[0] >= 2**255: stackargs[0] -= 2**256
        if stackargs[1] >= 2**255: stackargs[1] -= 2**256
        stk.push((stackargs[0] % stackargs[1]) % 2**256)
    elif op == 'EXP':
        stk.push(pow(stackargs[0],stackargs[1],2**256))
    elif op == 'NEG':
        stk.push(2**256 - stackargs[0])
    elif op == 'LT':
        stk.push(1 if stackargs[0] < stackargs[1] else 0)
    elif op == 'GT':
        stk.push(1 if stackargs[0] > stackargs[1] else 0)
    elif op == 'EQ':
        stk.push(1 if stackargs[0] == stackargs[1] else 0)
    elif op == 'NOT':
        stk.push(0 if stackargs[0] else 1)
    elif op == 'AND':
        stk.push(stackargs[0] & stackargs[1])
    elif op == 'OR':
        stk.push(stackargs[0] | stackargs[1])
    elif op == 'XOR':
        stk.push(stackargs[0] ^ stackargs[1])
    elif op == 'BYTE':
        if stackargs[0] >= 32: stk.push(0)
        else: stk.push((stackargs[1] / 256**stackargs[0]) % 256)
    elif op == 'SHA3':
        if len(mem) < stackargs[0] + stackargs[1]:
            mem.extend([0] * (stackargs[0] + stackargs[1] - len(mem)))
        data = ''.join(map(chr,mem[stackargs[0]:stackargs[0] + stackargs[1]]))
        stk.push(decode(sha3(data),256))
    elif op == 'ADDRESS':
        stk.push(msg.to)
    elif op == 'BALANCE':
        stk.push(block.get_balance(msg.to))
    elif op == 'ORIGIN':
        stk.push(tx.sender)
    elif op == 'CALLER':
        stk.push(msg.sender)
    elif op == 'CALLVALUE':
        stk.push(msg.value)
    elif op == 'CALLDATA':
        if stackargs[-1] >= len(msg.data): stk.push(0)
        else:
            dat = ''.join(map(chr,msg.data[stackargs[-1]:stackargs[-1]+32]))
            stk.push(decode(dat+'\x00'*(32-len(dat)),256))
    elif op == 'CALLDATASIZE':
        stk.push(len(msg.data))
    elif op == 'GASPRICE':
        stk.push(tx.gasprice)
    elif op == 'PREVHASH':
        stk.push(block.prevhash)
    elif op == 'COINBASE':
        stk.push(block.coinbase)
    elif op == 'TIMESTAMP':
        stk.push(block.timestamp)
    elif op == 'NUMBER':
        stk.push(block.number)
    elif op == 'DIFFICULTY':
        stk.push(block.difficulty)
    elif op == 'GASLIMIT':
        stk.push(block.gaslimit)
    elif op == 'POP':
        pass
    elif op == 'DUP':
        stk.push(stackargs[0])
        stk.push(stackargs[0])
    elif op == 'SWAP':
        stk.push(stackargs[0])
        stk.push(stackargs[1])
    elif op == 'MLOAD':
        if len(mem) < stackargs[0] + 32:
            mem.extend([0] * (stackargs[0] + 32 - len(mem)))
        data = ''.join(map(chr,mem[stackargs[0]:stackargs[0] + 32]))
        stk.push(decode(data,256))
    elif op == 'MSTORE':
        if len(mem) < stackargs[0] + 32:
            mem.extend([0] * (stackargs[0] + 32 - len(mem)))
        v = stackargs[1]
        for i in range(31,-1,-1):
            mem[stackargs[0]+i] = v % 256
            v /= 256
    elif op == 'MSTORE8':
        if len(mem) < stackargs[0] + 1:
            mem.extend([0] * (stackargs[0] + 1 - len(mem)))
        mem[stackargs[0]] = stackargs[1] % 256
    elif op == 'SLOAD':
        stk.push(block.get_storage_data(msg.to,stackargs[0]))
    elif op == 'SSTORE':
        block.set_storage_data(msg.to,stackargs[0],stackargs[1])
    elif op == 'JUMP':
        newpc = stackargs[0]
    elif op == 'JUMPI':
        if stackargs[1]: newpc = stackargs[0]
    elif op == 'PC':
        stk.push(compustate.pc)
    elif op == 'MSIZE':
        stk.push(len(mem))
    elif op == 'GAS':
        stk.push(compustate.gas)
    elif op[:4] == 'PUSH':
        pushnum = int(op[4:])
        newpc = compustate.pc + 1 + pushnum
        dat = code[compustate.pc + 1: compustate.pc + 1 + pushnum]
        stk.push(decode(dat+'\x00'*(32-len(dat)),256))
    elif op == 'CREATE':
        if len(mem) < stackargs[2] + stackargs[3]:
            mem.extend([0] * (stackargs[2] + stackargs[3] - len(mem)))
        value = stackhash[0]
        gas = stackhash[1]
        data = ''.join(map(chr,mem[stackhash[2]:stackhash[2]+stackhash[3]]))
        create_contract(block,tx,Message(msg.to,'',value,gas,data))
    elif op == 'CALL':
        if len(mem) < stackargs[3] + stackargs[4]:
            mem.extend([0] * (stackargs[3] + stackargs[4] - len(mem)))
        if len(mem) < stackargs[5] + stackargs[6]:
            mem.extend([0] * (stackargs[5] + stackargs[6] - len(mem)))
        to = stackhash[0]
        value = stackhash[1]
        gas = stackhash[2]
        data = ''.join(map(chr,mem[stackhash[3]:stackhash[3]+stackhash[4]]))
        apply_msg(block,tx,Message(msg.to,to,value,gas,data))
