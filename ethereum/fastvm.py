from ethereum.opcodes import opcodes
from ethereum import utils
from ethereum.utils import safe_ord
import serpent
import rlp
from rlp.utils import decode_hex, encode_hex, ascii_chr
import copy

code_cache = {}
OUT_OF_GAS = -1

GDEFAULT = 1
GMEMORY = 1
GSTORAGE = 100
GTXDATA = 5
GTXCOST = 500
TT255 = 2 ** 255
TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1
TT160 = 2 ** 160
TT160M1 = 2 ** 160 - 1


# Converts an unsigned value to a signed value
def to_signed(i):
    return i if i < TT255 else i - TT256


# Given a bytearray stored as a list of 32-byte values, extracts
# bytes start...start+sz-1 as an ordinary bytearray
def extract_bytes(mem, start, sz):
    end = start + sz
    sminor, smajor = start & 31, start >> 5
    eminor, emajor = end & 31, end >> 5
    if not sz:
        return []
    elif smajor == emajor:
        m = mem[smajor]
        o = utils.int_to_32bytearray(m)[sminor: eminor]
    else:
        m = utils.int_to_32bytearray(mem[smajor])[sminor:]
        for i in range((smajor) + 1, emajor):
            m.extend(utils.int_to_32bytearray(mem[i]))
        if eminor:
            m.extend(utils.int_to_32bytearray(mem[emajor])[:eminor])
        o = m
    return o


# Given a bytearray stored as a list of 32-byte values, sets the
# bytes starting at the given starting location to equal the given
# normal bytearray
def set_bytes(mem, start, bytez):
    end = start + len(bytez)
    sminor, smajor = start & 31, start >> 5
    eminor, emajor = end & 31, end >> 5
    if not bytez:
        pass
    elif (smajor) == (emajor):
        m = utils.int_to_32bytearray(mem[smajor])
        mem[smajor] = utils.bytearray_to_int(m[:sminor] + bytez + m[eminor:])
    else:
        if sminor:
            m = utils.int_to_32bytearray(mem[smajor])
            mem[smajor] = utils.bytearray_to_int(m[:sminor] + bytez[:32 - (sminor)])
        else:
            mem[smajor] = utils.bytearray_to_int(bytez[:32])
        j = 0
        for i in range((smajor) + 1, emajor):
            mem[i] = utils.bytearray_to_int(bytez[j + 32 - (sminor): j + 64 - (sminor)])
            j += 32
        if eminor:
            m2 = utils.int_to_32bytearray(mem[emajor])
            endpiece = bytez[j + 32 - (sminor):]
            mem[emajor] = utils.bytearray_to_int(endpiece + m2[-32 + len(endpiece):])


# Copies bytes start1....start1+l-1 of bytearray mem1 to bytes
# start2...start2+l-1 of bytearray mem2 (both bytearrays stored as 32-byte
# values)
def copy32(mem1, mem2, start1, start2, l):
    major1 = start1 >> 5
    major2 = start2 >> 5
    offset1 = start1 % 32
    offset2 = start2 % 32
    for i in range(l >> 5):
        if not offset1:
            L = mem1[major1 + i]
        else:
            L = ((mem1[major1 + i] << (8 * offset1)) & TT256M1) + \
                (mem1[major1 + i + 1] >> (256 - 8 * offset1))

        if not offset2:
            mem2[major2 + i] = L
        else:
            mem2[major2 + i] = (mem2[major2 + i] &
                                (TT256 - (TT256 >> (8 * offset2)))) + (L >> (8 * offset2))
            mem2[major2 + i + 1] = (mem2[major2 + i + 1] & ((TT256 >> (8 * offset2)) - 1)) + \
                ((L << (256 - 8 * offset2)) & TT256M1)

    if l % 32:
        b = extract_bytes(mem1, start1 + l - l % 32, l % 32)
        set_bytes(mem2, start2 + l - l % 32, b)


