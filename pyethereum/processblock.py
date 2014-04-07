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

NONCE_INDEX = 0
BALANCE_INDEX = 1
CODE_INDEX = 2
STORAGE_INDEX = 3

OUT_OF_GAS = -1

def process(block,txs):
    for tx in txs:
        apply_tx(block,tx)
    finalize(block)

def finalize(block):
    minerstate = block.state.get(block.coinbase) or ['','','','']
    minerstate[BALANCE_INDEX] \
        = encode_int(decode_int(minerstate[BALANCE_INDEX]) + block.reward)
    block.state.update(block.coinbase,minerstate)

class Message(object):
    def __init__(self,sender,to,value,gas,data):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data

def apply_tx(block,tx):
    fee = tx.gasprice * tx.startgas
    addrstate = block.state.get(tx.sender.decode('hex'))
    if not addrstate:
        raise Exception("Sending from a not-yet-existent account!")
    if decode_int(addrstate[NONCE_INDEX]) != tx.nonce:
        print decode_int(addrstate[NONCE_INDEX]), tx.nonce
        raise Exception("Invalid nonce!")
    if decode_int(addrstate[BALANCE_INDEX]) < fee:
        raise Exception("Not enough in account to pay fee!")
    addrstate[NONCE_INDEX] = encode_int(decode_int(addrstate[NONCE_INDEX])+1)
    addrstate[BALANCE_INDEX] = encode_int(decode_int(addrstate[BALANCE_INDEX])-fee)
    block.state.update(tx.sender.decode('hex'),addrstate)
    block.gas_consumed += fee
    medroot = block.state.root
    message_gas = tx.startgas - GTXDATA * len(tx.data)
    message = Message(tx.sender,tx.to,tx.value,message_gas,tx.data)
    if tx.to:
        s,g,d = apply_msg(block,tx,message)
    else:
        s,g = create_contract(block,tx,message)
    if not s:
        block.state.root = medroot
        minerstate = block.state.get(block.coinbase)
        minerstate[BALANCE_INDEX] = encode_int(decode_int(minerstate[BALANCE_INDEX])+fee)
        block.state.update(block.coinbase,minerstate)
    else:
        addrstate[BALANCE_INDEX] = encode_int(decode_int(addrstate[BALANCE_INDEX])+tx.gasprice * g)
        block.state.update(tx.sender.decode('hex'),addrstate)
        minerstate = block.state.get(block.coinbase.decode('hex')) or ['','','','']
        minerstate[BALANCE_INDEX] = encode_int(decode_int(minerstate[BALANCE_INDEX])+(fee - g * tx.gasprice))
        block.state.update(block.coinbase.decode('hex'),minerstate)

class Compustate():
    def __init__(self,**kwargs):
        self.memory = []
        self.stack = []
        self.pc = 0
        self.gas = 0
        for kw in kwargs:
            vars(self)[kw] = kwargs[kw]

def apply_msg(block,tx,msg):
    oldroot = block.state.root
    senderstate = block.state.get(msg.sender)
    recvstate = block.state.get(msg.to) or ['','','','']
    codehash = recvstate[CODE_INDEX]
    code = statedb.get(codehash)
    compustate = Compustate(gas=msg.gas)
    # Not enough value to send, instaquit
    if decode_int(senderstate[BALANCE_INDEX]) < msg.value:
        return 1, compustate.gas, []
    # Transfer value
    senderstate[BALANCE_INDEX] = encode_int(decode_int(senderstate[BALANCE_INDEX]) - msg.value)
    recvstate[BALANCE_INDEX] = encode_int(decode_int(senderstate[BALANCE_INDEX]) + msg.value)
    block.state.update(msg.sender,senderstate)
    block.state.update(msg.to,recvstate)
    # Main loop
    while 1:
        o = apply_op(block,tx,msg,code,compustate,op)
        if o is not None:
            if o == OUT_OF_GAS:
                block.state.root = oldroot
                return 0, 0, []
            else:
                return 1, compustate.gas, o

def create_contract(block,tx,msg):
    oldroot = block.state.root
    senderstate = block.state.get(msg.sender) or ['','','','']
    recvstate = ['','',sha3(msg.data),'']
    recvaddr = sha3(rlp.encode([msg.sender,senderstate[NONCE_INDEX]]))[12:]
    code = msg.data
    statedb.put(sha3(msg.data),msg.data)
    compustate = Compustate(gas=msg.gas)
    # Not enough vaue to send, instaquit
    if decode_int(senderstate[BALANCE_INDEX]) < msg.value:
        recvstate[2] = []
        block.state.update(recvaddr,recvstate)
        return recvaddr, compustate.gas
    # Transfer value and update nonce
    senderstate[BALANCE_INDEX] = encode_int(decode_int(senderstate[BALANCE_INDEX])-msg.value)
    senderstate[NONCE_INDEX] = encode_int(decode_int(senderstate[NONCE_INDEX])+1)
    recvstate[BALANCE_INDEX] = encode_int(decode_int(senderstate[BALANCE_INDEX])+msg.value)
    block.state.update(msg.sender.decode('hex'),senderstate)
    block.state.update(recvaddr,recvstate)
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
                recvstate = block.state.get(recvaddr)
                recvstate[CODE_INDEX] = sha3(map(chr,o))
                statedb.put(sha3(map(chr,o)),map(chr,o))
                block.state.update(recvaddr,recvstate)
                return recvaddr, recvstate
    
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
def apply_op(block,tx,msg,code,compustate,op):
    op_data = get_op_data(code,compustate.pc)
    # empty stack error
    if op_data[1] > len(compustate.stack):
        return []
    stackargs = []
    for i in range(op.data[1]):
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
        stk.push(block.state.get(msg.to)[BALANCE_INDEX])
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
        trie = Trie(block.state.get(msg.to)[STORAGE_INDEX],'statedb')
        stk.push(trie.get(stackargs[0]))
    elif op == 'SSTORE':
        mystate = block.state.get(msg.to)
        trie = Trie(mystate[STORAGE_INDEX],'statedb')
        trie.update(stackargs[0],stackargs[1])
        mystate[STORAGE_INDEX] = trie.root
        block.state.update(msg.to,mystate)
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
