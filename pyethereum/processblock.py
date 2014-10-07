import rlp
from opcodes import opcodes

import utils
import time
import blocks
import transactions
import trie
import sys
import logging
import json
import time
logger = logging.getLogger(__name__)
sys.setrecursionlimit(100000)



class PBLogger(object):
    log_apply_op = False    # general flag for logging inside apply_op
    log_op = False          # log op, gas, stack before each op
    log_pre_state = False   # dump storage at account before execution
    log_post_state = False  # dump storage at account after execution
    log_block = False       # dump block after TX was applied
    log_memory = False      # dump memory before each op
    log_stack = False       # dump stack before each op
    log_storage = False     # dump storage before each op
    log_json = False        # generate machine readable output
    log_state_delta = False  # dump state delta post tx execution

    def __init__(self):
        self.listeners = []  # register callbacks here

    def log(self, name, **kargs):
        # call callbacks
        for l in self.listeners:
            l(name, kargs)
        if self.log_json:
            logger.debug(json.dumps({name: kargs}))
        else:
            order = dict(pc=-2, op=-1, stackargs=1, data=2, code=3)
            items = sorted(kargs.items(), key=lambda x: order.get(x[0], 0))
            msg = ", ".join("%s=%s" % (k, v) for k, v in items)
            logger.debug("%s: %s", name.ljust(15), msg)

pblogger = PBLogger()

code_cache = {}


GDEFAULT = 1
GMEMORY = 1
GSTORAGE = 100
GTXDATA = 5
GTXCOST = 500
TT255 = 2**255
TT256 = 2**256

OUT_OF_GAS = -1

# contract creating transactions send to an empty address
CREATE_CONTRACT_ADDRESS = ''

class VerificationFailed(Exception):
    pass

def verify(block, parent):
    def must_equal(what, a, b):
        if a != b: raise VerificationFailed(what, a, '==', b)

    if not block.timestamp >= parent.timestamp:
        raise VerificationFailed('timestamp', block.timestamp, '>=', parent.timestamp)
    if not block.timestamp <= time.time() + 900:
        raise VerificationFailed('timestamps', block.timestamp, '<=', time.time() + 900)

    block2 = blocks.Block.init_from_parent(parent,
                                           block.coinbase,
                                           extra_data=block.extra_data,
                                           timestamp=block.timestamp,
                                           uncles=block.uncles)
    must_equal('difficulty', block2.difficulty, block.difficulty)
    must_equal('gas limit', block2.gas_limit, block.gas_limit)
    for i in range(block.transaction_count):
        tx, s, g = rlp.decode(
            block.transactions.get(rlp.encode(utils.encode_int(i))))
        tx = transactions.Transaction.create(tx)
        if not tx.startgas + block2.gas_used <= block.gas_limit:
            raise VerificationFailed('gas_limit', tx.startgas + block2.gas_used, '<=', block.gas_limit)
        apply_transaction(block2, tx)
        must_equal('tx state root', s, block2.state.root_hash)
        must_equal('tx gas used', g, utils.encode_int(block2.gas_used))
    block2.finalize()
    must_equal('block state root', block2.state.root_hash, block.state.root_hash)
    must_equal('block gas used', block2.gas_used, block.gas_used)
    return True


class Message(object):

    def __init__(self, sender, to, value, gas, data):
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data

    def __repr__(self):
        return '<Message(to:%s...)>' % self.to[:8]


class InvalidTransaction(Exception):
    pass

class UnsignedTransaction(InvalidTransaction):
    pass

class InvalidNonce(InvalidTransaction):
    pass

class InsufficientBalance(InvalidTransaction):
    pass

class InsufficientStartGas(InvalidTransaction):
    pass

class BlockGasLimitReached(InvalidTransaction):
    pass

class GasPriceTooLow(InvalidTransaction):
    pass


