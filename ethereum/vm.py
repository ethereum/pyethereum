####### dev hack flags ###############

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
from ethereum.utils import to_string, encode_int, zpad

log_log = get_logger('eth.vm.log')
log_vm_exit = get_logger('eth.vm.exit')
log_vm_op = get_logger('eth.vm.op')
log_vm_op_stack = get_logger('eth.vm.op.stack')
log_vm_op_memory = get_logger('eth.vm.op.memory')
log_vm_op_storage = get_logger('eth.vm.op.storage')

TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1
TT255 = 2 ** 255

MAX_DEPTH = 1024


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
        for i in range(size):
            if datastart + i < self.size:
                mem[memstart + i] = self.data[self.offset + datastart + i]
            else:
                mem[memstart + i] = 0


class Message(object):

    def __init__(self, sender, to, value=0, gas=1000000, data='', depth=0,
            code_address=None, is_create=False, transfers_value=True):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = CallData(map(ord, data)) if isinstance(data, (str, bytes)) else data
        self.depth = depth
        self.logs = []
        self.code_address = to if code_address is None else code_address
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


# Preprocesses code, and determines which locations are in the middle
# of pushdata and thus invalid
def preprocess_code(code):
    assert isinstance(code, bytes)
    code = memoryview(code).tolist()
    ops = []
    i = 0
    while i < len(code):
        o = copy.copy(opcodes.opcodes.get(code[i], ['INVALID', 0, 0, 0]) + [code[i], 0])
        ops.append(o)
        if o[0][:4] == 'PUSH':
            for j in range(int(o[0][4:])):
                i += 1
                byte = code[i] if i < len(code) else 0
                o[-1] = (o[-1] << 8) + byte
                if i < len(code):
                    ops.append(['INVALID', 0, 0, 0, byte, 0])
        i += 1
    return ops


def mem_extend(mem, compustate, op, start, sz):
    if sz:
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


def eat_gas(compustate, amount):
    if compustate.gas < amount:
        compustate.gas = 0
        return False
    else:
        compustate.gas -= amount
        return True


