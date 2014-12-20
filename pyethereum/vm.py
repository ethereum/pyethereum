import utils
import copy
import opcodes
import json
from pyethereum.slogging import get_logger
log_log = get_logger('eth.vm.log')
log_vm_exit = get_logger('eth.vm.exit')
log_vm_op = get_logger('eth.vm.op')
log_vm_op_stack = get_logger('eth.vm.op.stack')
log_vm_op_memory = get_logger('eth.vm.op.memory')
log_vm_op_storage = get_logger('eth.vm.op.storage')

TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1
TT255 = 2 ** 255


class Message(object):

    def __init__(self, sender, to, value, gas, data, depth=0):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data
        self.depth = depth
        self.logs = []

    def __repr__(self):
        return '<Message(to:%s...)>' % self.to[:8]


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
        o = copy.copy(opcodes.opcodes.get(ord(code[i]), ['INVALID', 0, 0, 0]) +
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


def mem_extend(mem, compustate, op, start, sz):
    if sz:
        newsize = start + sz
        if len(mem) < utils.ceil32(newsize):
            m_extend = utils.ceil32(newsize) - len(mem)
            memfee = opcodes.GMEMORY * (m_extend / 32)
            if compustate.gas < memfee:
                compustate.gas = 0
                return False
            compustate.gas -= memfee
            mem.extend([0] * m_extend)
    return True


def data_copy(compustate, size):
    if size:
        copyfee = opcodes.GCOPY * utils.ceil32(size) / 32
        if compustate.gas < copyfee:
            compustate.gas = 0
            return False
        compustate.gas -= copyfee
    return True


def vm_exception(error, **kargs):
    log_vm_exit.trace('EXCEPTION', cause=error, **kargs)
    return 0, 0, []


def peaceful_exit(cause, gas, data, **kargs):
    log_vm_exit.trace('EXIT', cause=cause, **kargs)
    return 1, gas, data

code_cache = {}


def vm_execute(ext, msg, code):
    # precompute trace flag
    # if we trace vm, we're in slow mode anyway
    trace_vm = log_vm_op.is_active('trace')

    compustate = Compustate(gas=msg.gas)
    stk = compustate.stack
    mem = compustate.memory

    if code in code_cache:
        processed_code = code_cache[code]
    else:
        processed_code = preprocess_code(code)
        code_cache[code] = processed_code

    codelen = len(processed_code)

    while 1:
        if compustate.pc >= codelen:
            return peaceful_exit('CODE OUT OF RANGE', compustate.gas, [])

        op, in_args, out_args, fee, opcode, pushval = \
            processed_code[compustate.pc]

        # out of gas error
        if fee > compustate.gas:
            return vm_exception('OUT OF GAS')

        # empty stack error
        if in_args > len(compustate.stack):
            return vm_exception('INSUFFICIENT STACK',
                                op=op, needed=str(in_args),
                                available=str(len(compustate.stack)))

        # Apply operation
        compustate.gas -= fee
        compustate.pc += 1

        if trace_vm:
            """
            This diverges from normal logging, as we use the logging namespace
            only to decide which features get logged in 'eth.vm.op'
            i.e. tracing can not be activated by activating a sub like 'eth.vm.op.stack'
            """
            trace_data = {}
            if log_vm_op_stack.is_active():
                trace_data['stack'] = map(str, list(compustate.stack))
            if log_vm_op_memory.is_active():
                trace_data['memory'] = \
                    ''.join([chr(x).encode('hex') for x in compustate.memory])
            if log_vm_op_storage.is_active():
                trace_data['storage'] = ext.log_storage(msg.to)
            trace_data['gas'] = str(compustate.gas + fee)
            trace_data['pc'] = str(compustate.pc - 1)
            trace_data['op'] = op
            if op[:4] == 'PUSH':
                trace_data['pushvalue'] = pushval

            log_vm_op.trace('vm', **trace_data)

        if opcode < 0x10:
            if op == 'STOP':
                return peaceful_exit('STOP', compustate.gas, [])
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
                s0, s1 = utils.to_signed(stk.pop()), utils.to_signed(stk.pop())
                stk.append(0 if s1 == 0 else (abs(s0) // abs(s1) *
                           (-1 if s0 * s1 < 0 else 1)) & TT256M1)
            elif op == 'SMOD':
                s0, s1 = utils.to_signed(stk.pop()), utils.to_signed(stk.pop())
                stk.append(0 if s1 == 0 else (abs(s0) % abs(s1) *
                           (-1 if s0 < 0 else 1)) & TT256M1)
            elif op == 'ADDMOD':
                s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
                stk.append((s0 + s1) % s2 if s2 else 0)
            elif op == 'MULMOD':
                s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
                stk.append((s0 * s1) % s2 if s2 else 0)
            elif op == 'EXP':
                base, exponent = stk.pop(), stk.pop()
                # fee for exponent is dependent on its bytes
                # calc n bytes to represent exponent
                nbytes = len(utils.encode_int(exponent))
                expfee = nbytes * opcodes.GEXPONENTBYTE
                if compustate.gas < expfee:
                    compustate.gas = 0
                    return vm_exception('OOG EXPONENT')
                compustate.gas -= expfee
                stk.append(pow(base, exponent, TT256))
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
        elif opcode < 0x20:
            if op == 'LT':
                stk.append(1 if stk.pop() < stk.pop() else 0)
            elif op == 'GT':
                stk.append(1 if stk.pop() > stk.pop() else 0)
            elif op == 'SLT':
                s0, s1 = utils.to_signed(stk.pop()), utils.to_signed(stk.pop())
                stk.append(1 if s0 < s1 else 0)
            elif op == 'SGT':
                s0, s1 = utils.to_signed(stk.pop()), utils.to_signed(stk.pop())
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
        elif opcode < 0x40:
            if op == 'SHA3':
                s0, s1 = stk.pop(), stk.pop()
                compustate.gas -= 10 * (utils.ceil32(s1) / 32)
                if compustate.gas < 0:
                    return vm_exception('OOG PAYING FOR SHA3')
                if not mem_extend(mem, compustate, op, s0, s1):
                    return vm_exception('OOG EXTENDING MEMORY')
                data = ''.join(map(chr, mem[s0: s0 + s1]))
                stk.append(utils.big_endian_to_int(utils.sha3(data)))
            elif op == 'ADDRESS':
                stk.append(utils.coerce_to_int(msg.to))
            elif op == 'BALANCE':
                stk.append(ext.get_balance(utils.coerce_addr_to_hex(stk.pop())))
            elif op == 'ORIGIN':
                stk.append(utils.coerce_to_int(ext.tx_origin))
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
                start, s1, size = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, start, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                for i in range(size):
                    if s1 + i < len(msg.data):
                        mem[start + i] = ord(msg.data[s1 + i])
                    else:
                        mem[start + i] = 0
            elif op == 'CODESIZE':
                stk.append(len(processed_code))
            elif op == 'CODECOPY':
                start, s1, size = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, start, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                for i in range(size):
                    if s1 + i < len(processed_code):
                        mem[start + i] = processed_code[s1 + i][4]
                    else:
                        mem[start + i] = 0
            elif op == 'GASPRICE':
                stk.append(ext.tx_gasprice)
            elif op == 'EXTCODESIZE':
                stk.append(len(ext.get_code(utils.coerce_addr_to_hex(stk.pop())) or ''))
            elif op == 'EXTCODECOPY':
                addr, start, s2, size = stk.pop(), stk.pop(), stk.pop(), stk.pop()
                extcode = ext.get_code(utils.coerce_addr_to_hex(addr)) or ''
                if not mem_extend(mem, compustate, op, start, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                for i in range(size):
                    if s2 + i < len(extcode):
                        mem[start + i] = ord(extcode[s2 + i])
                    else:
                        mem[start + i] = 0
        elif opcode < 0x50:
            if op == 'PREVHASH':
                stk.append(utils.big_endian_to_int(ext.block_prevhash))
            elif op == 'COINBASE':
                stk.append(utils.big_endian_to_int(ext.block_coinbase.decode('hex')))
            elif op == 'TIMESTAMP':
                stk.append(ext.block_timestamp)
            elif op == 'NUMBER':
                stk.append(ext.block_number)
            elif op == 'DIFFICULTY':
                stk.append(ext.block_difficulty)
            elif op == 'GASLIMIT':
                stk.append(ext.block_gas_limit)
        elif opcode < 0x60:
            if op == 'POP':
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
                stk.append(ext.get_storage_data(msg.to, stk.pop()))
            elif op == 'SSTORE':
                s0, s1 = stk.pop(), stk.pop()
                if ext.get_storage_data(msg.to, s0):
                    gascost = opcodes.GSTORAGEMOD if s1 else opcodes.GSTORAGEKILL
                else:
                    gascost = opcodes.GSTORAGEADD if s1 else opcodes.GSTORAGEMOD
                if compustate.gas < gascost:
                    return vm_exception('OUT OF GAS')
                compustate.gas -= max(gascost, 0)
                ext.add_refund(max(-gascost, 0))  # adds neg gascost as a refund if below zero
                ext.set_storage_data(msg.to, s0, s1)
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
            temp = stk[-depth - 1]
            stk[-depth - 1] = stk[-1]
            stk[-1] = temp

        elif op[:3] == 'LOG':
            """
            0xa0 ... 0xa4, 32/64/96/128/160 + len(data) gas
            a. Opcodes LOG0...LOG4 are added, takes 2-6 stack arguments
                    MEMSTART MEMSZ (TOPIC1) (TOPIC2) (TOPIC3) (TOPIC4)
            b. Logs are kept track of during tx execution exactly the same way as suicides
               (except as an ordered list, not a set).
               Each log is in the form [address, [topic1, ... ], data] where:
               * address is what the ADDRESS opcode would output
               * data is mem[MEMSTART: MEMSTART + MEMSZ]
               * topics are as provided by the opcode
            c. The ordered list of logs in the transaction are expressed as [log0, log1, ..., logN].
            """
            depth = int(op[3:])
            mstart, msz = stk.pop(), stk.pop()
            topics = [stk.pop() for x in range(depth)]
            compustate.gas -= msz
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            data = ''.join(map(chr, mem[mstart: mstart + msz]))
            ext.log(msg.to, topics, data)
            log_log.trace('LOG', to=msg.to, topics=topics, data=map(ord, data))
            print ('LOG', msg.to, topics, map(ord, data))

        elif op == 'CREATE':
            value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            if ext.get_balance(msg.to) >= value:
                data = ''.join(map(chr, mem[mstart: mstart + msz]))
                create_msg = Message(msg.to, '', value, compustate.gas, data, msg.depth + 1)
                o, gas, addr = ext.create(create_msg)
                if o:
                    stk.append(utils.coerce_to_int(addr))
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
            if ext.get_balance(msg.to) >= value:
                to = utils.encode_int(to)
                to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
                data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
                call_msg = Message(msg.to, to, value, gas, data, msg.depth + 1)
                result, gas, data = ext.call(call_msg)
                if result == 0:
                    stk.append(0)
                else:
                    stk.append(1)
                    compustate.gas += gas
                    for i in range(min(len(data), memoutsz)):
                        mem[memoutstart + i] = data[i]
            else:
                stk.append(0)
        elif op == 'CALLCODE':
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
            call_msg = Message(msg.to, msg.to, value, gas, data, msg.depth + 1)
            result, gas, data = ext.sendmsg(call_msg, ext.get_code(to))
            if result == 0:
                stk.append(0)
            else:
                stk.append(1)
                compustate.gas += gas
                for i in range(min(len(data), memoutsz)):
                    mem[memoutstart + i] = data[i]
        elif op == 'RETURN':
            s0, s1 = stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, s0, s1):
                return vm_exception('OOG EXTENDING MEMORY')
            return peaceful_exit('RETURN', compustate.gas, mem[s0: s0 + s1])
        elif op == 'SUICIDE':
            to = utils.encode_int(stk.pop())
            to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
            xfer = ext.get_balance(msg.to)
            ext.set_balance(msg.to, 0)
            ext.set_balance(to, ext.get_balance(to) + xfer)
            ext.add_suicide(msg.to)
            return 1, compustate.gas, []
        elif op == 'INVALID':
            return vm_exception('INVALID OP', opcode=opcode)
        # for a in stk:
        #     assert isinstance(a, (int, long))


class VmExtBase():

    def __init__(self):
        self.get_code = lambda addr: ''
        self.get_balance = lambda addr: 0
        self.set_balance = lambda addr, balance: 0
        self.set_storage_data = lambda addr, key, value: 0
        self.get_storage_data = lambda addr, key: 0
        self.log_storage = lambda addr: 0
        self.add_suicide = lambda addr: 0
        self.add_refund = lambda x: 0
        self.block_prevhash = 0
        self.block_coinbase = 0
        self.block_timestamp = 0
        self.block_number = 0
        self.block_difficulty = 0
        self.block_gas_limit = 0
        self.log = lambda addr, topics, data: 0
        self.tx_origin = '0' * 40
        self.tx_gasprice = 0
        self.create = lambda msg: 0, 0, 0
        self.call = lambda msg: 0, 0, 0
        self.sendmsg = lambda msg: 0, 0, 0