# Given a byte array, returns the integer value from the 32 bytes
# starting at the given index
def load32(mem, byte):
    if not byte % 32:
        return mem[byte >> 5]
    else:
        return ((mem[byte >> 5] << (8 * (byte % 32))) & TT256M1) + (mem[byte >> 5 + 1] >> (256 - 8 * (byte % 32)))


# Converts a bytearray to a bytearray stored as 32 byte words
def bytearray_to_32s(b):
    b += [0] * 32
    o = []
    for i in range(0, len(b), 32):
        o.append(utils.bytearray_to_int(b[i:i + 32]))
    return o


# Extends the length of a memory array
def mem_extend(mem, compustate, op, start, sz):
    if sz:
        newsize = ((start + sz) + 33 - ((start + sz - 1) & 31)) >> 5
        if len(mem) < newsize:
            m_extend = newsize - len(mem)
            memfee = GMEMORY * m_extend
            if compustate.gas < memfee:
                out_of_gas_exception('mem_extend', memfee, compustate, op)
                compustate.gas = 0
                return False
            compustate.gas -= memfee
            mem.extend([0] * m_extend)
    return True


# An object encompassing the current computational state
# longterm todo: combine this into the message object?
class Compustate():

    def __init__(self, **kwargs):
        self.memory = []
        self.stack = []
        self.pc = 0
        self.gas = 0
        for kw in kwargs:
            setattr(self, kw, kwargs[kw])


# Message
class Message(object):

    def __init__(self, sender, to, value, gas, data, databytes):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        # data stored as 32-byte word array
        self.data = data
        # length of data as exact byte count
        self.databytes = databytes
        self.processed_code = []
        # function to cal when the message execution returns/exits
        self.callback = lambda x, y, z: x
        # snapshot to revert to if execution is reverted due to oog
        self.snapshot = None
        self.compustate = None

    def __repr__(self):
        return '<Message(to:%s...)>' % self.to[:8]


def out_of_gas_exception(expense, fee, compustate, op):
    return OUT_OF_GAS


filter1 = set(['JUMP', 'JUMPI', 'JUMPDEST', 'STOP', 'RETURN',
               'INVALID', 'CALL', 'CREATE', 'CALLCODE', 'SUICIDE'])


# "compiles" virtual machine code into a format consisting of a map between
# starting coordinates and "chunks" of code from that starting coordinate
# to the next control point (control points defined by filter1 above). Also
# calculates stack requirements and gas costs for each chunk all together
def preprocess_vmcode(code):
    o = []
    jumps = {}
    # Round 1: Locate all JUMP, JUMPI, JUMPDEST, STOP, RETURN, INVALID locs
    opcodez = copy.deepcopy([opcodes.get(safe_ord(c), ['INVALID', 0, 0, 1]) +
                             [safe_ord(c)] for c in code])
    for i, o in enumerate(opcodez):
        if o[0] in filter1:
            jumps[i] = True

    chunks = {}
    chunks["code"] = [safe_ord(x) for x in code]
    c = []
    h, reqh, gascost = 0, 0, 0
    i = 0
    laststart, lastjumpable = 0, 0
    while i < len(opcodez):
        o = opcodez[i]  # [op, ins, outs, gas, opcode, pos, push?]
        o.append(laststart + i)
        c.append(o)
        reqh = max(reqh, h + o[1])
        h += o[1] - o[2]
        gascost += o[3]
        if i in jumps:
            chunks[laststart] = {"reqh": reqh, "deltah": -h,
                                 "gascost": gascost, "opdata": c,
                                 "ops": list(enumerate([x[4] for x in c])),
                                 "start": laststart, "jumpable": lastjumpable,
                                 "end": i + 1}
            c = []
            laststart = i + 1
            lastjumpable = 1 if o[0] == 'JUMPDEST' else 0
            h, reqh, gascost = 0, 0, 0
        if 0x60 <= o[4] < 0x80:
            v = 0
            for j in range(i + 1, i + o[4] - 0x5e):
                v = (v << 8) + opcodez[j][4]
            o.append(v)
            i += o[4] - 0x5f
        i += 1
    chunks[laststart] = {"reqh": reqh, "deltah": -h,
                         "gascost": gascost, "opdata": c,
                         "ops": list(enumerate([x[4] for x in c])),
                         "start": laststart, "jumpable": lastjumpable,
                         "end": i + 1}
    return chunks