def apply_transaction(block, tx):

    def rp(actual, target):
        return '%r, actual:%r target:%r' % (tx, actual, target)

    # (1) The transaction signature is valid;
    if not tx.sender:
        raise UnsignedTransaction(tx)

    # (2) the transaction nonce is valid (equivalent to the
    #     sender account's current nonce);
    acctnonce = block.get_nonce(tx.sender)
    if acctnonce != tx.nonce:
        raise InvalidNonce(rp(tx.nonce, acctnonce))

    # (3) the gas limit is no smaller than the intrinsic gas,
    # g0, used by the transaction;
    intrinsic_gas_used = GTXDATA * len(tx.data) + GTXCOST
    if tx.startgas < intrinsic_gas_used:
        raise InsufficientStartGas(rp(tx.startgas, intrinsic_gas_used))

    # (4) the sender account balance contains at least the
    # cost, v0, required in up-front payment.
    total_cost = tx.value + tx.gasprice * tx.startgas
    if block.get_balance(tx.sender) < total_cost:
        raise InsufficientBalance(
            rp(block.get_balance(tx.sender), total_cost))

    # check offered gas price is enough
    if tx.gasprice < block.min_gas_price:
        raise GasPriceTooLow(rp(tx.gasprice, block.min_gas_price))

    # check block gas limit
    if block.gas_used + tx.startgas > block.gas_limit:
        raise BlockGasLimitReached(rp(block.gas_used + tx.startgas, block.gas_limit))


    pblogger.log('TX NEW', tx=tx.hex_hash(), tx_dict=tx.to_dict())
    # start transacting #################
    block.increment_nonce(tx.sender)

    # buy startgas
    success = block.transfer_value(tx.sender, block.coinbase,
                                   tx.gasprice * tx.startgas)
    assert success

    message_gas = tx.startgas - intrinsic_gas_used
    message = Message(tx.sender, tx.to, tx.value, message_gas, tx.data)

    block.postqueue = [ message ]
    primary_result = None
    while len(block.postqueue):
        message = block.postqueue.pop(0)
        # MESSAGE
        if tx.to and tx.to != CREATE_CONTRACT_ADDRESS:
            result, gas_remained, data = apply_msg_send(block, tx, message)
        else:  # CREATE
            result, gas_remained, data = create_contract(block, tx, message)
            if result > 0:
                result = utils.coerce_addr_to_hex(result)
        if not primary_result:
            primary_result = result, gas_remained, data

    result, gas_remained, data = primary_result

    assert gas_remained >= 0

    pblogger.log("TX APPLIED", result=result, gas_remained=gas_remained,
                 data=''.join(map(chr, data)).encode('hex'))
    if pblogger.log_block:
        pblogger.log('BLOCK', block=block.to_dict(with_state=True, full_transactions=True))


    if not result:  # 0 = OOG failure in both cases
        pblogger.log('TX FAILED', reason='out of gas', startgas=tx.startgas, gas_remained=gas_remained)
        block.gas_used += tx.startgas
        output = OUT_OF_GAS
    else:
        pblogger.log('TX SUCCESS')
        gas_used = tx.startgas - gas_remained
        # sell remaining gas
        block.transfer_value(
            block.coinbase, tx.sender, tx.gasprice * gas_remained)
        block.gas_used += gas_used
        if tx.to:
            output = ''.join(map(chr, data))
        else:
            output = result
    block.commit_state()
    suicides = block.suicides
    block.suicides = []
    for s in suicides:
        block.del_account(s)
    block.add_transaction_to_list(tx)
    success = output is not OUT_OF_GAS
    return success, output if success else ''


def mk_transaction_spv_proof(block, tx):
    block.set_proof_mode(blocks.RECORDING)
    apply_transaction(block, tx)
    o = block.proof_nodes
    block.set_proof_mode(blocks.NONE)
    return o


def verify_transaction_spv_proof(block, tx, proof):
    block.set_proof_mode(blocks.VERIFYING, proof)
    try:
        apply_transaction(block, tx)
        block.set_proof_mode(blocks.NONE)
        return True
    except Exception, e:
        print e
        return False


def mk_independent_transaction_spv_proof(block, index):
    print block, index, block._list_transactions()
    block = blocks.Block.init_from_header(block.list_header())
    tx = transactions.Transaction.create(block.get_transaction(index)[0])
    if index > 0:
        _, pre_med, pre_gas = block.get_transaction(index - 1)
    else:
        pre_med, pre_gas = block.get_parent().state_root, 0
    block.state_root = pre_med
    block.gas_used = pre_gas
    nodes = mk_transaction_spv_proof(block, tx)
    nodes.extend(block.transactions.produce_spv_proof(rlp.encode(utils.encode_int(index))))
    if index > 0:
        nodes.extend(block.transactions.produce_spv_proof(rlp.encode(utils.encode_int(index - 1))))
    nodes = map(rlp.decode, list(set(map(rlp.encode, nodes))))
    return rlp.encode([utils.encode_int(64), block.get_parent().list_header(),
                       block.list_header(), utils.encode_int(index), nodes])


