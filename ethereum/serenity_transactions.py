from rlp.sedes import big_endian_int, Binary, binary, CountableList
from rlp.utils import decode_hex, encode_hex, ascii_chr, str_to_bytes
from ethereum.utils import address, int256, trie_root, hash32, to_string, \
    sha3, zpad, normalize_address, int_to_addr, big_endian_to_int
from config import Env
from db import EphemDB
import opcodes
import rlp

class Transaction(rlp.Serializable):
    fields = [
        ('addr', address),
        ('execgas', big_endian_int),
        ('data', binary),
        ('code', binary)
    ]

    def __init__(self, addr, execgas, data, code=b''):
        self.addr = addr or sha3('\x00' * 20 + code)[12:]
        self.execgas = execgas
        self.data = data
        self.code = code
        assert len(self.addr) == 20 and (self.code == b'' or sha3('\x00' * 20 + self.code)[12:] == self.addr)

    @property
    def hash(self):
        return sha3(rlp.encode(self))

    @property
    def intrinsic_gas(self):
        num_zero_bytes = str_to_bytes(tx.data).count(ascii_chr(0))
        num_non_zero_bytes = len(tx.data) - num_zero_bytes
        return opcodes.GTXCOST + \
            num_zero_bytes * opcodes.GTXDATAZERO + \
            num_non_zero_bytes * opcodes.GTXDATANONZERO + \
            len(tx.code) * opcodes.GCONTRACTBYTE
