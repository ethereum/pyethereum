####### dev hack flags ###############

verify_stack_after_op = False

#  ######################################
import sys
sys.setrecursionlimit(10000)

import copy

from ethereum.utils import encode_hex, ascii_chr
from ethereum import utils
from ethereum.abi import is_numeric
from ethereum import opcodes
from ethereum.slogging import get_logger
from ethereum.utils import to_string, encode_int, zpad, bytearray_to_bytestr, safe_ord

if sys.version_info.major == 2:
    from repoze.lru import lru_cache
else:
    from functools import lru_cache

log_log = get_logger('eth.vm.log')
log_msg = get_logger('eth.pb.msg')
log_vm_exit = get_logger('eth.vm.exit')
log_vm_op = get_logger('eth.vm.op')
log_vm_op_stack = get_logger('eth.vm.op.stack')
log_vm_op_memory = get_logger('eth.vm.op.memory')
log_vm_op_storage = get_logger('eth.vm.op.storage')

TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1
TT255 = 2 ** 255

MAX_DEPTH = 1024


# Wrapper to store call data. This is needed because it is possible to
# call a contract N times with N bytes of data with a gas cost of O(N);
# if implemented naively this would require O(N**2) bytes of data
# copying. Instead we just copy the reference to the parent memory
# slice plus the start and end of the slice
class CallData(object):

    def __init__(self, parent_memory, offset=0, size=None):
        self.data = parent_memory
        self.offset = offset
        self.size = len(self.data) if size is None else size
        self.rlimit = self.offset + self.size

    # Convert calldata to bytes
    def extract_all(self):
        d = self.data[self.offset: self.offset + self.size]
        d.extend(bytearray(self.size - len(d)))
        return bytes(bytearray(d))

    # Extract 32 bytes as integer
    def extract32(self, i):
        if i >= self.size:
            return 0
        o = self.data[self.offset + i: min(self.offset + i + 32, self.rlimit)]
        o.extend(bytearray(32 - len(o)))
        return utils.bytearray_to_int(o)

    # Extract a slice and copy it to memory
    def extract_copy(self, mem, memstart, datastart, size):
        for i in range(size):
            if datastart + i < self.size:
                mem[memstart + i] = self.data[self.offset + datastart + i]
            else:
                mem[memstart + i] = 0


# Stores a message object, including context data like sender,
# destination, gas, whether or not it is a STATICCALL, etc
class Message(object):

    def __init__(self, sender, to, value=0, gas=1000000, data='', depth=0,
                 code_address=None, is_create=False, transfers_value=True, static=False):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = CallData(list(map(utils.safe_ord, data))) if isinstance(
            data, (str, bytes)) else data
        self.depth = depth
        self.logs = []
        self.code_address = to if code_address is None else code_address
        self.is_create = is_create
        self.transfers_value = transfers_value
        self.static = static

    def __repr__(self):
        return '<Message(to:%s...)>' % self.to[:8]


# Virtual machine state of the current EVM instance
class Compustate():

    def __init__(self, **kwargs):
        self.memory = bytearray()
        self.stack = []
        self.steps = 0
        self.pc = 0
        self.gas = 0

        self.prev_memory = bytearray()
        self.prev_stack = []
        self.prev_pc = 0
        self.prev_gas = 0
        self.prev_prev_op = None
        self.last_returned = bytearray()

        for kw in kwargs:
            setattr(self, kw, kwargs[kw])

    def reset_prev(self):
        self.prev_memory = copy.copy(self.memory)
        self.prev_stack = copy.copy(self.stack)
        self.prev_pc = self.pc
        self.prev_gas = self.gas


# Preprocesses code, and determines which locations are in the middle
# of pushdata and thus invalid
@lru_cache(128)
def preprocess_code(code):
    o = 0
    i = 0
    pushcache = {}
    code = code + b'\x00' * 32
    while i < len(code) - 32:
        codebyte = safe_ord(code[i])
        if codebyte == 0x5b:
            o |= 1 << i
        if 0x60 <= codebyte <= 0x7f:
            pushcache[i] = utils.big_endian_to_int(
                code[i + 1: i + codebyte - 0x5e])
            i += codebyte - 0x5e
        else:
            i += 1
    return o, pushcache