def verify_independent_transaction_spv_proof(proof):
    _, prevheader, header, index, nodes = rlp.decode(proof)
    index = utils.decode_int(index)
    pb = blocks.Block.deserialize_header(prevheader)
    b = blocks.Block.init_from_header(header)
    b.set_proof_mode(blocks.VERIFYING, nodes)
    if index != 0:
        _, pre_med, pre_gas = b.get_transaction(index - 1)
    else:
        pre_med, pre_gas = pb['state_root'], ''
        if utils.sha3(rlp.encode(prevheader)) != b.prevhash:
            return False
    b.state_root = pre_med
    b.gas_used = utils.decode_int(pre_gas)
    tx, post_med, post_gas = b.get_transaction(index)
    tx = transactions.Transaction.create(tx)
    o = verify_transaction_spv_proof(b, tx, nodes)
    return o and b.state_root == post_med and b.gas_used == utils.decode_int(post_gas)


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
        o.append(utils.big_endian_to_int(arr[i:i + 32]))
    return o


def apply_msg(block, tx, msg, code):
    pblogger.log("MSG APPLY", tx=tx.hex_hash(), sender=msg.sender, to=msg.to,
                 gas=msg.gas, value=msg.value, data=msg.data.encode('hex'))
    if pblogger.log_pre_state:
        pblogger.log('MSG PRE STATE', account=msg.to, state=block.account_to_dict(msg.to))
    # Transfer value, instaquit if not enough
    o = block.transfer_value(msg.sender, msg.to, msg.value)
    if not o:
        return 1, msg.gas, []
    snapshot = block.snapshot()
    compustate = Compustate(gas=msg.gas)
    t, ops = time.time(), 0
    if code in code_cache:
        processed_code = code_cache[code]
    else:
        processed_code = [opcodes.get(ord(c), ['INVALID', 0, 0, [], 1]) +
                          [ord(c)] for c in code]
        code_cache[code] = processed_code
    # Main loop
    while 1:
        o = apply_op(block, tx, msg, processed_code, compustate)
        ops += 1
        if o is not None:
            pblogger.log('MSG APPLIED', result=o, gas_remained=compustate.gas,
                         sender=msg.sender, to=msg.to, ops=ops,
                         time_per_op=(time.time() - t) / ops)
            if pblogger.log_post_state:
                    pblogger.log('MSG POST STATE', account=msg.to,
                                 state=block.account_to_dict(msg.to))

            if o == OUT_OF_GAS:
                block.revert(snapshot)
                return 0, compustate.gas, []
            else:
                return 1, compustate.gas, o


def apply_msg_send(block, tx, msg):
    return apply_msg(block, tx, msg, block.get_code(msg.to))


def create_contract(block, tx, msg):
    sender = msg.sender.decode('hex') if len(msg.sender) == 40 else msg.sender
    if tx.sender != msg.sender:
        block.increment_nonce(msg.sender)
    nonce = utils.encode_int(block.get_nonce(msg.sender) - 1)
    msg.to = utils.sha3(rlp.encode([sender, nonce]))[12:].encode('hex')
    assert not block.get_code(msg.to)
    res, gas, dat = apply_msg(block, tx, msg, msg.data)
    if res:
        block.set_code(msg.to, ''.join(map(chr, dat)))
        return utils.coerce_to_int(msg.to), gas, dat
    else:
        if tx.sender != msg.sender:
            block.decrement_nonce(msg.sender)
        block.del_account(msg.to)
        return res, gas, dat


def get_opcode(code, index):
    return ord(code[index]) if index < len(code) else 0


def get_op_data(code, index):
    opcode = ord(code[index]) if index < len(code) else 0
    return opcodes.get(opcode, ['INVALID', 0, 0, [], 0])


def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)


def out_of_gas_exception(expense, fee, compustate, op):
    pblogger.log('OUT OF GAS', expense=expense, needed=fee, available=compustate.gas,
                 op=op, stack=list(reversed(compustate.stack)))
    return OUT_OF_GAS


