import copy
import ethereum.opcodes as opcodes
#  ####### dev hack flags ###############

verify_stack_after_op = False

#  ######################################
import sys

from ethereum import utils
from ethereum.abi import is_numeric
import copy
from ethereum import opcodes
import time
from ethereum.slogging import get_logger
from rlp.utils import encode_hex, ascii_chr
from ethereum.utils import to_string
import numpy

log_log = get_logger('eth.vm.log')
log_vm_exit = get_logger('eth.vm.exit')
log_vm_op = get_logger('eth.vm.op')
log_vm_op_stack = get_logger('eth.vm.op.stack')
log_vm_op_memory = get_logger('eth.vm.op.memory')
log_vm_op_storage = get_logger('eth.vm.op.storage')

TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1
TT255 = 2 ** 255

for op in opcodes.opcodes:
    globals()["op_"+opcodes.opcodes[op][0]] = op

INVALID = -1


class CallData(object):

    def __init__(self, parent_memory, offset=0, size=None):
        self.data = parent_memory
        self.offset = offset
        self.size = len(self.data) if size is None else size
        self.rlimit = self.offset + self.size

    def extract_all(self):
        d = self.data[self.offset: self.offset + self.size]
        d += [0] * (self.size - len(d))
        return b''.join([ascii_chr(x) for x in d])

    def extract32(self, i):
        if i >= self.size:
            return 0
        o = self.data[self.offset + i: min(self.offset + i + 32, self.rlimit)]
        return utils.bytearray_to_int(o + [0] * (32 - len(o)))

    def extract_copy(self, mem, memstart, datastart, size):
        for i in range(min(size, self.size - datastart)):
            mem[memstart + i] = self.data[self.offset + datastart + i]
        for i in range(max(0, min(size, self.size - datastart)), size):
            mem[memstart + i] = 0


class Message(object):

    def __init__(self, sender, to, value, gas, data,
                 depth=0, code_address=None, is_create=False):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data
        self.depth = depth
        self.logs = []
        self.code_address = code_address
        self.is_create = is_create

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

end_breakpoints = [
    'JUMP', 'JUMPI', 'CALL', 'CALLCODE', 'CREATE', 'SUICIDE', 'STOP', 'RETURN', 'SUICIDE', 'INVALID', 'GAS', 'PC'
]

start_breakpoints = [
    'JUMPDEST', 'GAS', 'PC'
]


# Preprocesses code, and determines which locations are in the middle
# of pushdata and thus invalid
def preprocess_code(code):
    assert isinstance(code, bytes)
    code = memoryview(code).tolist()
    ops = {}
    cur_chunk = []
    cc_init_pos = 0
    cc_gas_consumption = 0
    cc_stack_change = 0
    cc_min_req_stack = 0
    cc_max_req_stack = 1024
    i = 0
    while i < len(code):
        op, in_args, out_args, fee = \
            copy.copy(opcodes.opcodes.get(code[i], ['INVALID', 0, 0, 0]))
        opcode, pushval = code[i], 0
        if op[:4] == 'PUSH':
            for j in range(int(op[4:])):
                i += 1
                byte = code[i] if i < len(code) else 0
                pushval = (pushval << 8) + byte
        i += 1
        if op == 'INVALID':
            opcode = -1
        cc_gas_consumption += fee
        cc_min_req_stack = max(cc_min_req_stack, -cc_stack_change + in_args)
        cc_max_req_stack = min(cc_max_req_stack, 1024 - cc_stack_change + in_args - out_args)
        cc_stack_change = cc_stack_change - in_args + out_args
        cur_chunk.append(opcode + (pushval << 8))
        if op in end_breakpoints or i >= len(code) or \
                opcodes.opcodes.get(code[i], ['INVALID'])[0] in start_breakpoints:
            ops[cc_init_pos] = [
                cc_gas_consumption,
                cc_min_req_stack,
                cc_max_req_stack,
                i
            ] + cur_chunk
            cur_chunk = []
            cc_init_pos = i
            cc_gas_consumption = 0
            cc_stack_change = 0
            cc_min_req_stack = 0
            cc_max_req_stack = 1024
    ops[i] = (0, 0, 1024, [0], 0)
    return ops


