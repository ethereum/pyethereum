import copy
import opcodes
#  ####### dev hack flags ###############

verify_stack_after_op = False

#  ######################################
import sys

from ethereum.abi import is_numeric
import copy
import time
from ethereum.slogging import get_logger
from rlp.utils import encode_hex, ascii_chr
from utils import to_string, shardify, int_to_addr, encode_int32, ADDR_BASE_BYTES
import utils
import numpy

from config import BLOCKHASHES, STATEROOTS, BLKNUMBER, CASPER, GASLIMIT, NULL_SENDER, ETHER, PROPOSER, TXGAS, MAXSHARDS, EXECUTION_STATE, LOG, RNGSEEDS, CREATOR

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
                 left_bound=0, right_bound=MAXSHARDS,
                 depth=0, code_address=None, is_create=False,
                 transfers_value=True):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data
        self.depth = depth
        self.left_bound = left_bound
        self.right_bound = right_bound
        self.logs = []
        self.code_address = code_address
        self.is_create = is_create
        self.transfers_value = transfers_value

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

def validate_and_get_address(addr_int, msg):
    if msg.left_bound <= (addr_int // 2**160) % MAXSHARDS < msg.right_bound:
        return int_to_addr(addr_int)
    print 'FAIL, left: %d, at: %d, right: %d' % (msg.left_bound, (addr_int // 2**160), msg.right_bound)
    return False

end_breakpoints = [
    'JUMP', 'JUMPI', 'CALL', 'CALLCODE', 'CALLSTATIC', 'CREATE', 'SUICIDE', 'STOP', 'RETURN', 'SUICIDE', 'INVALID', 'GAS', 'PC', 'BREAKPOINT'
]

start_breakpoints = [
    'JUMPDEST', 'GAS', 'PC', 'BREAKPOINT'
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
    ops[i] = [0, 0, 1024, i, 0]
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
    print 'EXCEPTION', error, kargs
    log_vm_exit.trace('EXCEPTION', cause=error, **kargs)
    return 0, 0, []


def peaceful_exit(cause, gas, data, **kargs):
    log_vm_exit.trace('EXIT', cause=cause, **kargs)
    return 1, gas, data

code_cache = {}


def vm_execute(ext, msg, code, breaking=False):
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

    _EXSTATE = shardify(EXECUTION_STATE, msg.left_bound)
    _LOG = shardify(LOG, msg.left_bound)
    _CREATOR = shardify(CREATOR, msg.left_bound)

    # print 'starting to run vm', msg.to.encode('hex')
    while 1:
      # print 'op: ', op, time.time() - s
      # s = time.time()
      # stack size limit error
      if compustate.pc not in processed_code:
          # print processed_code, map(ord, code), compustate.pc
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
            # if _prevop in (op_SSTORE, op_SLOAD) or steps == 0:
            #     trace_data['storage'] = ext.log_storage(msg.to)
            trace_data['approx_gas'] = to_string(compustate.gas)
            trace_data['inst'] = op % 256
            trace_data['pc'] = to_string(compustate.pc - 1)
            if steps == 0:
                trace_data['depth'] = msg.depth
                trace_data['address'] = msg.to
            trace_data['op'] = op
            trace_data['steps'] = steps
            # if op[:4] == 'PUSH':
            #     trace_data['pushvalue'] = pushval
            # print trace_data
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
                addr = validate_and_get_address(stk.pop(), msg)
                if addr is False:
                    return vm_exception('OUT OF RANGE')
                stk.append(utils.big_endian_to_int(ext.get_storage(ETHER, addr)))
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
            elif op == op_EXTCODESIZE:
                addr = validate_and_get_address(stk.pop(), msg)
                if addr is False:
                    return vm_exception('OUT OF RANGE')
                stk.append(len(ext.get_storage_at(addr, '') or b''))
            elif op == op_EXTCODECOPY:
                addr = validate_and_get_address(stk.pop(), msg)
                if addr is False:
                    return vm_exception('OUT OF RANGE')
                start, s2, size = stk.pop(), stk.pop(), stk.pop()
                extcode = ext.get_storage_at(addr, b'') or b''
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
            elif op == op_MCOPY:
                to, frm, size = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, to, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not mem_extend(mem, compustate, op, frm, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                data = mem[frm: frm + size]
                for i in range(size):
                    mem[to + i] = data[i]
        elif op < 0x50:
            if op == op_BLOCKHASH:
                stk.append(utils.big_endian_to_int(ext.get_storage(BLOCKHASHES, stk.pop())))
            elif op == op_COINBASE:
                stk.append(utils.big_endian_to_int(ext.get_storage(PROPOSER, '\x00' * 32)))
            elif op == op_NUMBER:
                stk.append(utils.big_endian_to_int(ext.get_storage(BLKNUMBER, '\x00' * 32)))
            elif op == op_DIFFICULTY:
                stk.append(ext.block_difficulty)
            elif op == op_GASLIMIT:
                stk.append(GASLIMIT)
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
                stk.append(utils.big_endian_to_int(ext.get_storage(msg.to, stk.pop())))
            elif op == op_SSTORE or op == op_SSTOREEXT:
                if op == op_SSTOREEXT:
                    shard = stk.pop()
                    if not validate_and_get_address(256**ADDR_BYTES * shard):
                        return vm_exception('OUT OF RANGE')
                    toaddr = shardify(msg.to, shard)
                else:   
                    toaddr = msg.to
                s0, s1 = stk.pop(), stk.pop()
                if ext.get_storage(msg.to, s0):
                    gascost = opcodes.GSTORAGEMOD if s1 else opcodes.GSTORAGEKILL
                    refund = 0 if s1 else opcodes.GSTORAGEREFUND
                else:
                    gascost = opcodes.GSTORAGEADD if s1 else opcodes.GSTORAGEMOD
                    refund = 0
                if toaddr == CASPER:
                    gascost /= 2
                if compustate.gas < gascost:
                    return vm_exception('OUT OF GAS')
                compustate.gas -= gascost
                ext.set_storage(toaddr, s0, s1)
                # Copy code to new shard
                if op == op_SSTOREEXT:
                    if not ext.get_storage(toaddr, ''):
                        ext.set_storage(toaddr, ext.get_storage(msg.to))
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
            elif op == op_SLOADEXT:
                shard, key = stk.pop(), stk.pop()
                if not validate_and_get_address(256**ADDR_BYTES * shard):
                    return vm_exception('OUT OF RANGE')
                toaddr = shardify(msg.to, shard)
                stk.append(utils.big_endian_to_int(ext.get_storage(toaddr, key)))
                if not ext.get_storage(toaddr, ''):
                    ext.set_storage(toaddr, ext.get_storage(msg.to))
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
            depth = op - op_LOG0
            mstart, msz = stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            topics = [stk.pop() if i < depth else 0 for i in range(4)]
            log_data = map(ord, ''.join(map(encode_int32, topics))) + mem[mstart: mstart + msz]
            print topics, mem[mstart: mstart + msz]
            # print 'ld', log_data, msz
            log_data = CallData(log_data, 0, len(log_data))
            log_gas = opcodes.GLOGBYTE * msz + opcodes.GLOGBASE + \
                len(topics) * opcodes.GLOGTOPIC
            compustate.gas -= log_gas
            if compustate.gas < log_gas:
                return vm_exception('OUT OF GAS', needed=log_gas)
            log_msg = Message(msg.to, _LOG, 0, log_gas, log_data,
                              depth=msg.depth + 1, code_address=_LOG)
            result, gas, data = ext.msg(log_msg, '')
            # print '###log###', mstart, msz, topics
            if 3141592653589 in [mstart, msz] + topics:
                raise Exception("Testing exception triggered!")

        elif op == op_CREATE:
            value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            code = mem[mstart:msz]
            crate_msg = Message(msg.to, _CREATOR, value, msg.gas - 20000, code,
                              depth=msg.depth + 1, code_address=_CREATOR)
            result, gas, data = ext.msg(create_msg, '')
            if result:
                addr = shardify(sha3(msg.to[-ADDR_BASE_BYTES:] + code)[32-ADDR_BASE_BYTES:], left_bound)
                stk.append(big_endian_to_int(addr))
            else:
                stk.append(0)
        elif op == op_CALL:
            gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, meminstart, meminsz):
                return vm_exception('OOG EXTENDING MEMORY')
            to = validate_and_get_address(to, msg)
            if to is False:
                return vm_exception('OUT OF RANGE')
            extra_gas = (value > 0) * opcodes.GCALLVALUETRANSFER
            submsg_gas = gas + opcodes.GSTIPEND * (value > 0)
            if compustate.gas < gas + extra_gas:
                return vm_exception('OUT OF GAS', needed=gas+extra_gas)
            if utils.big_endian_to_int(ext.get_storage(ETHER, msg.to)) >= value and msg.depth < 1024:
                compustate.gas -= (gas + extra_gas)
                cd = CallData(mem, meminstart, meminsz)
                call_msg = Message(msg.to, to, value, submsg_gas, cd,
                                   depth=msg.depth + 1, code_address=to)
                codehash = ext.get_storage(to, '')
                result, gas, data = ext.msg(call_msg, ext.unhash(codehash) if codehash else '')
                if result == 0:
                    stk.append(0)
                else:
                    stk.append(1)
                    if not mem_extend(mem, compustate, op, memoutstart, min(len(data), memoutsz)):
                        return vm_exception('OOG EXTENDING MEMORY')
                    compustate.gas += gas
                    for i in range(min(len(data), memoutsz)):
                        mem[memoutstart + i] = data[i]
            else:
                compustate.gas -= (gas + extra_gas - submsg_gas)
                stk.append(0)
        elif op == op_CALLCODE or op == op_DELEGATECALL:
            if op == op_CALLCODE:
                gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                    stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            else:
                gas, to, meminstart, meminsz, memoutstart, memoutsz = \
                    stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
                value = 0
            if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                    not mem_extend(mem, compustate, op, memoutstart, memoutsz):
                return vm_exception('OOG EXTENDING MEMORY')
            extra_gas = (value > 0) * opcodes.GCALLVALUETRANSFER
            submsg_gas = gas + opcodes.GSTIPEND * (value > 0)
            if compustate.gas < gas + extra_gas:
                return vm_exception('OUT OF GAS', needed=gas+extra_gas)
            if utils.big_endian_to_int(ext.get_storage(ETHER, msg.to)) and msg.depth < 1024:
                compustate.gas -= (gas + extra_gas)
                to = validate_and_get_address(to, msg)
                if to is False:
                    return vm_exception('OUT OF RANGE')
                cd = CallData(mem, meminstart, meminsz)
                if op == op_CALLCODE:
                    call_msg = Message(msg.to, msg.to, value, submsg_gas, cd,
                                       depth=msg.depth + 1, code_address=to)
                elif op == op_DELEGATECALL:
                    call_msg = Message(msg.sender, msg.to, value, submsg_gas, cd,
                                       depth=msg.depth + 1, code_address=to, transfers_value=False)
                codehash = ext.get_storage(to, '')
                result, gas, data = ext.msg(call_msg, ext.unhash(codehash) if codehash else '')
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
        elif op == op_CALLSTATIC:
            submsg_gas, codestart, codesz, datastart, datasz, outstart, outsz = [stk.pop() for i in range(7)]
            if not mem_extend(mem, compustate, op, codestart, codesz) or \
                    not mem_extend(mem, compustate, op, datastart, datasz):
                return vm_exception('OOG EXTENDING MEMORY')
            if compustate.gas < submsg_gas:
                return vm_exception('OUT OF GAS', needed=submsg_gas)
            compustate.gas -= submsg_gas
            cd = CallData(mem, datastart, datasz)
            call_msg = Message(msg.sender, msg.to, 0, submsg_gas, cd, depth=msg.depth + 1)
            result, gas, data = ext.static_msg(call_msg, ''.join([chr(x) for x in mem[codestart:codestart + codesz]]))
            if result == 0:
                stk.append(0)
            else:
                stk.append(1)
                compustate.gas += gas
                if not mem_extend(mem, compustate, op, outstart, outsz):
                    return vm_exception('OOG EXTENDING MEMORY')
                for i in range(min(len(data), outsz)):
                    mem[outstart + i] = data[i]
        elif op == op_RETURN:
            s0, s1 = stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, s0, s1):
                return vm_exception('OOG EXTENDING MEMORY')
            return peaceful_exit('RETURN', compustate.gas, mem[s0: s0 + s1])
        elif op == op_SLOADBYTES or op == op_SLOADEXTBYTES:
            if op == op_SLOADEXTBYTES:
                shard = stk.pop()
                if not validate_and_get_address(256**ADDR_BYTES * shard):
                    return vm_exception('OUT OF RANGE')
                toaddr = shardify(msg.to, shard)
            else:
                toaddr = msg.to
            s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
            data = map(ord, ext.get_storage(toaddr, s0))
            if not mem_extend(mem, compustate, op, s1, min(len(data), s2)):
                return vm_exception('OOG EXTENDING MEMORY')
            for i in range(min(len(data), s2)):
                mem[s1 + i] = data[i]
            # Copy code to new shard
            if op == op_SLOADEXTBYTES:
                if not ext.get_storage(toaddr, ''):
                    ext.set_storage(toaddr, ext.get_storage(msg.to))
        elif op == op_BREAKPOINT:
            if breaking:
                return peaceful_exit('RETURN', compustate.gas, mem)
            else:
                pass
        elif op == op_RNGSEED:
            stk.append(utils.big_endian_to_int(ext.get_storage(RNGSEEDS, stk.pop())))
        elif op == op_SSIZEEXT:
            shard, key = stk.pop(), stk.pop()
            if not validate_and_get_address(256**ADDR_BYTES * shard):
                return vm_exception('OUT OF RANGE')
            toaddr = shardify(msg.to, shard)
            stk.append(len(ext.get_storage(toaddr, key)))
            if not ext.get_storage(toaddr, ''):
                ext.set_storage(toaddr, ext.get_storage(msg.to))
        elif op == op_SSTOREBYTES or op == op_SSTOREEXTBYTES:
            if op == op_SSTOREEXTBYTES:
                shard = stk.pop()
                if not validate_and_get_address(256**ADDR_BYTES * shard):
                    return vm_exception('OUT OF RANGE')
                toaddr = shardify(msg.to, shard)
            else:
                toaddr = msg.to
            s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, s1, s2):
                return vm_exception('OOG EXTENDING MEMORY')
            data = ''.join(map(chr, mem[s1: s1 + s2]))
            ext.set_storage(toaddr, s0, data)
            # Copy code to new shard
            if op == op_SSTOREEXTBYTES:
                if not ext.get_storage(toaddr, ''):
                    ext.set_storage(toaddr, ext.get_storage(msg.to))
        elif op == op_SSIZE:
            stk.append(len(ext.get_storage(msg.to, stk.pop())))
        elif op == op_STATEROOT:
            stk.append(utils.big_endian_to_int(ext.get_storage(STATEROOTS, stk.pop())))
        elif op == op_TXGAS:
            stk.append(utils.big_endian_to_int(ext.get_storage(_EXSTATE, TXGAS)))
        elif op == op_SUICIDE:
            to = validate_and_get_address(stk.pop(), msg)
            if to is False:
                return vm_exception('OUT OF RANGE')
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