def mem_extend(mem, compustate, op, start, sz):
    if sz:
        newsize = start + sz
        if len(mem) < ceil32(newsize):
            m_extend = ceil32(newsize) - len(mem)
            memfee = GMEMORY * (m_extend / 32)
            if compustate.gas < memfee:
                out_of_gas_exception('mem_extend', memfee, compustate, op)
                compustate.gas = 0
                return False
            compustate.gas -= memfee
            mem.extend([0] * m_extend)
    return True


def to_signed(i):
    return i if i < TT255 else i - TT256

# Does not include paying opfee
def apply_op(block, tx, msg, processed_code, compustate):
    if compustate.pc >= len(processed_code):
        return []
    op, in_args, out_args, mem_grabs, fee, opcode = processed_code[compustate.pc]

    # out of gas error
    if fee > compustate.gas:
        return out_of_gas_exception('base_gas', fee, compustate, op)

    # Apply operation
    compustate.gas -= fee
    compustate.pc += 1
    stk = compustate.stack
    mem = compustate.memory

    # empty stack error
    if in_args > len(compustate.stack):
        pblogger.log('INSUFFICIENT STACK ERROR', op=op, needed=in_args,
                     available=len(compustate.stack))
        return []


    if pblogger.log_apply_op:
        if pblogger.log_stack:
            pblogger.log('STK', stk=list(reversed(compustate.stack)))

        if pblogger.log_memory:
            for i in range(0, len(compustate.memory), 16):
                memblk = compustate.memory[i:i+16]
                memline = ' '.join([chr(x).encode('hex') for x in memblk])
                pblogger.log('MEM', mem=memline)

        if pblogger.log_storage:
            pblogger.log('STORAGE', storage=block.account_to_dict(msg.to)['storage'])

        if pblogger.log_op:
            log_args = dict(pc=compustate.pc - 1,
                            op=op,
                            stackargs=compustate.stack[-1:-in_args-1:-1],
                            gas=compustate.gas + fee,
                            balance=block.get_balance(msg.to))
            if op[:4] == 'PUSH':
                ind = compustate.pc
                log_args['value'] = \
                    utils.bytearray_to_int([x[-1] for x in processed_code[ind: ind + int(op[4:])]])
            elif op == 'CALLDATACOPY':
                log_args['data'] = msg.data.encode('hex')
            pblogger.log('OP', **log_args)

    if op == 'STOP' or op == 'INVALID':
        return []
    elif op == 'ADD':
        stk.append((stk.pop() + stk.pop()) % TT256)
    elif op == 'SUB':
        stk.append((stk.pop() - stk.pop()) % TT256)
    elif op == 'MUL':
        stk.append((stk.pop() * stk.pop()) % TT256)
    elif op == 'DIV':
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 / s1)
    elif op == 'MOD':
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 % s1)
    elif op == 'SDIV':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (abs(s0) // abs(s1) * (-1 if s0*s1 < 0 else 1)) % TT256)
    elif op == 'SMOD':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (abs(s0) % abs(s1) * (-1 if s0 < 0 else 1)) % TT256)
    elif op == 'EXP':
        stk.append(pow(stk.pop(), stk.pop(), TT256))
    elif op == 'NEG':
        stk.append(-stk.pop() % TT256)
    elif op == 'LT':
        stk.append(1 if stk.pop() < stk.pop() else 0)
    elif op == 'GT':
        stk.append(1 if stk.pop() > stk.pop() else 0)
    elif op == 'SLT':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(1 if s0 < s1 else 0)
    elif op == 'SGT':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(1 if s0 > s1 else 0)
    elif op == 'EQ':
        stk.append(1 if stk.pop() == stk.pop() else 0)
    elif op == 'NOT':
        stk.append(0 if stk.pop() else 1)
    elif op == 'AND':
        stk.append(stk.pop() & stk.pop())
    elif op == 'OR':
        stk.append(stk.pop() | stk.pop())
    elif op == 'XOR':
        stk.append(stk.pop() ^ stk.pop())
    elif op == 'BYTE':
        s0, s1 = stk.pop(), stk.pop()
        if s0 >= 32:
            stk.append(0)
        else:
            stk.append((s1 / 256 ** (31 - s0)) % 256)
    elif op == 'ADDMOD':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 + s1) % s2 if s2 else 0)
    elif op == 'MULMOD':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 * s1) % s2 if s2 else 0)
    elif op == 'SHA3':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, s1):
            return OUT_OF_GAS
        data = ''.join(map(chr, mem[s0: s0 + s1]))
        stk.append(utils.big_endian_to_int(utils.sha3(data)))
    elif op == 'ADDRESS':
        stk.append(utils.coerce_to_int(msg.to))
    elif op == 'BALANCE':
        stk.append(block.get_balance(utils.coerce_addr_to_hex(stk.pop())))
    elif op == 'ORIGIN':
        stk.append(utils.coerce_to_int(tx.sender))
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
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, s2):
            return OUT_OF_GAS
        for i in range(s2):
            if s1 + i < len(msg.data):
                mem[s0 + i] = ord(msg.data[s1 + i])
            else:
                mem[s0 + i] = 0
    elif op == 'CODESIZE':
        stk.append(len(processed_code))
    elif op == 'CODECOPY':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, s2):
            return OUT_OF_GAS
        for i in range(s2):
            if s1 + i < len(processed_code):
                mem[s0 + i] = processed_code[s1 + i][-1]
            else:
                mem[s0 + i] = 0
    elif op == 'GASPRICE':
        stk.append(tx.gasprice)
    elif op == 'EXTCODESIZE':
        stk.append(len(block.get_code(utils.coerce_addr_to_hex(stk.pop())) or ''))
    elif op == 'EXTCODECOPY':
        addr, s1, s2, s3 = stk.pop(), stk.pop(), stk.pop(), stk.pop()
        extcode = block.get_code(utils.coerce_addr_to_hex(addr)) or ''
        if not mem_extend(mem, compustate, op, s1, s3):
            return OUT_OF_GAS
        for i in range(s3):
            if s2 + i < len(extcode):
                mem[s1 + i] = ord(extcode[s2 + i])
            else:
                mem[s1 + i] = 0
    elif op == 'PREVHASH':
        stk.append(utils.big_endian_to_int(block.prevhash))
    elif op == 'COINBASE':
        stk.append(utils.big_endian_to_int(block.coinbase.decode('hex')))
    elif op == 'TIMESTAMP':
        stk.append(block.timestamp)
    elif op == 'NUMBER':
        stk.append(block.number)
    elif op == 'DIFFICULTY':
        stk.append(block.difficulty)
    elif op == 'GASLIMIT':
        stk.append(block.gas_limit)
    elif op == 'POP':
        stk.pop()
    elif op == 'MLOAD':
        s0 = stk.pop()
        if not mem_extend(mem, compustate, op, s0, 32):
            return OUT_OF_GAS
        data = ''.join(map(chr, mem[s0: s0 + 32]))
        stk.append(utils.big_endian_to_int(data))
    elif op == 'MSTORE':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, 32):
            return OUT_OF_GAS
        v = s1
        for i in range(31, -1, -1):
            mem[s0 + i] = v % 256
            v /= 256
    elif op == 'MSTORE8':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, 1):
            return OUT_OF_GAS
        mem[s0] = s1 % 256
    elif op == 'SLOAD':
        stk.append(block.get_storage_data(msg.to, stk.pop()))
    elif op == 'SSTORE':
        s0, s1 = stk.pop(), stk.pop()
        pre_occupied = GSTORAGE if block.get_storage_data(msg.to, s0) else 0
        post_occupied = GSTORAGE if s1 else 0
        gascost = GSTORAGE + post_occupied - pre_occupied
        if compustate.gas < gascost:
            return out_of_gas_exception('sstore trie expansion', gascost, compustate, op)
        compustate.gas -= gascost
        block.set_storage_data(msg.to, s0, s1)
    elif op == 'JUMP':
        compustate.pc = stk.pop()
    elif op == 'JUMPI':
        s0, s1 = stk.pop(), stk.pop()
        if s1:
            compustate.pc = s0
    elif op == 'PC':
        stk.append(compustate.pc - 1)
    elif op == 'MSIZE':
        stk.append(len(mem))
    elif op == 'GAS':
        stk.append(compustate.gas)  # AFTER subtracting cost 1
    elif op[:4] == 'PUSH':
        pushnum = int(op[4:])
        dat = [x[-1] for x in processed_code[compustate.pc: compustate.pc + pushnum]]
        compustate.pc += pushnum
        stk.append(utils.bytearray_to_int(dat))
    elif op[:3] == 'DUP':
        depth = int(op[3:])
        # DUP POP POP Debug hint
        is_debug = 1
        for i in range(depth):
            if compustate.pc + i < len(processed_code) and \
                    processed_code[compustate.pc + i][0] != 'POP':
                is_debug = 0
                break
        if is_debug:
            stackargs = [stk.pop() for i in range(depth)]
            print(' '.join(map(repr, stackargs)))
            stk.extend(reversed(stackargs))
            stk.append(stackargs[-1])
        else:
            stk.append(stk[-depth])
    elif op[:4] == 'SWAP':
        depth = int(op[4:])
        temp = stk[-depth-1]
        stk[-depth-1] = stk[-1]
        stk[-1] = temp
    elif op == 'CREATE':
        value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, mstart, msz):
            return OUT_OF_GAS
        if block.get_balance(msg.to) >= value:
            data = ''.join(map(chr, mem[mstart: mstart + msz]))
            pblogger.log('SUB CONTRACT NEW', sender=msg.to, value=value, data=data.encode('hex'))
            create_msg = Message(msg.to, '', value, compustate.gas, data)
            addr, gas, code = create_contract(block, tx, create_msg)
            pblogger.log('SUB CONTRACT OUT', address=addr, code=code)
            if addr:
                stk.append(addr)
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
            return OUT_OF_GAS
        if compustate.gas < gas:
            return out_of_gas_exception('subcall gas', gas, compustate, op)
        compustate.gas -= gas
        if block.get_balance(msg.to) >= value:
            to = utils.encode_int(to)
            to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
            data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
            pblogger.log('SUB CALL NEW', sender=msg.to, to=to, value=value, gas=gas, data=data.encode('hex'), csg=compustate.gas)
            call_msg = Message(msg.to, to, value, gas, data)
            result, gas, data = apply_msg_send(block, tx, call_msg)
            pblogger.log('SUB CALL OUT', result=result, data=data, length=len(data), expected=memoutsz, csg=compustate.gas)
            if result == 0:
                stk.append(0)
            else:
                stk.append(1)
                compustate.gas += gas
                for i in range(min(len(data), memoutsz)):
                    mem[memoutstart + i] = data[i]
        else:
            stk.append(0)
    elif op == 'RETURN':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0, s1):
            return OUT_OF_GAS
        return mem[s0: s0 + s1]
    elif op == 'POST':
        gas, to, value, meminstart, meminsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, meminstart, meminsz):
            return OUT_OF_GAS
        if compustate.gas < gas:
            return out_of_gas_exception('subcall gas', gas, compustate, op)
        compustate.gas -= gas
        to = utils.encode_int(to)
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        pblogger.log('POST NEW', sender=msg.to, to=to, value=value, gas=gas, data=data.encode('hex'))
        post_msg = Message(msg.to, to, value, gas, data)
        block.postqueue.append(post_msg)
    elif op == 'CALL_STATELESS':
        gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, meminstart, meminsz) or \
                not mem_extend(mem, compustate, op, memoutstart, memoutsz):
            return OUT_OF_GAS
        if compustate.gas < gas:
            return out_of_gas_exception('subcall gas', gas, compustate, op)
        compustate.gas -= gas
        to = utils.encode_int(to)
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        pblogger.log('SUB CALL NEW', sender=msg.to, to=to, value=value, gas=gas, data=data.encode('hex'))
        call_msg = Message(msg.to, msg.to, value, gas, data)
        result, gas, data = apply_msg(block, tx, call_msg, block.get_code(to))
        pblogger.log('SUB CALL OUT', result=result, data=data, length=len(data), expected=memoutsz)
        if result == 0:
            stk.append(0)
        else:
            stk.append(1)
            compustate.gas += gas
            for i in range(min(len(data), memoutsz)):
                mem[memoutstart + i] = data[i]
    elif op == 'SUICIDE':
        to = utils.encode_int(stk.pop())
        to = (('\x00' * (32 - len(to))) + to)[12:].encode('hex')
        block.transfer_value(msg.to, to, block.get_balance(msg.to))
        block.suicides.append(msg.to)
        return []
    for a in stk:
        assert isinstance(a, (int, long))
