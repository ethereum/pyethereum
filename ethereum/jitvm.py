from evmjit import EVMJIT
from ethereum.utils import sha3_256, decode_int
from ethereum.vm import CallData, Message

from pprint import pprint
from binascii import hexlify

jit = EVMJIT()


class JitEnv(object):
    def __init__(self, ext, msg):
        self.ext = ext
        self.msg = msg

    def get_balance(self, addr):
        addr = addr.encode('hex')
        if addr not in self.pre:
            return 0
        return int(self.pre[addr]['balance'], 16)

    def query(self, key, arg):
        print("query(key: {}, arg: {})".format(key, arg))
        if key == EVMJIT.SLOAD:
            return self.ext.get_storage_data(self.msg.to, arg)
        if key == EVMJIT.ADDRESS:
            return self.msg.to
        if key == EVMJIT.CALLER:
            return self.msg.sender
        if key == EVMJIT.ORIGIN:
            return self.ext.tx_origin
        if key == EVMJIT.GAS_PRICE:
            return self.ext.tx_gasprice
        if key == EVMJIT.COINBASE:
            return self.ext.block_coinbase
        if key == EVMJIT.NUMBER:
            n = self.ext.block_number
            print("NUMBER: {}".format(n))
            return n
        if key == EVMJIT.TIMESTAMP:
            n = self.ext.block_timestamp
            print("TIMESTAMP: {}".format(n))
            return n
        if key == EVMJIT.GAS_LIMIT:
            return self.ext.block_gas_limit
        if key == EVMJIT.DIFFICULTY:
            return self.ext.block_difficulty
        if key == EVMJIT.BLOCKHASH:
            block_hash = self.ext.block_hash(arg)
            if not block_hash:
                # Do not return empty bytes, but 0 hash.
                block_hash = b'\x00' * 32
            print("BLOCKHASH({}): {}".format(arg, hexlify(block_hash)))
            return block_hash
        if key == EVMJIT.CODE_BY_ADDRESS:
            code = self.ext.get_code(arg)
            print("EXTCODE({}): {}".format(hexlify(arg), hexlify(code)))
            return code
        if key == EVMJIT.BALANCE:
            b = self.ext.get_balance(arg)
            print("BALANCE({}): {}".format(hexlify(arg), b))
            return b
        assert False, "Implement ME!"

    def update(self, key, arg1, arg2):
        if key == EVMJIT.SSTORE:
            print("SSTORE({}, {})".format(arg1, arg2))
            self.ext.set_storage_data(self.msg.to, arg1, arg2)
        elif key == EVMJIT.SELFDESTRUCT:
            print("SELFDESTRUCT({})".format(hexlify(arg1)))
            # Copy the argument to bytes because some API freaks out otherwise.
            addr = bytes(arg1)
            # TODO: This logic should go to VMExt
            xfer = self.ext.get_balance(self.msg.to)
            self.ext.set_balance(addr, self.ext.get_balance(addr) + xfer)
            self.ext.set_balance(self.msg.to, 0)
            self.ext.add_suicide(self.msg.to)
        elif key == EVMJIT.LOG:
            print("LOG {}".format(map(hexlify, arg2)))
            # Make a copy of data because pyethereum expects bytes type
            # not buffer protocol.
            data = bytes(arg1)
            # Convert topics to ints.
            topics = [decode_int(t) for t in arg2]
            self.ext.log(self.msg.to, topics, data)
        else:
            assert False, "Unknown EVM-C update key"

    def call(self, kind, gas, address, value, input):
        if self.msg.depth >= 1024:
            return EVMJIT.FAILURE, b'', 0

        # First convert bytes to a list of int to allow CallData to pack it
        # again to bytes. WTF????????
        call_data = CallData(map(ord, input))
        # Convert to bytes becase rlp.encode_hex requires str or unicode. WTF?
        address = bytes(address)
        msg = Message(self.msg.to, address, value, gas, call_data,
                      self.msg.depth + 1, code_address=address)
        if kind == EVMJIT.CREATE:
            if value and self.ext.get_balance(self.msg.to) < value:
                return EVMJIT.FAILURE, b'', 0
            # TODO: msg.address is invalid
            o, gas_left, addr = self.ext.create(msg)
            res_code = EVMJIT.SUCCESS if addr else EVMJIT.FAILURE
            print("CREATE(gas: {}, value: {}, code: {}): {}".format(
                  gas, value, hexlify(input), hexlify(addr)))
            # FIXME: Change out args order to match ext.create()
            return EVMJIT.SUCCESS, addr, gas - gas_left

        if kind == EVMJIT.DELEGATECALL:
            assert value == 0

        cost = msg.gas
        if value and kind != EVMJIT.DELEGATECALL:
            cost += 9000
            msg.gas += 2300

        if kind == EVMJIT.CALL and not self.ext.account_exists(address):
            cost += 25000
        elif kind == EVMJIT.CALLCODE:
            msg.to = self.msg.to
            msg.code_address = address
        elif kind == EVMJIT.DELEGATECALL:
            msg.value = self.msg.value
            msg.transfers_value = False

        if value and self.ext.get_balance(self.msg.to) < value:
            cost -= msg.gas
            return EVMJIT.FAILURE, b'', cost

        print("call(kind: {}, to: {}, gas: {}, value: {})".format(kind, type(address), gas, value))
        result, gas_left, out = self.ext.msg(msg)
        cost -= gas_left
        assert cost >= 0
        res_code = EVMJIT.SUCCESS if result else EVMJIT.FAILURE
        return res_code, out, cost


def vm_execute(ext, msg, code):
    # FIXME: This pprint is needed for ext.get_code() to work. WTF??????????
    pprint(ext.__dict__)
    # pprint(msg.__dict__)
    # EVMJIT requires secure hash of the code to be used as the code
    # identifier.
    # TODO: Can we avoid recalculating it?
    code_hash = sha3_256(code)
    mode = (EVMJIT.HOMESTEAD if ext.post_homestead_hardfork()
            else EVMJIT.FRONTIER)
    data = msg.data.extract_all()
    env = JitEnv(ext, msg)
    result = jit.execute(env, mode, code_hash, code, msg.gas, data, msg.value)
    return result.code == EVMJIT.SUCCESS, result.gas_left, b''