# Main function, drop-in replacement for apply_msg in processblock.py
def apply_msg(block, tx, msg, code):
    msg = Message(msg.sender, msg.to, msg.value, msg.gas, bytearray_to_32s(
        [safe_ord(x) for x in msg.data]), len(msg.data))
    # print '### applying msg ###'
    callstack = []
    msgtop, mem, stk, ops, index = None, None, None, [], [None]

    done = []
    # Does anything special need to be done after this code chunk?
    special = [None, None, None, None, None, None]

    # To be called immediately when a new message is initiated
    def initialize(msg, code):
        # print 'init', extract_bytes(msg.data, 0, msg.databytes), msg.gas,
        # msg.sender, block.get_nonce(msg.sender)
        callstack.append(msg)
        # Transfer value, instaquit if not enough
        o = block.transfer_value(msg.sender, msg.to, msg.value)
        if not o:
            msg.callback(1, msg.gas, [])
            return
        msg.snapshot = block.snapshot()
        msg.compustate = Compustate(gas=msg.gas)
        if code in code_cache:
            msg.processed_code = code_cache[code]
        else:
            msg.processed_code = preprocess_vmcode(code)
            code_cache[code] = msg.processed_code

    initialize(msg, code)

    # To be called immediately when a message returns
    def drop(output, outputlength=0):
        special[0] = 'drop'
        special[1] = output
        special[2] = outputlength

    # The actual drop function, called by chunk finalizing code way
    # at the bottom below
    def drop2(o, l=0):
        # print 'dropping', extract_bytes(o, 0, l)
        if len(callstack) > 1:
            if o == OUT_OF_GAS:
                block.revert(msgtop.snapshot)
                msgtop.callback(0, msgtop.compustate.gas, [], 0)
            else:
                msgtop.callback(1, msgtop.compustate.gas, o, l)
            callstack.pop()
        else:
            if o == OUT_OF_GAS:
                block.revert(msgtop.snapshot)
                done.extend([0, msgtop.compustate.gas, []])
            else:
                done.extend([1, msgtop.compustate.gas, extract_bytes(o, 0, l)])

    # Generates callback functions for messages that create contracts
    def contract_callback_factory():

        def cb(res, gas, dat, databytes):
            if res:
                b = extract_bytes(dat, 0, databytes)
                block.set_code(callstack[-1].to, ''.join([ascii_chr(x) for x in b]))
                res = utils.coerce_to_int(callstack[-1].to)
            else:
                if tx.sender != callstack[-1].sender:
                    block.decrement_nonce(callstack[-1].sender)
                block.del_account(callstack[-1].to)
            callstack[-2].compustate.stack.append(res)
            callstack[-2].compustate.gas = gas
        callstack[-1].callback = cb

    # Generates callback functions for normal messages. Take the output start
    # and end bytes to put return data into parent memory
    def callback_factory(memoutstart, memoutsz):

        def cb(res, gas, dat, databytes):
            if res == 0:
                callstack[-2].compustate.stack.append(0)
            else:
                callstack[-2].compustate.stack.append(1)
                callstack[-2].compustate.gas += gas
                if len(dat) * 32 < memoutsz:
                    dat += [0] * (memoutsz - (len(dat) // 32) + 1)
                copy32(dat, callstack[-2].compustate.memory, 0, memoutstart, databytes)
        callstack[-1].callback = cb

    # Functions to calculate the current amount of gas left and
    # the current PC
    def gaz():
        g = msgtop.compustate.gas
        for i in range(index[0]):
            g -= code_chunk['opdata'][i][3]
        return g

    gas = gaz

    def pc():
        return code_chunk["opdata"][index[0]][5]

    # Functions to handle the individual operations
    def OP_STOP():
        drop([])

    def OP_ADD():
        stk.append((stk.pop() + stk.pop()) & TT256M1)

    def OP_SUB():
        stk.append((stk.pop() - stk.pop()) & TT256M1)

    def OP_MUL():
        stk.append((stk.pop() * stk.pop()) & TT256M1)

    def OP_DIV():
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 // s1)

    def OP_MOD():
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 % s1)

    def OP_SDIV():
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (abs(s0) // abs(s1) * (-1 if s0 * s1 < 0 else 1)) & TT256M1)

    def OP_SMOD():
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (abs(s0) % abs(s1) * (-1 if s0 < 0 else 1)) & TT256M1)

    def OP_INVALID():
        drop([])

    def OP_PUSHN():
        stk.append(code_chunk['opdata'][index[0]][6])

    def OP_DUPN():
        stk.append(stk[-(ops[index[0]][1] - 0x7f)])

    def OP_SWAPN():
        depth = ops[index[0]][1] - 0x8f
        temp = stk[-depth - 1]
        stk[-depth - 1] = stk[-1]
        stk[-1] = temp

    def OP_CREATE():
        value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, '', mstart, msz):
            return drop(OUT_OF_GAS)
        if block.get_balance(msgtop.to) >= value:
            sender = decode_hex(msgtop.to) if len(msgtop.to) == 40 else msgtop.to
            block.increment_nonce(msgtop.to)
            data = [0] * ((msz >> 5) + 1)
            copy32(mem, data, mstart, 0, msz)
            create_msg = Message(msgtop.to, '', value, gaz() - 100, data, msz)
            msgtop.compustate.gas -= gaz() - 100
            nonce = utils.encode_int(block.get_nonce(msgtop.to) - 1)
            create_msg.to = encode_hex(utils.sha3(rlp.encode([sender, nonce]))[12:])
            special[0] = 'create'
            special[1] = create_msg
            special[2] = ''.join([ascii_chr(x) for x in extract_bytes(data, 0, msz)])
        else:
            stk.append(0)

    def OP_CALL():
        subgas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        if max(meminstart + meminsz, memoutstart + memoutsz) > len(mem) << 5:
            if not mem_extend(mem, msgtop.compustate, '', meminstart, meminsz) or \
                    not mem_extend(mem, msgtop.compustate, '', memoutstart, memoutsz) or \
                    msgtop.compustate.gas < subgas:
                return drop(OUT_OF_GAS)
        msgtop.compustate.gas -= subgas
        if block.get_balance(msgtop.to) >= value:
            data = [0] * ((meminsz >> 5) + 1)
            copy32(mem, data, meminstart, 0, meminsz)
            to = utils.int_to_addr(to)
            call_msg = Message(msgtop.to, to, value, subgas, data, meminsz)
            special[0] = 'call'
            special[1] = call_msg
            special[2] = block.get_code(to)
            special[3] = memoutstart
            special[4] = memoutsz
        else:
            stk.append(0)

    def OP_RETURN():
        s0, s1 = stk.pop(), stk.pop()
        if s1:
            if not mem_extend(mem, msgtop.compustate, '', s0, s1):
                return drop(OUT_OF_GAS)
            o = [0] * ((s1 >> 5) + 1)
            copy32(mem, o, s0, 0, s1)
            drop(o, s1)

    def OP_CALLCODE():
        subgas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, '', meminstart, meminsz) or \
                not mem_extend(mem, msgtop.compustate, '', memoutstart, memoutsz):
            return drop(OUT_OF_GAS)
        if msgtop.compustate.gas < subgas:
            return drop(out_of_gas_exception('subcall gas', gas, msgtop.compustate, ''))
        msgtop.compustate.gas -= subgas
        data = [0] * ((meminsz >> 5) + 1)
        copy32(mem, data, meminstart, 0, meminsz)
        call_msg = Message(msgtop.to, msgtop.to, value, subgas, data, meminsz)
        special[0] = 'call'
        special[1] = call_msg
        special[2] = block.get_code(utils.int_to_addr(to))
        special[3] = memoutstart
        special[4] = memoutsz

    def OP_SUICIDE():
        to = utils.encode_int(stk.pop())
        to = encode_hex((('\x00' * (32 - len(to))) + to)[12:])
        block.transfer_value(msgtop.to, to, block.get_balance(msgtop.to))
        block.suicides.append(msgtop.to)
        drop([])

    def OP_EXP():
        stk.append(pow(stk.pop(), stk.pop(), TT256))

    def OP_NEG():
        stk.append(-stk.pop() & TT256M1)

    def OP_LT():
        stk.append(1 if stk.pop() < stk.pop() else 0)

    def OP_GT():
        stk.append(1 if stk.pop() > stk.pop() else 0)

    def OP_SLT():
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(1 if s0 < s1 else 0)

    def OP_SGT():
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(1 if s0 > s1 else 0)

    def OP_EQ():
        stk.append(1 if stk.pop() == stk.pop() else 0)

    def OP_NOT():
        stk.append(0 if stk.pop() else 1)

    def OP_AND():
        stk.append(stk.pop() & stk.pop())

    def OP_OR():
        stk.append(stk.pop() | stk.pop())

    def OP_XOR():
        stk.append(stk.pop() ^ stk.pop())

    def OP_BYTE():
        s0, s1 = stk.pop(), stk.pop()
        if s0 >= 32:
            stk.append(0)
        else:
            stk.append((s1 // 256 ** (31 - s0)) % 256)

    def OP_ADDMOD():
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 + s1) % s2 if s2 else 0)

    def OP_MULMOD():
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 * s1) % s2 if s2 else 0)

    def OP_SHA3():
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, '', s0, s1):
            return drop(OUT_OF_GAS)
        data = ''.join([ascii_chr(x) for x in mem[s0: s0 + s1]])
        stk.append(utils.big_endian_to_int(utils.sha3(data)))

    def OP_ADDRESS():
        stk.append(utils.coerce_to_int(msg.to))

    def OP_BALANCE():
        stk.append(block.get_balance(utils.coerce_addr_to_hex(stk.pop())))

    def OP_ORIGIN():
        stk.append(utils.coerce_to_int(tx.sender))

    def OP_CALLER():
        stk.append(utils.coerce_to_int(msg.sender))

    def OP_CALLVALUE():
        stk.append(msg.value)

    def OP_CALLDATALOAD():
        s0 = stk.pop()
        if s0 >= msgtop.databytes:
            stk.append(0)
        else:
            stk.append(load32(msgtop.data, s0))

    def OP_CALLDATASIZE():
        stk.append(msgtop.databytes)

    def OP_CALLDATACOPY():
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, '', s0, s2):
            return drop(OUT_OF_GAS)
        if s1 + s2 > (len(msgtop.data) << 5):
            msgtop.data.extend([0] * (((s1 + s2) >> 5) - len(msgtop.data) + 1))
        copy32(msgtop.data, mem, s1, s0, s2)

    def OP_CODESIZE():
        stk.append(len(msgtop.processed_code))

    def OP_CODECOPY():
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if s2:
            if not mem_extend(mem, msgtop.compustate, '', s0, s2):
                return drop(OUT_OF_GAS)
            copy_chunk = msgtop.processed_code["code"][s1: s1 + s2]
            copy_chunk += [0] * (s2 - len(copy_chunk))
            set_bytes(mem, s0, copy_chunk)

    def OP_GASPRICE():
        stk.append(tx.gasprice)

    def OP_EXTCODESIZE():
        stk.append(len(block.get_code(utils.coerce_addr_to_hex(stk.pop())) or ''))

    def OP_EXTCODECOPY():
        addr, s1, s2, s3 = stk.pop(), stk.pop(), stk.pop(), stk.pop()
        extcode = block.get_code(utils.coerce_addr_to_hex(addr)) or ''
        if not mem_extend(mem, msgtop.compustate, '', s1, s3):
            return drop(OUT_OF_GAS)
        for i in range(s3):
            if s2 + i < len(extcode):
                mem[s1 + i] = safe_ord(extcode[s2 + i])
            else:
                mem[s1 + i] = 0

    def OP_PREVHASH():
        stk.append(utils.big_endian_to_int(block.prevhash))

    def OP_COINBASE():
        stk.append(utils.big_endian_to_int(decode_hex(block.coinbase)))

    def OP_TIMESTAMP():
        stk.append(block.timestamp)

    def OP_NUMBER():
        stk.append(block.number)

    def OP_DIFFICULTY():
        stk.append(block.difficulty)

    def OP_GASLIMIT():
        stk.append(block.gas_limit)

    def OP_POP():
        stk.pop()

    def OP_MLOAD():
        s0 = stk.pop()
        if (s0 + 32) > len(mem) << 5:
            if not mem_extend(mem, msgtop.compustate, '', s0, 32):
                return drop(OUT_OF_GAS)
        if not s0 % 32:
            stk.append(mem[s0 >> 5])
        else:
            stk.append((mem[s0 >> 5] << (8 * (s0 % 32))) &
                       TT256M1 + mem[s0 >> 5 + 1] >> (256 - 8 * (s0 % 32)))

    def OP_MSTORE():
        s0, s1 = stk.pop(), stk.pop()
        if (s0 + 32) > len(mem) << 5:
            if not mem_extend(mem, msgtop.compustate, '', s0, 32):
                return drop(OUT_OF_GAS)
        if not s0 % 32:
            mem[s0 >> 5] = s1
        else:
            mem[s0 >> 5] = mem[s0 >> 5] & (
                TT256 - (TT256 >> (8 * (s0 % 32)))) + s1 >> (8 * (s0 % 32))
            mem[s0 >> 5 + 1] = mem[s0 >> 5 +
                                   1] & ((TT256 >> (8 * (s0 % 32))) - 1) + (s1 << (256 - 8 * (s0 % 32))) & TT256M1

    def OP_MSTORE8():
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, '', s0, 1):
            return drop(OUT_OF_GAS)
        a = mem[s0 >> 5]
        mem[s0 >> 5] = (a ^ (a & ((1 << (256 - 8 * (s0 % 32))) * 255))) + \
            s1 << (256 - 8 * (s0 % 32))

    def OP_SLOAD():
        stk.append(block.get_storage_data(msgtop.to, stk.pop()))

    def OP_SSTORE():
        s0, s1 = stk.pop(), stk.pop()
        pre_occupied = GSTORAGE if block.get_storage_data(msgtop.to, s0) else 0
        post_occupied = GSTORAGE if s1 else 0
        gascost = GSTORAGE + post_occupied - pre_occupied
        if msgtop.compustate.gas < gascost:
            return drop(out_of_gas_exception('sstore trie expansion', gascost, msgtop.compustate, ''))
        msgtop.compustate.gas -= gascost
        block.set_storage_data(msgtop.to, s0, s1)

    def OP_JUMP():
        special[0] = 'jump'
        special[1] = stk.pop() + 1
        op = msgtop.processed_code.get(special[1], {"jumpable": None})
        if not op["jumpable"]:
            return drop([])
        msgtop.compustate.gas -= 1

    def OP_JUMPI():
        s0, s1 = stk.pop(), stk.pop()
        if s1:
            special[0] = 'jump'
            special[1] = s0 + 1
            op = msgtop.processed_code.get(special[1], {"jumpable": None})
            if not op["jumpable"]:
                return drop([])
            msgtop.compustate.gas -= 1

    def OP_PC():
        stk.append(pc())

    def OP_MSIZE():
        stk.append(len(mem) << 5)

    def OP_GAS():
        stk.append(gas() - 1)

    def OP_JUMPDEST():
        pass

    op_map = [
        # 0x00
        OP_STOP,
        OP_ADD,
        OP_MUL,
        OP_SUB,
        OP_DIV,
        OP_SDIV,
        OP_MOD,
        OP_SMOD,
        OP_EXP,
        OP_NEG,
        OP_LT,
        OP_GT,
        OP_SLT,
        OP_SGT,
        OP_EQ,
        OP_NOT,
        # 0x10
        OP_AND,
        OP_OR,
        OP_XOR,
        OP_BYTE,
        OP_ADDMOD,
        OP_MULMOD,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        # 0x20
        OP_SHA3,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        # 0x30:
        OP_ADDRESS,
        OP_BALANCE,
        OP_ORIGIN,
        OP_CALLER,
        OP_CALLVALUE,
        OP_CALLDATALOAD,
        OP_CALLDATASIZE,
        OP_CALLDATACOPY,
        OP_CODESIZE,
        OP_CODECOPY,
        OP_GASPRICE,
        OP_EXTCODESIZE,
        OP_EXTCODECOPY,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        # 0x40:
        OP_PREVHASH,
        OP_COINBASE,
        OP_TIMESTAMP,
        OP_NUMBER,
        OP_DIFFICULTY,
        OP_GASLIMIT,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        # 0x50
        OP_POP,
        OP_INVALID,
        OP_INVALID,
        OP_MLOAD,
        OP_MSTORE,
        OP_MSTORE8,
        OP_SLOAD,
        OP_SSTORE,
        OP_JUMP,
        OP_JUMPI,
        OP_PC,
        OP_MSIZE,
        OP_GAS,
        OP_JUMPDEST,
        OP_INVALID,
        OP_INVALID,
    ] + [OP_PUSHN] * 32 + [OP_DUPN] * 16 + [OP_SWAPN] * 16 + [OP_INVALID] * 80 + [
        OP_CREATE,
        OP_CALL,
        OP_CALLCODE,
        OP_RETURN,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_INVALID,
        OP_SUICIDE
    ]

    # Main loop
    while not done:
        msgtop = callstack[-1]
        stk = msgtop.compustate.stack
        mem = msgtop.compustate.memory
        # print msgtop.processed_code
        if msgtop.compustate.pc not in msgtop.processed_code:
            drop2([])
            continue

        code_chunk = msgtop.processed_code[msgtop.compustate.pc]
        # insufficient stack or base gas
        if len(stk) < code_chunk["reqh"] or \
                msgtop.compustate.gas < code_chunk["gascost"]:
            drop2([])
        ops = code_chunk["ops"]
        index = [0]
        # Run a code chunk
        for (index[0], op) in ops:
            op_map[op]()

        msgtop.compustate.gas -= code_chunk["gascost"]
        # insufficient extra gas
        if msgtop.compustate.gas < 0:
            drop2(out_of_gas_exception(
                'surcharges', code_chunk["gascost"], msgtop.compustate, ops))
        msgtop.compustate.pc = code_chunk["end"]

        # If we need to jump, return or call
        if special[0] is not None:
            if special[0] == 'drop':
                drop2(special[1], special[2])
            elif special[0] == 'jump':
                msgtop.compustate.pc = special[1]
            elif special[0] == 'create':
                initialize(special[1], special[2])
                contract_callback_factory()
            elif special[0] == 'call':
                initialize(special[1], special[2])
                callback_factory(special[3], special[4])
            special[0] = None

    return done
