from rlp.sedes import big_endian_int, Binary, binary, CountableList
from rlp.utils import decode_hex, encode_hex, ascii_chr, str_to_bytes
from utils import address, int256, trie_root, hash32, to_string, sha3, \
    zpad, normalize_address, int_to_addr, big_endian_to_int, shardify
from db import EphemDB
from config import MAXSHARDS, SHARD_BYTES
import opcodes
import rlp

class Transaction(rlp.Serializable):
    fields = [
        ('addr', address),
        ('gas', big_endian_int),
        ('left_bound', big_endian_int),
        ('right_bound', big_endian_int),
        ('data', binary),
        ('code', binary)
    ]

    def __init__(self, addr, gas, left_bound=0, right_bound=MAXSHARDS, data='', code=b''):
        self.addr = addr or shardify(sha3('\x00' * 20 + code)[12:], left_bound)
        self.gas = gas
        self.left_bound = left_bound
        self.right_bound = right_bound
        self.data = data
        self.code = code
        assert len(self.addr) == 20 + SHARD_BYTES and (self.code == b'' or shardify(sha3('\x00' * 20 + self.code)[12:], left_bound) == self.addr)
        assert self.exec_gas >= 0
        assert isinstance(self.left_bound, int)
        assert isinstance(self.right_bound, int)

    @property
    def hash(self):
        return sha3(rlp.encode(self))

    @property
    def intrinsic_gas(self):
        num_zero_bytes = str_to_bytes(self.data).count(ascii_chr(0))
        num_non_zero_bytes = len(self.data) - num_zero_bytes
        return opcodes.GTXCOST + \
            num_zero_bytes * opcodes.GTXDATAZERO + \
            num_non_zero_bytes * opcodes.GTXDATANONZERO + \
            len(self.code) * opcodes.GCONTRACTBYTE

    @property
    def exec_gas(self):
        return self.gas - self.intrinsic_gas