def mem_extend(mem, compustate, op, start, sz):
    if sz and utils.ceil32(start + sz) > len(mem):
        oldsize = len(mem) // 32
        old_totalfee = oldsize * opcodes.GMEMORY + \
            oldsize**2 // opcodes.GQUADRATICMEMDENOM
        newsize = utils.ceil32(start + sz) // 32
        # if newsize > 524288:
        #     raise Exception("Memory above 16 MB per call not supported by this VM")
        new_totalfee = newsize * opcodes.GMEMORY + \
            newsize**2 // opcodes.GQUADRATICMEMDENOM
        if old_totalfee < new_totalfee:
            memfee = new_totalfee - old_totalfee
            if compustate.gas < memfee:
                compustate.gas = 0
                return False
            compustate.gas -= memfee
            m_extend = (newsize - oldsize) * 32
            mem.extend([0] * m_extend)
    return True


def data_copy(compustate, size):
    if size:
        copyfee = opcodes.GCOPY * utils.ceil32(size) // 32
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

    s = time.time()
    op = None
    steps = 0
    _prevop = None  # for trace only

    while 1:
      # print('op: ', op, time.time() - s)
      # s = time.time()
      # stack size limit error
      if compustate.pc not in processed_code:
          return vm_exception('INVALID START POINT')

      _data = processed_code[compustate.pc]
      gas, min_stack, max_stack, compustate.pc = _data[:4]
      ops = _data[4:]

      # out of gas error
      if gas > compustate.gas:
        return vm_exception('OUT OF GAS')

      # insufficient stack error
      if not (min_stack <= len(compustate.stack) <= max_stack):
        return vm_exception('INCOMPATIBLE STACK LENGTH', min_stack=min_stack,
                            have=len(compustate.stack), max_stack=max_stack)

      # Apply operation
      compustate.gas -= gas

      for op in ops:

        if trace_vm:
            """
            This diverges from normal logging, as we use the logging namespace
            only to decide which features get logged in 'eth.vm.op'
            i.e. tracing can not be activated by activating a sub
            like 'eth.vm.op.stack'
            """
            trace_data = {}
            trace_data['stack'] = list(map(to_string, list(compustate.stack)))
            if _prevop in (op_MLOAD, op_MSTORE, op_MSTORE8, op_SHA3, op_CALL,
                           op_CALLCODE, op_CREATE, op_CALLDATACOPY, op_CODECOPY,
                           op_EXTCODECOPY):
                if len(compustate.memory) < 1024:
                    trace_data['memory'] = \
                        b''.join([encode_hex(ascii_chr(x)) for x
                                  in compustate.memory])
                else:
                    trace_data['sha3memory'] = \
                        encode_hex(utils.sha3(''.join([ascii_chr(x) for
                                              x in compustate.memory])))
            if _prevop in (op_SSTORE, op_SLOAD) or steps == 0:
                trace_data['storage'] = ext.log_storage(msg.to)
            # trace_data['gas'] = to_string(compustate.gas + fee)
            trace_data['inst'] = op
            trace_data['pc'] = to_string(compustate.pc - 1)
            if steps == 0:
                trace_data['depth'] = msg.depth
                trace_data['address'] = msg.to
            trace_data['op'] = op
            trace_data['steps'] = steps
            # if op[:4] == 'PUSH':
            #     trace_data['pushvalue'] = pushval
            log_vm_op.trace('vm', **trace_data)
            steps += 1
            _prevop = op

        # Invalid operation
        if op == INVALID:
            return vm_exception('INVALID OP', opcode=op)

        # Valid operations
        if op < 0x10:
            if op == op_STOP:
                return peaceful_exit('STOP', compustate.gas, [])
            elif op == op_ADD:
                stk.append((stk.pop() + stk.pop()) & TT256M1)
            elif op == op_SUB:
                stk.append((stk.pop() - stk.pop()) & TT256M1)
            elif op == op_MUL:
                stk.append((stk.pop() * stk.pop()) & TT256M1)
            elif op == op_DIV:
                s0, s1 = stk.pop(), stk.pop()
                stk.append(0 if s1 == 0 else s0 // s1)
            elif op == op_MOD:
                s0, s1 = stk.pop(), stk.pop()
                stk.append(0 if s1 == 0 else s0 % s1)
            elif op == op_SDIV:
                s0, s1 = utils.to_signed(stk.pop()), utils.to_signed(stk.pop())
                stk.append(0 if s1 == 0 else (abs(s0) // abs(s1) *
                                              (-1 if s0 * s1 < 0 else 1)) & TT256M1)
            elif op == op_SMOD:
                s0, s1 = utils.to_signed(stk.pop()), utils.to_signed(stk.pop())
                stk.append(0 if s1 == 0 else (abs(s0) % abs(s1) *
                                              (-1 if s0 < 0 else 1)) & TT256M1)
            elif op == op_ADDMOD:
                s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
                stk.append((s0 + s1) % s2 if s2 else 0)
            elif op == op_MULMOD:
                s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
                stk.append((s0 * s1) % s2 if s2 else 0)
            elif op == op_EXP:
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
            elif op == op_SIGNEXTEND:
                s0, s1 = stk.pop(), stk.pop()
                if s0 <= 31:
                    testbit = s0 * 8 + 7
                    if s1 & (1 << testbit):
                        stk.append(s1 | (TT256 - (1 << testbit)))
                    else:
                        stk.append(s1 & ((1 << testbit) - 1))
                else:
                    stk.append(s1)
        elif op < 0x20:
            if op == op_LT:
                stk.append(1 if stk.pop() < stk.pop() else 0)
            elif op == op_GT:
                stk.append(1 if stk.pop() > stk.pop() else 0)
            elif op == op_SLT:
                s0, s1 = utils.to_signed(stk.pop()), utils.to_signed(stk.pop())
                stk.append(1 if s0 < s1 else 0)
            elif op == op_SGT:
                s0, s1 = utils.to_signed(stk.pop()), utils.to_signed(stk.pop())
                stk.append(1 if s0 > s1 else 0)
            elif op == op_EQ:
                stk.append(1 if stk.pop() == stk.pop() else 0)
            elif op == op_ISZERO:
                stk.append(0 if stk.pop() else 1)
            elif op == op_AND:
                stk.append(stk.pop() & stk.pop())
            elif op == op_OR:
                stk.append(stk.pop() | stk.pop())
            elif op == op_XOR:
                stk.append(stk.pop() ^ stk.pop())
            elif op == op_NOT:
                stk.append(TT256M1 - stk.pop())
            elif op == op_BYTE:
                s0, s1 = stk.pop(), stk.pop()
                if s0 >= 32:
                    stk.append(0)
                else:
                    stk.append((s1 // 256 ** (31 - s0)) % 256)
        elif op < 0x40:
            if op == op_SHA3:
                s0, s1 = stk.pop(), stk.pop()
                compustate.gas -= opcodes.GSHA3WORD * (utils.ceil32(s1) // 32)
                if compustate.gas < 0:
                    return vm_exception('OOG PAYING FOR SHA3')
                if not mem_extend(mem, compustate, op, s0, s1):
                    return vm_exception('OOG EXTENDING MEMORY')
                data = b''.join(map(ascii_chr, mem[s0: s0 + s1]))
                stk.append(utils.big_endian_to_int(utils.sha3(data)))
            elif op == op_ADDRESS:
                stk.append(utils.coerce_to_int(msg.to))
            elif op == op_BALANCE:
                addr = utils.coerce_addr_to_hex(stk.pop() % 2**160)
                stk.append(ext.get_balance(addr))
            elif op == op_ORIGIN:
                stk.append(utils.coerce_to_int(ext.tx_origin))
            elif op == op_CALLER:
                stk.append(utils.coerce_to_int(msg.sender))
            elif op == op_CALLVALUE:
                stk.append(msg.value)
            elif op == op_CALLDATALOAD:
                stk.append(msg.data.extract32(stk.pop()))
            elif op == op_CALLDATASIZE:
                stk.append(msg.data.size)
            elif op == op_CALLDATACOPY:
                mstart, dstart, size = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, mstart, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                msg.data.extract_copy(mem, mstart, dstart, size)
            elif op == op_CODESIZE:
                stk.append(len(code))
            elif op == op_CODECOPY:
                start, s1, size = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, start, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                for i in range(size):
                    if s1 + i < len(code):
                        mem[start + i] = utils.safe_ord(code[s1 + i])
                    else:
                        mem[start + i] = 0
            elif op == op_GASPRICE:
                stk.append(ext.tx_gasprice)
            elif op == op_EXTCODESIZE:
                addr = utils.coerce_addr_to_hex(stk.pop() % 2**160)
                stk.append(len(ext.get_code(addr) or b''))
            elif op == op_EXTCODECOPY:
                addr = utils.coerce_addr_to_hex(stk.pop() % 2**160)
                start, s2, size = stk.pop(), stk.pop(), stk.pop()
                extcode = ext.get_code(addr) or b''
                assert utils.is_string(extcode)
                if not mem_extend(mem, compustate, op, start, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                for i in range(size):
                    if s2 + i < len(extcode):
                        mem[start + i] = utils.safe_ord(extcode[s2 + i])
                    else:
                        mem[start + i] = 0
        elif op < 0x50:
            if op == op_BLOCKHASH:
                stk.append(utils.big_endian_to_int(ext.block_hash(stk.pop())))
            elif op == op_COINBASE:
                stk.append(utils.big_endian_to_int(ext.block_coinbase))
            elif op == op_TIMESTAMP:
                stk.append(ext.block_timestamp)
            elif op == op_NUMBER:
                stk.append(ext.block_number)
            elif op == op_DIFFICULTY:
                stk.append(ext.block_difficulty)
            elif op == op_GASLIMIT:
                stk.append(ext.block_gas_limit)
        elif op < 0x60:
            if op == op_POP:
                stk.pop()
            elif op == op_MLOAD:
                s0 = stk.pop()
                if not mem_extend(mem, compustate, op, s0, 32):
                    return vm_exception('OOG EXTENDING MEMORY')
                data = 0
                for c in mem[s0: s0 + 32]:
                    data = (data << 8) + c
                stk.append(data)
            elif op == op_MSTORE:
                s0, s1 = stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, s0, 32):
                    return vm_exception('OOG EXTENDING MEMORY')
                v = s1
                for i in range(31, -1, -1):
                    mem[s0 + i] = v % 256
                    v //= 256
            elif op == op_MSTORE8:
                s0, s1 = stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, s0, 1):
                    return vm_exception('OOG EXTENDING MEMORY')
                mem[s0] = s1 % 256
            elif op == op_SLOAD:
                stk.append(ext.get_storage_data(msg.to, stk.pop()))
            elif op == op_SSTORE:
                s0, s1 = stk.pop(), stk.pop()
                if ext.get_storage_data(msg.to, s0):
                    gascost = opcodes.GSTORAGEMOD if s1 else opcodes.GSTORAGEKILL
                    refund = 0 if s1 else opcodes.GSTORAGEREFUND
                else:
                    gascost = opcodes.GSTORAGEADD if s1 else opcodes.GSTORAGEMOD
                    refund = 0
                if compustate.gas < gascost:
                    return vm_exception('OUT OF GAS')
                compustate.gas -= gascost
                ext.add_refund(refund)  # adds neg gascost as a refund if below zero
                ext.set_storage_data(msg.to, s0, s1)
            elif op == op_JUMP:
                compustate.pc = stk.pop()
                opnew = processed_code[compustate.pc][4] if \
                    compustate.pc in processed_code else op_STOP
                if opnew != op_JUMPDEST:
                    return vm_exception('BAD JUMPDEST')
            elif op == op_JUMPI:
                s0, s1 = stk.pop(), stk.pop()
                if s1:
                    compustate.pc = s0
                    opnew = processed_code[compustate.pc][4] if \
                        compustate.pc in processed_code else op_STOP
                    if opnew != op_JUMPDEST:
                        return vm_exception('BAD JUMPDEST')
            elif op == op_PC:
                stk.append(compustate.pc - 1)
            elif op == op_MSIZE:
                stk.append(len(mem))
            elif op == op_GAS:
                stk.append(compustate.gas)  # AFTER subtracting cost 1
        elif op_PUSH1 <= (op & 255) <= op_PUSH32:
            # Hide push value in high-order bytes of op
            stk.append(op >> 8)
        elif op_DUP1 <= op <= op_DUP16:
            depth = op - op_DUP1 + 1
            stk.append(stk[-depth])
        elif op_SWAP1 <= op <= op_SWAP16:
            depth = op - op_SWAP1 + 1
            temp = stk[-depth - 1]
            stk[-depth - 1] = stk[-1]
            stk[-1] = temp

        elif op_LOG0 <= op <= op_LOG4:
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
            depth = op - op_LOG0
            mstart, msz = stk.pop(), stk.pop()
            topics = [stk.pop() for x in range(depth)]
            compustate.gas -= msz * opcodes.GLOGBYTE
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            data = b''.join(map(ascii_chr, mem[mstart: mstart + msz]))
            ext.log(msg.to, topics, data)
            log_log.trace('LOG', to=msg.to, topics=topics, data=list(map(utils.safe_ord, data)))
            # print('LOG', msg.to, topics, list(map(ord, data)))

        elif op == op_CREATE:
            value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            if ext.get_balance(msg.to) >= value and msg.depth < 1024:
                cd = CallData(mem, mstart, msz)
                create_msg = Message(msg.to, b'', value, compustate.gas, cd, msg.depth + 1)
                o, gas, addr = ext.create(create_msg)
                if o:
                    stk.append(utils.coerce_to_int(addr))
                    compustate.gas = gas
                else:
                    stk.append(0)
                    compustate.gas = 0
            else:
                stk.append(0)
        elif op == op_CALL:
            gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                    not mem_extend(mem, compustate, op, memoutstart, memoutsz):
                return vm_exception('OOG EXTENDING MEMORY')
            to = utils.encode_int(to)
            to = ((b'\x00' * (32 - len(to))) + to)[12:]
            extra_gas = (not ext.account_exists(to)) * opcodes.GCALLNEWACCOUNT + \
                (value > 0) * opcodes.GCALLVALUETRANSFER
            submsg_gas = gas + opcodes.GSTIPEND * (value > 0)
            if compustate.gas < gas + extra_gas:
                return vm_exception('OUT OF GAS', needed=gas+extra_gas)
            if ext.get_balance(msg.to) >= value and msg.depth < 1024:
                compustate.gas -= (gas + extra_gas)
                cd = CallData(mem, meminstart, meminsz)
                call_msg = Message(msg.to, to, value, submsg_gas, cd,
                                   msg.depth + 1, code_address=to)
                result, gas, data = ext.msg(call_msg)
                if result == 0:
                    stk.append(0)
                else:
                    stk.append(1)
                    compustate.gas += gas
                    for i in range(min(len(data), memoutsz)):
                        mem[memoutstart + i] = data[i]
            else:
                compustate.gas -= (gas + extra_gas - submsg_gas)
                stk.append(0)
        elif op == op_CALLCODE:
            gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                    not mem_extend(mem, compustate, op, memoutstart, memoutsz):
                return vm_exception('OOG EXTENDING MEMORY')
            extra_gas = (value > 0) * opcodes.GCALLVALUETRANSFER
            submsg_gas = gas + opcodes.GSTIPEND * (value > 0)
            if compustate.gas < gas + extra_gas:
                return vm_exception('OUT OF GAS', needed=gas+extra_gas)
            if ext.get_balance(msg.to) >= value and msg.depth < 1024:
                compustate.gas -= (gas + extra_gas)
                to = utils.encode_int(to)
                to = ((b'\x00' * (32 - len(to))) + to)[12:]
                cd = CallData(mem, meminstart, meminsz)
                call_msg = Message(msg.to, msg.to, value, submsg_gas, cd,
                                   msg.depth + 1, code_address=to)
                result, gas, data = ext.msg(call_msg)
                if result == 0:
                    stk.append(0)
                else:
                    stk.append(1)
                    compustate.gas += gas
                    for i in range(min(len(data), memoutsz)):
                        mem[memoutstart + i] = data[i]
            else:
                compustate.gas -= (gas + extra_gas - submsg_gas)
                stk.append(0)
        elif op == op_RETURN:
            s0, s1 = stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, s0, s1):
                return vm_exception('OOG EXTENDING MEMORY')
            return peaceful_exit('RETURN', compustate.gas, mem[s0: s0 + s1])
        elif op == op_SUICIDE:
            to = utils.encode_int(stk.pop())
            to = ((b'\x00' * (32 - len(to))) + to)[12:]
            xfer = ext.get_balance(msg.to)
            ext.set_balance(to, ext.get_balance(to) + xfer)
            ext.set_balance(msg.to, 0)
            ext.add_suicide(msg.to)
            # print('suiciding %s %s %d' % (msg.to, to, xfer))
            return 1, compustate.gas, []

        # this is slow!
        # for a in stk:
        #     assert is_numeric(a), (op, stk)
        #     assert a >= 0 and a < 2**256, (a, op, stk)