# Extends memory, and pays gas for it
def mem_extend(mem, compustate, op, start, sz):
    if sz and start + sz > len(mem):
        oldsize = len(mem) // 32
        old_totalfee = oldsize * opcodes.GMEMORY + \
            oldsize ** 2 // opcodes.GQUADRATICMEMDENOM
        newsize = utils.ceil32(start + sz) // 32
        new_totalfee = newsize * opcodes.GMEMORY + \
            newsize**2 // opcodes.GQUADRATICMEMDENOM
        memfee = new_totalfee - old_totalfee
        if compustate.gas < memfee:
            compustate.gas = 0
            return False
        compustate.gas -= memfee
        m_extend = (newsize - oldsize) * 32
        mem.extend(bytearray(m_extend))
    return True


# Pays gas for copying data
def data_copy(compustate, size):
    return eat_gas(compustate, opcodes.GCOPY * utils.ceil32(size) // 32)


# Consumes a given amount of gas
def eat_gas(compustate, amount):
    if compustate.gas < amount:
        compustate.gas = 0
        return False
    else:
        compustate.gas -= amount
        return True


# Used to compute maximum amount of gas for child calls
def all_but_1n(x, n):
    return x - x // n


# Throws a VM exception
def vm_exception(error, **kargs):
    log_vm_exit.trace('EXCEPTION', cause=error, **kargs)
    return 0, 0, []


# Peacefully exits the VM
def peaceful_exit(cause, gas, data, **kargs):
    log_vm_exit.trace('EXIT', cause=cause, **kargs)
    return 1, gas, data


# Exits with the REVERT opcode
def revert(gas, data, **kargs):
    log_vm_exit.trace('REVERT', **kargs)
    return 0, gas, data


def vm_trace(ext, msg, compustate, opcode, pushcache, tracer=log_vm_op):
    """
    This diverges from normal logging, as we use the logging namespace
    only to decide which features get logged in 'eth.vm.op'
    i.e. tracing can not be activated by activating a sub
    like 'eth.vm.op.stack'
    """

    op, in_args, out_args, fee = opcodes.opcodes[opcode]

    trace_data = {}
    trace_data['stack'] = list(map(to_string, list(compustate.prev_stack)))
    if compustate.prev_prev_op in ('MLOAD', 'MSTORE', 'MSTORE8', 'SHA3', 'CALL',
                   'CALLCODE', 'CREATE', 'CALLDATACOPY', 'CODECOPY',
                   'EXTCODECOPY'):
        if len(compustate.prev_memory) < 4096:
            trace_data['memory'] = \
                ''.join([encode_hex(ascii_chr(x)) for x
                          in compustate.prev_memory])
        else:
            trace_data['sha3memory'] = \
                encode_hex(utils.sha3(b''.join([ascii_chr(x) for
                                      x in compustate.prev_memory])))
    if compustate.prev_prev_op in ('SSTORE',) or compustate.steps == 0:
        trace_data['storage'] = ext.log_storage(msg.to)
    trace_data['gas'] = to_string(compustate.prev_gas)
    trace_data['gas_cost'] = to_string(compustate.prev_gas - compustate.gas)
    trace_data['fee'] = fee
    trace_data['inst'] = opcode
    trace_data['pc'] = to_string(compustate.prev_pc)
    if compustate.steps == 0:
        trace_data['depth'] = msg.depth
        trace_data['address'] = msg.to
    trace_data['steps'] = compustate.steps
    trace_data['depth'] = msg.depth
    if op[:4] == 'PUSH':
        print(repr(pushcache))
        trace_data['pushvalue'] = pushcache[compustate.prev_pc]
    tracer.trace('vm', op=op, **trace_data)
    compustate.steps += 1
    compustate.prev_prev_op = op


# Main function
def vm_execute(ext, msg, code):
    # precompute trace flag
    # if we trace vm, we're in slow mode anyway
    trace_vm = log_vm_op.is_active('trace')

    # Initialize stack, memory, program counter, etc
    compustate = Compustate(gas=msg.gas)
    stk = compustate.stack
    mem = compustate.memory

    # Compute
    jumpdest_mask, pushcache = preprocess_code(code)
    codelen = len(code)

    # For tracing purposes
    op = None
    _prevop = None
    steps = 0
    while compustate.pc < codelen:

        opcode = safe_ord(code[compustate.pc])

        # Invalid operation
        if opcode not in opcodes.opcodes:
            return vm_exception('INVALID OP', opcode=opcode)

        if opcode in opcodes.opcodesMetropolis and not ext.post_metropolis_hardfork():
            return vm_exception('INVALID OP (not yet enabled)', opcode=opcode)

        op, in_args, out_args, fee = opcodes.opcodes[opcode]

        # Apply operation
        if trace_vm:
            compustate.reset_prev()
        compustate.gas -= fee
        compustate.pc += 1

        # Tracing
        if trace_vm:
            """
            This diverges from normal logging, as we use the logging namespace
            only to decide which features get logged in 'eth.vm.op'
            i.e. tracing can not be activated by activating a sub
            like 'eth.vm.op.stack'
            """
            trace_data = {}
            trace_data['stack'] = list(map(to_string, list(compustate.stack)))
            if _prevop in ('MLOAD', 'MSTORE', 'MSTORE8', 'SHA3', 'CALL',
                           'CALLCODE', 'CREATE', 'CALLDATACOPY', 'CODECOPY',
                           'EXTCODECOPY'):
                if len(compustate.memory) < 4096:
                    trace_data['memory'] = \
                        ''.join([encode_hex(ascii_chr(x)) for x
                                 in compustate.memory])
                else:
                    trace_data['sha3memory'] = \
                        encode_hex(utils.sha3(b''.join([ascii_chr(x) for
                                                        x in compustate.memory])))
            if _prevop in ('SSTORE',) or steps == 0:
                trace_data['storage'] = ext.log_storage(msg.to)
            trace_data['gas'] = to_string(compustate.gas + fee)
            trace_data['inst'] = opcode
            trace_data['pc'] = to_string(compustate.pc - 1)
            if steps == 0:
                trace_data['depth'] = msg.depth
                trace_data['address'] = msg.to
            trace_data['steps'] = steps
            trace_data['depth'] = msg.depth
            if op[:4] == 'PUSH':
                trace_data['pushvalue'] = pushcache[compustate.pc - 1]
            log_vm_op.trace('vm', op=op, **trace_data)
            steps += 1
            _prevop = op

        # out of gas error
        if compustate.gas < 0:
            return vm_exception('OUT OF GAS')

        # empty stack error
        if in_args > len(compustate.stack):
            return vm_exception('INSUFFICIENT STACK',
                                op=op, needed=to_string(in_args),
                                available=to_string(len(compustate.stack)))

        # overfull stack error
        if len(compustate.stack) - in_args + out_args > 1024:
            return vm_exception('STACK SIZE LIMIT EXCEEDED',
                                op=op,
                                pre_height=to_string(len(compustate.stack)))

        # Valid operations
        # Pushes first because they are very frequent
        if 0x60 <= opcode <= 0x7f:
            stk.append(pushcache[compustate.pc - 1])
            # Move 1 byte forward for 0x60, up to 32 bytes for 0x7f
            compustate.pc += opcode - 0x5f
        # Arithmetic
        elif opcode < 0x10:
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
                stk.append(0 if s1 == 0 else s0 // s1)
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
                if ext.post_spurious_dragon_hardfork():
                    expfee += opcodes.EXP_SUPPLEMENTAL_GAS * nbytes
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
        # Comparisons
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
                    stk.append((s1 // 256 ** (31 - s0)) % 256)
        # SHA3 and environment info
        elif opcode < 0x40:
            if op == 'SHA3':
                s0, s1 = stk.pop(), stk.pop()
                compustate.gas -= opcodes.GSHA3WORD * (utils.ceil32(s1) // 32)
                if compustate.gas < 0:
                    return vm_exception('OOG PAYING FOR SHA3')
                if not mem_extend(mem, compustate, op, s0, s1):
                    return vm_exception('OOG EXTENDING MEMORY')
                data = bytearray_to_bytestr(mem[s0: s0 + s1])
                stk.append(utils.big_endian_to_int(utils.sha3(data)))
            elif op == 'ADDRESS':
                stk.append(utils.coerce_to_int(msg.to))
            elif op == 'BALANCE':
                if ext.post_anti_dos_hardfork():
                    if not eat_gas(compustate,
                                   opcodes.BALANCE_SUPPLEMENTAL_GAS):
                        return vm_exception("OUT OF GAS")
                addr = utils.coerce_addr_to_hex(stk.pop() % 2**160)
                stk.append(ext.get_balance(addr))
            elif op == 'ORIGIN':
                stk.append(utils.coerce_to_int(ext.tx_origin))
            elif op == 'CALLER':
                stk.append(utils.coerce_to_int(msg.sender))
            elif op == 'CALLVALUE':
                stk.append(msg.value)
            elif op == 'CALLDATALOAD':
                stk.append(msg.data.extract32(stk.pop()))
            elif op == 'CALLDATASIZE':
                stk.append(msg.data.size)
            elif op == 'CALLDATACOPY':
                mstart, dstart, size = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, mstart, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                msg.data.extract_copy(mem, mstart, dstart, size)
            elif op == 'CODESIZE':
                stk.append(codelen)
            elif op == 'CODECOPY':
                mstart, dstart, size = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, mstart, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                for i in range(size):
                    if dstart + i < codelen:
                        mem[mstart + i] = safe_ord(code[dstart + i])
                    else:
                        mem[mstart + i] = 0
            elif op == 'RETURNDATACOPY':
                mstart, dstart, size = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, mstart, size):
                    return vm_exception('OOG EXTENDING MEMORY')
                if not data_copy(compustate, size):
                    return vm_exception('OOG COPY DATA')
                if dstart + size > len(compustate.last_returned):
                    return vm_exception('RETURNDATACOPY out of range')
                mem[mstart: mstart + size] = compustate.last_returned[dstart: dstart + size]
            elif op == 'RETURNDATASIZE':
                stk.append(len(compustate.last_returned))
            elif op == 'GASPRICE':
                stk.append(ext.tx_gasprice)
            elif op == 'EXTCODESIZE':
                if ext.post_anti_dos_hardfork():
                    if not eat_gas(compustate,
                                   opcodes.EXTCODELOAD_SUPPLEMENTAL_GAS):
                        return vm_exception("OUT OF GAS")
                addr = utils.coerce_addr_to_hex(stk.pop() % 2**160)
                stk.append(len(ext.get_code(addr) or b''))
            elif op == 'EXTCODECOPY':
                if ext.post_anti_dos_hardfork():
                    if not eat_gas(compustate,
                                   opcodes.EXTCODELOAD_SUPPLEMENTAL_GAS):
                        return vm_exception("OUT OF GAS")
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
                        mem[start + i] = safe_ord(extcode[s2 + i])
                    else:
                        mem[start + i] = 0
        # Block info
        elif opcode < 0x50:
            if op == 'BLOCKHASH':
                if ext.post_constantinople_hardfork() and False:
                    bh_addr = ext.blockhash_store
                    stk.append(ext.get_storage_data(bh_addr, stk.pop()))
                else:
                    stk.append(
                        utils.big_endian_to_int(
                            ext.block_hash(
                                stk.pop())))
            elif op == 'COINBASE':
                stk.append(utils.big_endian_to_int(ext.block_coinbase))
            elif op == 'TIMESTAMP':
                stk.append(ext.block_timestamp)
            elif op == 'NUMBER':
                stk.append(ext.block_number)
            elif op == 'DIFFICULTY':
                stk.append(ext.block_difficulty)
            elif op == 'GASLIMIT':
                stk.append(ext.block_gas_limit)
        # VM state manipulations
        elif opcode < 0x60:
            if op == 'POP':
                stk.pop()
            elif op == 'MLOAD':
                s0 = stk.pop()
                if not mem_extend(mem, compustate, op, s0, 32):
                    return vm_exception('OOG EXTENDING MEMORY')
                stk.append(utils.bytes_to_int(mem[s0: s0 + 32]))
            elif op == 'MSTORE':
                s0, s1 = stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, s0, 32):
                    return vm_exception('OOG EXTENDING MEMORY')
                mem[s0: s0 + 32] = utils.encode_int32(s1)
            elif op == 'MSTORE8':
                s0, s1 = stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, s0, 1):
                    return vm_exception('OOG EXTENDING MEMORY')
                mem[s0] = s1 % 256
            elif op == 'SLOAD':
                if ext.post_anti_dos_hardfork():
                    if not eat_gas(compustate, opcodes.SLOAD_SUPPLEMENTAL_GAS):
                        return vm_exception("OUT OF GAS")
                stk.append(ext.get_storage_data(msg.to, stk.pop()))
            elif op == 'SSTORE':
                s0, s1 = stk.pop(), stk.pop()
                if msg.static:
                    return vm_exception(
                        'Cannot SSTORE inside a static context')
                if ext.get_storage_data(msg.to, s0):
                    gascost = opcodes.GSTORAGEMOD if s1 else opcodes.GSTORAGEKILL
                    refund = 0 if s1 else opcodes.GSTORAGEREFUND
                else:
                    gascost = opcodes.GSTORAGEADD if s1 else opcodes.GSTORAGEMOD
                    refund = 0
                if compustate.gas < gascost:
                    return vm_exception('OUT OF GAS')
                compustate.gas -= gascost
                # adds neg gascost as a refund if below zero
                ext.add_refund(refund)
                ext.set_storage_data(msg.to, s0, s1)
            elif op == 'JUMP':
                compustate.pc = stk.pop()
                if compustate.pc >= codelen or not (
                        (1 << compustate.pc) & jumpdest_mask):
                    return vm_exception('BAD JUMPDEST')
            elif op == 'JUMPI':
                s0, s1 = stk.pop(), stk.pop()
                if s1:
                    compustate.pc = s0
                    if compustate.pc >= codelen or not (
                            (1 << compustate.pc) & jumpdest_mask):
                        return vm_exception('BAD JUMPDEST')
            elif op == 'PC':
                stk.append(compustate.pc - 1)
            elif op == 'MSIZE':
                stk.append(len(mem))
            elif op == 'GAS':
                stk.append(compustate.gas)  # AFTER subtracting cost 1
        # DUPn (eg. DUP1: a b c -> a b c c, DUP3: a b c -> a b c a)
        elif op[:3] == 'DUP':
            # 0x7f - opcode is a negative number, -1 for 0x80 ... -16 for 0x8f
            stk.append(stk[0x7f - opcode])
        # SWAPn (eg. SWAP1: a b c d -> a b d c, SWAP3: a b c d -> d b c a)
        elif op[:4] == 'SWAP':
            # 0x8e - opcode is a negative number, -2 for 0x90 ... -17 for 0x9f
            temp = stk[0x8e - opcode]
            stk[0x8e - opcode] = stk[-1]
            stk[-1] = temp
        # Logs (aka "events")
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
            compustate.gas -= msz * opcodes.GLOGBYTE
            if msg.static:
                return vm_exception('Cannot LOG inside a static context')
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            data = bytearray_to_bytestr(mem[mstart: mstart + msz])
            ext.log(msg.to, topics, data)
            log_log.trace('LOG', to=msg.to, topics=topics,
                          data=list(map(utils.safe_ord, data)))
            # print('LOG', msg.to, topics, list(map(ord, data)))
        # Create a new contract
        elif op == 'CREATE':
            value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            if msg.static:
                return vm_exception('Cannot CREATE inside a static context')
            if ext.get_balance(msg.to) >= value and msg.depth < MAX_DEPTH:
                cd = CallData(mem, mstart, msz)
                ingas = compustate.gas
                if ext.post_anti_dos_hardfork():
                    ingas = all_but_1n(ingas, opcodes.CALL_CHILD_LIMIT_DENOM)
                create_msg = Message(msg.to, b'', value, ingas, cd, msg.depth + 1)
                o, gas, data = ext.create(create_msg)
                if o:
                    stk.append(utils.coerce_to_int(data))
                    compustate.last_returned = bytearray(b'')
                else:
                    stk.append(0)
                    compustate.last_returned = bytearray(data)
                compustate.gas = compustate.gas - ingas + gas
            else:
                stk.append(0)
                compustate.last_returned = bytearray(b'')
        # Calls
        elif op in ('CALL', 'CALLCODE', 'DELEGATECALL', 'STATICCALL'):
            # Pull arguments from the stack
            if op in ('CALL', 'CALLCODE'):
                gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                    stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            else:
                gas, to, meminstart, meminsz, memoutstart, memoutsz = \
                    stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
                value = 0
            # Static context prohibition
            if msg.static and value > 0 and op == 'CALL':
                return vm_exception(
                    'Cannot make a non-zero-value call inside a static context')
            # Expand memory
            if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                    not mem_extend(mem, compustate, op, memoutstart, memoutsz):
                return vm_exception('OOG EXTENDING MEMORY')
            to = utils.int_to_addr(to)
            # Extra gas costs based on various factors
            extra_gas = 0
            # Creating a new account
            if op == 'CALL' and not ext.account_exists(to) and (
                    value > 0 or not ext.post_spurious_dragon_hardfork()):
                extra_gas += opcodes.GCALLNEWACCOUNT
            # Value transfer
            if value > 0:
                extra_gas += opcodes.GCALLVALUETRANSFER
            # Cost increased from 40 to 700 in Tangerine Whistle
            if ext.post_anti_dos_hardfork():
                extra_gas += opcodes.CALL_SUPPLEMENTAL_GAS
            # Compute child gas limit
            if ext.post_anti_dos_hardfork():
                if compustate.gas < extra_gas:
                    return vm_exception('OUT OF GAS', needed=extra_gas)
                gas = min(
                    gas,
                    all_but_1n(
                        compustate.gas -
                        extra_gas,
                        opcodes.CALL_CHILD_LIMIT_DENOM))
            else:
                if compustate.gas < gas + extra_gas:
                    return vm_exception('OUT OF GAS', needed=gas + extra_gas)
            submsg_gas = gas + opcodes.GSTIPEND * (value > 0)
            # Verify that there is sufficient balance and depth
            if ext.get_balance(msg.to) < value or msg.depth >= MAX_DEPTH:
                compustate.gas -= (gas + extra_gas - submsg_gas)
                stk.append(0)
                compustate.last_returned = bytearray(b'')
            else:
                # Subtract gas from parent
                compustate.gas -= (gas + extra_gas)
                assert compustate.gas >= 0
                cd = CallData(mem, meminstart, meminsz)
                # Generate the message
                if op == 'CALL':
                    call_msg = Message(msg.to, to, value, submsg_gas, cd,
                                       msg.depth + 1, code_address=to, static=msg.static)
                elif ext.post_homestead_hardfork() and op == 'DELEGATECALL':
                    call_msg = Message(msg.sender, msg.to, msg.value, submsg_gas, cd,
                                       msg.depth + 1, code_address=to, transfers_value=False, static=msg.static)
                elif ext.post_metropolis_hardfork() and op == 'STATICCALL':
                    call_msg = Message(msg.to, to, value, submsg_gas, cd,
                                       msg.depth + 1, code_address=to, static=True)
                elif op in ('DELEGATECALL', 'STATICCALL'):
                    return vm_exception('OPCODE %s INACTIVE' % op)
                elif op == 'CALLCODE':
                    call_msg = Message(msg.to, msg.to, value, submsg_gas, cd,
                                       msg.depth + 1, code_address=to, static=msg.static)
                else:
                    raise Exception("Lolwut")
                # Get result
                result, gas, data = ext.msg(call_msg)
                if result == 0:
                    stk.append(0)
                else:
                    stk.append(1)
                # Set output memory
                for i in range(min(len(data), memoutsz)):
                    mem[memoutstart + i] = data[i]
                compustate.gas += gas
                compustate.last_returned = bytearray(data)
        # Return opcode
        elif op == 'RETURN':
            s0, s1 = stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, s0, s1):
                return vm_exception('OOG EXTENDING MEMORY')
            return peaceful_exit('RETURN', compustate.gas, mem[s0: s0 + s1])
        # Revert opcode (Metropolis)
        elif op == 'REVERT':
            if not ext.post_metropolis_hardfork():
                return vm_exception('Opcode not yet enabled')
            s0, s1 = stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, s0, s1):
                return vm_exception('OOG EXTENDING MEMORY')
            return revert(compustate.gas, mem[s0: s0 + s1])
        # SUICIDE opcode (also called SELFDESTRUCT)
        elif op == 'SUICIDE':
            if msg.static:
                return vm_exception('Cannot SUICIDE inside a static context')
            to = utils.encode_int(stk.pop())
            to = ((b'\x00' * (32 - len(to))) + to)[12:]
            xfer = ext.get_balance(msg.to)
            if ext.post_anti_dos_hardfork():
                extra_gas = opcodes.SUICIDE_SUPPLEMENTAL_GAS + \
                    (not ext.account_exists(to)) * (xfer >
                                                    0 or not ext.post_spurious_dragon_hardfork()) * opcodes.GCALLNEWACCOUNT
                if not eat_gas(compustate, extra_gas):
                    return vm_exception("OUT OF GAS")
            ext.set_balance(to, ext.get_balance(to) + xfer)
            ext.set_balance(msg.to, 0)
            ext.add_suicide(msg.to)
            log_msg.debug(
                'SUICIDING',
                addr=utils.checksum_encode(
                    msg.to),
                to=utils.checksum_encode(to),
                xferring=xfer)
            return peaceful_exit('SUICIDED', compustate.gas, [])

        if trace_vm:
            vm_trace(ext, msg, compustate, opcode, pushcache)

    if trace_vm:
        compustate.reset_prev()
        vm_trace(ext, msg, compustate, 0, None)
    return peaceful_exit('CODE OUT OF RANGE', compustate.gas, [])


# A stub that's mainly here to show what you would need to implement to
# hook into the EVM
class VmExtBase():

    def __init__(self):
        self.get_code = lambda addr: b''
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
        self.tx_origin = b'0' * 40
        self.tx_gasprice = 0
        self.create = lambda msg: 0, 0, 0
        self.call = lambda msg: 0, 0, 0
        self.sendmsg = lambda msg: 0, 0, 0
