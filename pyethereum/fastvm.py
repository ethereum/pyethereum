from opcodes import opcodes, reverse_opcodes
import utils
import serpent
import rlp
import copy

code_cache = {}
OUT_OF_GAS = -1

GDEFAULT = 1
GMEMORY = 1
GSTORAGE = 100
GTXDATA = 5
GTXCOST = 500
TT255 = 2**255
TT256 = 2**256
TT256M1 = 2**256 - 1
filter1 = set(['JUMP', 'JUMPI', 'JUMPDEST', 'STOP', 'RETURN',
               'INVALID', 'CALL', 'CREATE', 'CALL_CODE', 'SUICIDE'])


def to_signed(i):
    return i if i < TT255 else i - TT256


def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)


def extract_bytes(mem, start, sz):
    end = start + sz
    if not sz:
        return []
    elif (start // 32) == (end // 32):
        m = mem[start // 32]
        o = utils.int_to_bytearray(m, 32)[start % 32: end % 32]
    else:
        m = utils.int_to_bytearray(mem[start // 32], 32)[start % 32:]
        for i in range(start // 32 + 1, end // 32):
            m.extend(utils.int_to_bytearray(mem[i], 32))
        if end % 32:
            m.extend(utils.int_to_bytearray(mem[end // 32], 32)[:end % 32])
        o = m
    return o


def set_bytes(mem, start, bytez):
    end = start + len(bytez)
    if not bytez:
        pass
    elif (start // 32) == (end // 32):
        m = utils.int_to_bytearray(mem[start // 32], 32)
        mem[start // 32] = utils.bytearray_to_int(m[:start % 32] + bytez + m[end % 32:])
    else:
        m = utils.int_to_bytearray(mem[start // 32], 32)
        mem[start // 32] = utils.bytearray_to_int(m[:start % 32] + bytez[:32 - (start % 32)])
        j = 0
        for i in range(start // 32 + 1, end // 32):
            mem[i] = utils.bytearray_to_int(bytez[j * 32 + 32 - start % 32: j * 32 + 64 - start % 32])
            j += 1
        if end % 32:
            m2 = utils.int_to_bytearray(mem[end // 32], 32)
            endpiece = bytez[j * 32 + 32 - start % 32:]
            mem[end // 32] = utils.bytearray_to_int(endpiece + m2[-32+len(endpiece):])


def mem_extend(mem, compustate, op, start, sz):
    if sz:
        newsize = start + sz
        if len(mem) < ceil32(newsize) // 32:
            m_extend = ceil32(newsize) // 32 - len(mem)
            memfee = GMEMORY * m_extend
            if compustate.gas < memfee:
                out_of_gas_exception('mem_extend', memfee, compustate, op)
                compustate.gas = 0
                return False
            compustate.gas -= memfee
            mem.extend([0] * m_extend)
    return True


class Compustate():

    def __init__(self, **kwargs):
        self.memory = []
        self.stack = []
        self.pc = 0
        self.gas = 0
        for kw in kwargs:
            setattr(self, kw, kwargs[kw])


class Message(object):

    def __init__(self, sender, to, value, gas, data):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data
        self.processed_code = []
        self.callback = lambda x, y, z: x
        self.snapshot = None
        self.compustate = None

    def __repr__(self):
        return '<Message(to:%s...)>' % self.to[:8]


def out_of_gas_exception(expense, fee, compustate, op):
    return OUT_OF_GAS


def preprocess_vmcode(code):
    o = []
    jumps = {}
    # Round 1: Locate all JUMP, JUMPI, JUMPDEST, STOP, RETURN, INVALID locs
    opcodez = copy.deepcopy([opcodes.get(ord(c), ['INVALID', 0, 0, 1]) +
               [ord(c)] for c in code])
    for i, o in enumerate(opcodez):
        if o[0] in filter1:
            jumps[i] = True

    chunks = {}
    chunks["code"] = [ord(x) for x in code]
    c = []
    h, reqh, gascost = 0, 0, 0
    i = 0
    laststart, lastjumpable = 0, 0
    while i < len(opcodez):
        o = opcodez[i] # [op, ins, outs, gas, opcode, pos, push?]
        o.append(laststart + i)
        c.append(o)
        reqh = max(reqh, h + o[1])
        h += o[1] - o[2]
        gascost += o[3]
        if i in jumps:
            chunks[laststart] = {"reqh": reqh, "deltah": -h,
                                 "gascost": gascost, "opdata": c,
                                 "ops": [x[4] for x in c],
                                 "start": laststart, "jumpable": lastjumpable,
                                 "end": i+1}
            c = []
            laststart = i+1
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
                         "ops": [x[4] for x in c],
                         "start": laststart, "jumpable": lastjumpable,
                         "end": i+1}
    return chunks


def apply_msg(block, tx, msg, code):
    # print '### applying msg ###'
    msg.data = [ord(x) for x in msg.data]
    callstack = []
    msgtop, mem, stk, ops, index = None, None, None, [], [None]

    done = []
    # Does anything special need to be done after this code chunk?
    special = [None, None, None, None, None, None]

    # To be called immediately when a new message is initiated
    def initialize(msg, code):
        # print 'init', msg.data, msg.gas, msg.sender, block.get_nonce(msg.sender)
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
    def drop(o):
        special[0] = 'drop'
        special[1] = o

    def drop2(o):
        # print 'dropping', o
        if len(callstack) > 1:
            if o == OUT_OF_GAS:
                block.revert(msgtop.snapshot)
                msgtop.callback(0, msgtop.compustate.gas, [])
            else:
                msgtop.callback(1, msgtop.compustate.gas, o)
            callstack.pop()
        else:
            if o == OUT_OF_GAS:
                block.revert(msgtop.snapshot)
                done.extend([0, msgtop.compustate.gas, []])
            else:
                done.extend([1, msgtop.compustate.gas, o])

    def contract_callback_factory():

        def cb(res, gas, dat):
            if res:
                block.set_code(callstack[-1].to, ''.join([chr(x) for x in dat]))
                res = utils.coerce_to_int(callstack[-1].to)
            else:
                if tx.sender != callstack[-1].sender:
                    block.decrement_nonce(callstack[-1].sender)
                block.del_account(callstack[-1].to)
            callstack[-2].compustate.stack.append(res)
            callstack[-2].compustate.gas = gas
        callstack[-1].callback = cb

    def callback_factory(memoutstart, memoutsz):

        def cb(res, gas, dat):
            if res == 0:
                callstack[-2].compustate.stack.append(0)
            else:
                callstack[-2].compustate.stack.append(1)
                callstack[-2].compustate.gas += gas
                dat2 = dat[:memoutsz]
                dat2 += [0] * (memoutsz - len(dat2))
                set_bytes(callstack[-2].compustate.memory, memoutstart, dat2)
        callstack[-1].callback = cb

    def gaz():
        g = msgtop.compustate.gas
        for i in range(index[0]):
            g -= code_chunk['opdata'][i][3]
        return g

    gas = gaz

    def pc():
        return code_chunk["opdata"][index[0]][5]

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
        stk.append(0 if s1 == 0 else s0 / s1)

    def OP_MOD():
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 % s1)

    def OP_SDIV():
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (abs(s0) // abs(s1) * (-1 if s0*s1 < 0 else 1)) & TT256M1)

    def OP_SMOD():
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (abs(s0) % abs(s1) * (-1 if s0 < 0 else 1)) & TT256M1)

    def OP_INVALID():
        drop([])

    def OP_CATCHALL():
        a = ops[index[0]]
        if 0x60 <= a < 0x80:
            dat = code_chunk['opdata'][index[0]][6]
            stk.append(dat)
        elif 0x80 <= a < 0x90:
            depth = a - 0x7f
            stk.append(stk[-depth])
        elif 0x90 <= a < 0xa0:
            depth = a - 0x8f
            temp = stk[-depth-1]
            stk[-depth-1] = stk[-1]
            stk[-1] = temp
        elif a not in opcodes: # INVALID
            drop([])

    def OP_CREATE():
            value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, msgtop.compustate, '', mstart, msz):
                return drop(OUT_OF_GAS)
            if block.get_balance(msgtop.to) >= value:
                sender = msgtop.to.decode('hex') if len(msgtop.to) == 40 else msgtop.to
                block.increment_nonce(msgtop.to)
                data = extract_bytes(mem, mstart, msz)
                create_msg = Message(msgtop.to, '', value, gaz() - 100, data)
                msgtop.compustate.gas -= gaz() - 100
                nonce = utils.encode_int(block.get_nonce(msgtop.to) - 1)
                create_msg.to = utils.sha3(rlp.encode([sender, nonce]))[12:].encode('hex')
                special[0] = 'create'
                special[1] = create_msg
                special[2] = ''.join([chr(x) for x in data])
            else:
                stk.append(0)

    def OP_CALL():
            subgas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, msgtop.compustate, '', meminstart, meminsz) or \
                    not mem_extend(mem, msgtop.compustate, '', memoutstart, memoutsz) or \
                    msgtop.compustate.gas < subgas:
                return drop(OUT_OF_GAS)
            msgtop.compustate.gas -= subgas
            if block.get_balance(msgtop.to) >= value:
                to = utils.encode_int(to & (2**160 - 1))
                to = (('\x00' * (20 - len(to))) + to).encode('hex')
                data = extract_bytes(mem, meminstart, meminsz)
                call_msg = Message(msgtop.to, to, value, subgas, data)
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
            drop(extract_bytes(mem, s0, s1))

    def OP_CALL_CODE():
            subgas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, msgtop.compustate, '', meminstart, meminsz) or \
                    not mem_extend(mem, msgtop.compustate, '', memoutstart, memoutsz):
                return drop(OUT_OF_GAS)
            if msgtop.compustate.gas < subgas:
                return drop(out_of_gas_exception('subcall gas', gas, msgtop.compustate, ''))
            msgtop.compustate.gas -= subgas
            to = utils.encode_int(to)
            to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
            data = extract_bytes(mem, meminstart, meminsz)
            call_msg = Message(msgtop.to, msgtop.to, value, subgas, data)
            special[0] = 'call'
            special[1] = call_msg
            special[2] = block.get_code(to)
            special[3] = memoutstart
            special[4] = memoutsz

    def OP_SUICIDE():
            to = utils.encode_int(stk.pop())
            to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
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
            stk.append((s1 / 256 ** (31 - s0)) % 256)

    def OP_ADDMOD():
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 + s1) % s2 if s2 else 0)

    def OP_MULMOD():
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 * s1) % s2 if s2 else 0)

    def OP_SHA3():
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, op, s0, s1):
            return drop(OUT_OF_GAS)
        data = ''.join([chr(x) for x in mem[s0: s0 + s1]])
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
        if s0 >= len(msgtop.data):
            stk.append(0)
        else:
            stk.append(utils.bytearray_to_int(msgtop.data[s0: s0 + 32]))

    def OP_CALLDATASIZE():
        stk.append(len(msgtop.data))

    def OP_CALLDATACOPY():
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, '', s0, s2):
            return drop(OUT_OF_GAS)
        copy_chunk = msgtop.data[s1: s1 + s2]
        copy_chunk += [0] * (s2 - len(copy_chunk))
        set_bytes(mem, s0, copy_chunk)

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
                mem[s1 + i] = ord(extcode[s2 + i])
            else:
                mem[s1 + i] = 0

    def OP_PREVHASH():
        stk.append(utils.big_endian_to_int(block.prevhash))

    def OP_COINBASE():
        stk.append(utils.big_endian_to_int(block.coinbase.decode('hex')))

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
        if not mem_extend(mem, msgtop.compustate, '', s0, 32):
            return drop(OUT_OF_GAS)
        if not s0 % 32:
            stk.append(mem[s0 // 32])
        else:
            stk.append((mem[s0 // 32] << (8 * (s0 % 32))) & TT256M1 + mem[s0 // 32 + 1] >> (32 - s0 % 32))

    def OP_MSTORE():
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, '', s0, 32):
            return drop(OUT_OF_GAS)
        if not s0 % 32:
            mem[s0 // 32] = s1
        else:
            mem[s0 // 32] = mem[s0 // 32] & (TT256 - (TT256 >> (8 * (s0 % 32)))) + s1 >> (8 * (s0 % 32))
            mem[s0 // 32 + 1] = mem[s0 // 32 + 1] & ((TT256 >> (8 * (s0 % 32))) - 1) + (s1 << (256 - 8 * (s0 % 32))) & TT256M1

    def OP_MSTORE8():
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, msgtop.compustate, '', s0, 1):
            return drop(OUT_OF_GAS)
        a = mem[s0 // 32]
        mem[s0 // 32] = (a ^ (a & ((1 << (256 - 8 * (s0 % 32))) * 255))) + s1 << (256 - 8 * (s0 % 32))

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
        stk.append(len(mem) * 32)

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
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        # 0x20
        OP_SHA3,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
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
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        # 0x40:
        OP_PREVHASH,
        OP_COINBASE,
        OP_TIMESTAMP,
        OP_NUMBER,
        OP_DIFFICULTY,
        OP_GASLIMIT,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        # 0x50
        OP_POP,
        OP_CATCHALL,
        OP_CATCHALL,
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
        OP_CATCHALL,
        OP_CATCHALL,
    ] + [OP_CATCHALL] * 144 + [
        OP_CREATE,
        OP_CALL,
        OP_RETURN,
        OP_CALL_CODE,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_CATCHALL,
        OP_SUICIDE
    ]

    while not done:
        msgtop = callstack[-1]
        stk = msgtop.compustate.stack
        mem = msgtop.compustate.memory
        # print msgtop.processed_code
        if msgtop.compustate.pc not in msgtop.processed_code:
            drop2([])
            continue

        code_chunk = msgtop.processed_code[msgtop.compustate.pc]
        # print 'cc', code_chunk, msgtop.compustate.gas
        # insufficient stack or base gas
        if len(msgtop.compustate.stack) < code_chunk["reqh"] or \
                msgtop.compustate.gas < code_chunk["gascost"]:
            drop2([])
        ops = code_chunk["ops"]
        opcount = len(ops)
        index = [0]
        while index[0] < opcount:
            # print msgtop.compustate.stack, gas(), msgtop.compustate.gas
            # print 'op', code_chunk['opdata'][index[0]][0], msgtop.compustate.stack, gaz()
            op_map[ops[index[0]]]()
            index[0] += 1

        # print 'd', msgtop.compustate.stack, gas(), msgtop.compustate.gas, code_chunk["gascost"]
        # print 'e', droppable[0], jumpable[0], msgtop.compustate.stack

        msgtop.compustate.gas -= code_chunk["gascost"]
        # insufficient extra gas
        if msgtop.compustate.gas < 0:
            drop2(out_of_gas_exception('surcharges', code_chunk["gascost"], msgtop.compustate, code_chunk["ops"]))
        msgtop.compustate.pc = code_chunk["end"]

        if special[0] is not None:
            if special[0] == 'drop':
                drop2(special[1])
            elif special[0] == 'jump':
                msgtop.compustate.pc = special[1]
            elif special[0] == 'create':
                initialize(special[1], special[2])
                contract_callback_factory()
            elif special[0] == 'call':
                initialize(special[1], special[2])
                callback_factory(special[3], special[4])
            special[0] = None
        #print done

    return done