def all_but_1n(x, n):
    return x - x / n


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

    s = time.time()
    op = None
    steps = 0
    _prevop = None  # for trace only

    while 1:
        # print('op: ', op, time.time() - s)
        # s = time.time()
        # stack size limit error
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
                                op=op, needed=to_string(in_args),
                                available=to_string(len(compustate.stack)))

        if len(compustate.stack) - in_args + out_args > 1024:
            return vm_exception('STACK SIZE LIMIT EXCEEDED',
                                op=op,
                                pre_height=to_string(len(compustate.stack)))

        # Apply operation
        compustate.gas -= fee
        compustate.pc += 1

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
                if len(compustate.memory) < 1024:
                    trace_data['memory'] = \
                        b''.join([encode_hex(ascii_chr(x)) for x
                                  in compustate.memory])
                else:
                    trace_data['sha3memory'] = \
                        encode_hex(utils.sha3(''.join([ascii_chr(x) for
                                              x in compustate.memory])))
            if _prevop in ('SSTORE', 'SLOAD') or steps == 0:
                trace_data['storage'] = ext.log_storage(msg.to)
            trace_data['gas'] = to_string(compustate.gas + fee)
            trace_data['inst'] = opcode
            trace_data['pc'] = to_string(compustate.pc - 1)
            if steps == 0:
                trace_data['depth'] = msg.depth
                trace_data['address'] = msg.to
            trace_data['op'] = op
            trace_data['steps'] = steps
            if op[:4] == 'PUSH':
                trace_data['pushvalue'] = pushval
            log_vm_op.trace('vm', **trace_data)
            steps += 1
            _prevop = op

        # Invalid operation
        if op == 'INVALID':
            return vm_exception('INVALID OP', opcode=opcode)

        # Valid operations
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
                if ext.post_clearing_hardfork():
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
        elif opcode < 0x40:
            if op == 'SHA3':
                s0, s1 = stk.pop(), stk.pop()
                compustate.gas -= opcodes.GSHA3WORD * (utils.ceil32(s1) // 32)
                if compustate.gas < 0:
                    return vm_exception('OOG PAYING FOR SHA3')
                if not mem_extend(mem, compustate, op, s0, s1):
                    return vm_exception('OOG EXTENDING MEMORY')
                data = b''.join(map(ascii_chr, mem[s0: s0 + s1]))
                stk.append(utils.big_endian_to_int(utils.sha3(data)))
            elif op == 'ADDRESS':
                stk.append(utils.coerce_to_int(msg.to))
            elif op == 'BALANCE':
                if ext.post_anti_dos_hardfork():
                    if not eat_gas(compustate, opcodes.BALANCE_SUPPLEMENTAL_GAS):
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
                if ext.post_anti_dos_hardfork():
                    if not eat_gas(compustate, opcodes.EXTCODELOAD_SUPPLEMENTAL_GAS):
                        return vm_exception("OUT OF GAS")
                addr = utils.coerce_addr_to_hex(stk.pop() % 2**160)
                stk.append(len(ext.get_code(addr) or b''))
            elif op == 'EXTCODECOPY':
                if ext.post_anti_dos_hardfork():
                    if not eat_gas(compustate, opcodes.EXTCODELOAD_SUPPLEMENTAL_GAS):
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
                        mem[start + i] = utils.safe_ord(extcode[s2 + i])
                    else:
                        mem[start + i] = 0
        elif opcode < 0x50:
            if op == 'BLOCKHASH':
                if ext.post_metropolis_hardfork():
                    bh_addr = ext.blockhash_store
                    stk.append(ext.get_storage_data(bh_addr, stk.pop()))
                else:
                    stk.append(utils.big_endian_to_int(ext.block_hash(stk.pop())))
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
        elif opcode < 0x60:
            if op == 'POP':
                stk.pop()
            elif op == 'MLOAD':
                s0 = stk.pop()
                if not mem_extend(mem, compustate, op, s0, 32):
                    return vm_exception('OOG EXTENDING MEMORY')
                data = b''.join(map(ascii_chr, mem[s0: s0 + 32]))
                stk.append(utils.big_endian_to_int(data))
            elif op == 'MSTORE':
                s0, s1 = stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, s0, 32):
                    return vm_exception('OOG EXTENDING MEMORY')
                v = s1
                for i in range(31, -1, -1):
                    mem[s0 + i] = v % 256
                    v //= 256
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
                ext.set_storage_data(msg.to, s0, encode_int(s1))
            elif op == 'JUMP':
                compustate.pc = stk.pop()
                opnew = processed_code[compustate.pc][0] if \
                    compustate.pc < len(processed_code) else 'STOP'
                if opnew != 'JUMPDEST':
                    return vm_exception('BAD JUMPDEST')
            elif op == 'JUMPI':
                s0, s1 = stk.pop(), stk.pop()
                if s1:
                    compustate.pc = s0
                    opnew = processed_code[compustate.pc][0] if \
                        compustate.pc < len(processed_code) else 'STOP'
                    if opnew != 'JUMPDEST':
                        return vm_exception('BAD JUMPDEST')
            elif op == 'PC':
                stk.append(compustate.pc - 1)
            elif op == 'MSIZE':
                stk.append(len(mem))
            elif op == 'GAS':
                stk.append(compustate.gas)  # AFTER subtracting cost 1
        elif 0xe0 <= opcode < 0xef:
            if not ext.post_metropolis_hardfork():
                return vm_exception('OPCODE RANGE INACTIVE', opcode=opcode)
            if op == 'SLOADBYTES':
                key, mstart, msize = stk.pop(), stk.pop(), stk.pop()
                bytez = map(ord, ext.get_storage_bytes(msg.to, key))
                if not mem_extend(mem, compustate, op, mstart, min(msize, len(bytez))):
                    return vm_exception('OOG EXTENDING MEMORY')
                for i in range(min(msize, len(bytez))):
                    mem[mstart + i] = bytez[i]
            elif op == 'SSTOREBYTES':
                key, mstart, msize = stk.pop(), stk.pop(), stk.pop()
                if not mem_extend(mem, compustate, op, mstart, msize):
                    return vm_exception('OOG EXTENDING MEMORY')
                prev_adjbyte_count = len(ext.get_storage_bytes(msg.to, key))
                if prev_adjbyte_count >= 0:
                    prev_adjbyte_count += 32
                post_adjbyte_count = msize + (32 if msize else 0)
                gas_cost = opcodes.GSTORAGEBASE + opcodes.GSTORAGEBYTESTORAGE * \
                    (post_adjbyte_count - prev_adjbyte_count) + opcodes.GSTORAGEBYTECHANGE * post_adjbyte_count
                gas_payment = max(opcodes.GSTORAGEMIN, gas_cost)
                refund = gas_payment - gas_cost
                if compustate.gas < gas_payment:
                    return vm_exception('OUT OF GAS')
                compustate.gas -= gas_payment
                data = b''.join(map(chr, mem[mstart: mstart + msize]))
                ext.set_storage_bytes(msg.to, key, data)
                ext.add_refund(refund)
            elif op == 'SSIZE':
                stk.append(len(ext.get_storage_bytes(msg.to, stk.pop())))
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
            compustate.gas -= msz * opcodes.GLOGBYTE
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            data = b''.join(map(ascii_chr, mem[mstart: mstart + msz]))
            ext.log(msg.to, topics, data)
            log_log.trace('LOG', to=msg.to, topics=topics, data=list(map(utils.safe_ord, data)))
            # print('LOG', msg.to, topics, list(map(ord, data)))

        elif op == 'CREATE':
            value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, mstart, msz):
                return vm_exception('OOG EXTENDING MEMORY')
            if ext.get_balance(msg.to) >= value and msg.depth < MAX_DEPTH:
                cd = CallData(mem, mstart, msz)
                ingas = compustate.gas
                if ext.post_anti_dos_hardfork():
                    ingas = all_but_1n(ingas, opcodes.CALL_CHILD_LIMIT_DENOM)
                create_msg = Message(msg.to, b'', value, ingas, cd, msg.depth + 1)
                o, gas, addr = ext.create(create_msg)
                if o:
                    stk.append(utils.coerce_to_int(addr))
                    compustate.gas = compustate.gas - ingas + gas
                else:
                    stk.append(0)
                    compustate.gas -= ingas
            else:
                stk.append(0)
        elif op == 'CALL':
            gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                    not mem_extend(mem, compustate, op, memoutstart, memoutsz):
                return vm_exception('OOG EXTENDING MEMORY')
            to = utils.encode_int(to)
            to = ((b'\x00' * (32 - len(to))) + to)[12:]
            extra_gas = (not ext.account_exists(to)) * (value > 0 or not ext.post_clearing_hardfork()) * opcodes.GCALLNEWACCOUNT + \
                (value > 0) * opcodes.GCALLVALUETRANSFER + \
                ext.post_anti_dos_hardfork() * opcodes.CALL_SUPPLEMENTAL_GAS
            submsg_gas = gas + opcodes.GSTIPEND * (value > 0)
            if ext.post_anti_dos_hardfork():
                if compustate.gas < extra_gas:
                    return vm_exception('OUT OF GAS', needed=extra_gas)
                gas = min(gas, all_but_1n(compustate.gas - extra_gas, opcodes.CALL_CHILD_LIMIT_DENOM))
            else:
                if compustate.gas < gas + extra_gas:
                    return vm_exception('OUT OF GAS', needed=gas+extra_gas)
            submsg_gas = gas + opcodes.GSTIPEND * (value > 0)
            if ext.get_balance(msg.to) >= value and msg.depth < MAX_DEPTH:
                compustate.gas -= (gas + extra_gas)
                assert compustate.gas >= 0
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
        elif op == 'CALLCODE' or op == 'DELEGATECALL':
            if op == 'CALLCODE':
                gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
                    stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            else:
                gas, to, meminstart, meminsz, memoutstart, memoutsz = \
                    stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
                value = 0
            if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                    not mem_extend(mem, compustate, op, memoutstart, memoutsz):
                return vm_exception('OOG EXTENDING MEMORY')
            extra_gas = (value > 0) * opcodes.GCALLVALUETRANSFER + \
                ext.post_anti_dos_hardfork() * opcodes.CALL_SUPPLEMENTAL_GAS
            if ext.post_anti_dos_hardfork():
                if compustate.gas < extra_gas:
                    return vm_exception('OUT OF GAS', needed=extra_gas)
                gas = min(gas, all_but_1n(compustate.gas - extra_gas, opcodes.CALL_CHILD_LIMIT_DENOM))
            else:
                if compustate.gas < gas + extra_gas:
                    return vm_exception('OUT OF GAS', needed=gas+extra_gas)
            submsg_gas = gas + opcodes.GSTIPEND * (value > 0)
            if ext.get_balance(msg.to) >= value and msg.depth < MAX_DEPTH:
                compustate.gas -= (gas + extra_gas)
                assert compustate.gas >= 0
                to = utils.encode_int(to)
                to = ((b'\x00' * (32 - len(to))) + to)[12:]
                cd = CallData(mem, meminstart, meminsz)
                if ext.post_homestead_hardfork() and op == 'DELEGATECALL':
                    call_msg = Message(msg.sender, msg.to, msg.value, submsg_gas, cd,
                                       msg.depth + 1, code_address=to, transfers_value=False)
                elif op == 'DELEGATECALL':
                    return vm_exception('OPCODE INACTIVE')
                else:
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
        elif op == 'CALLBLACKBOX':
            if not ext.post_serenity_hardfork():
                return vm_exception('OPCODE INACTIVE')
            gas, codestart, codesz, datastart, datasz, outstart, outsz = \
                stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, datastart, datasz) or \
                    not mem_extend(mem, compustate, op, codestart, codesz):
                return vm_exception('OOG EXTENDING MEMORY')
            if ext.post_anti_dos_hardfork():
                gas = min(gas, all_but_1n(compustate.gas, opcodes.CALL_CHILD_LIMIT_DENOM))
            else:
                if gas > compustate.gas:
                    return vm_exception("OUT OF GAS", needed=gas)
            compustate.gas -= gas
            code = ''.join([chr(x) for x in mem[codestart: codestart + codesz]])
            call_msg = Message('\x00'*20, '\x00'*20, 0, gas, CallData(mem, datastart, datasz),
                               msg.depth + 1, transfers_value=False)
            result, gas, data = ext.blackbox_msg(call_msg, code)
            if result == 0:
                stk.append(0)
            else:
                stk.append(1)
                compustate.gas += gas
                if not mem_extend(mem, compustate, op, outstart, min(outsz, len(data))):
                    return vm_exception('OOG EXTENDING MEMORY')
                for i in range(min(len(data), outsz)):
                    mem[outstart + i] = data[i]
        elif op == 'RETURN':
            s0, s1 = stk.pop(), stk.pop()
            if not mem_extend(mem, compustate, op, s0, s1):
                return vm_exception('OOG EXTENDING MEMORY')
            return peaceful_exit('RETURN', compustate.gas, mem[s0: s0 + s1])
        elif op == 'SUICIDE':
            to = utils.encode_int(stk.pop())
            to = ((b'\x00' * (32 - len(to))) + to)[12:]
            xfer = ext.get_balance(msg.to)
            if ext.post_anti_dos_hardfork():
                extra_gas = opcodes.SUICIDE_SUPPLEMENTAL_GAS + \
                    (not ext.account_exists(to)) * (xfer > 0 or not ext.post_clearing_hardfork()) * opcodes.GCALLNEWACCOUNT
                if not eat_gas(compustate, extra_gas):
                    return vm_exception("OUT OF GAS")
            ext.set_balance(to, ext.get_balance(to) + xfer)
            ext.set_balance(msg.to, 0)
            ext.add_suicide(msg.to)
            # print('suiciding %s %s %d' % (msg.to, to, xfer))
            return 1, compustate.gas, []

        # this is slow!
        # for a in stk:
        #     assert is_numeric(a), (op, stk)
        #     assert a >= 0 and a < 2**256, (a, op, stk)


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
