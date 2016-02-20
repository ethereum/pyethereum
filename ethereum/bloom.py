from ethereum import utils
from ethereum.utils import safe_ord
from ethereum.abi import is_numeric
"""
Blooms are the 3-point, 2048-bit (11-bits/point) Bloom filter of each
component (except data) of each log entry of each transaction.

We set the bits of a 2048-bit value whose indices are given by
the low order 9-bits
of the first three double-bytes
of the SHA3
of each value.

bloom(0f572e5295c57f15886f9b263e2f6d2d6c7b5ec6)
sha3: bd2b01afcd27800b54d2179edc49e2bffde5078bb6d0b204694169b1643fb108
first double-bytes: bd2b, 01af, cd27 -- which leads to bits in bloom --> 1323, 431, 1319

blooms in this module are of type 'int'
"""

BUCKETS_PER_VAL = 3


def bloom(val):
    return bloom_insert(0, val)


def bloom_insert(bloom, val):
    h = utils.sha3(val)
#   print 'bloom_insert', bloom_bits(val), repr(val)
    for i in range(0, BUCKETS_PER_VAL * 2, 2):
        bloom |= 1 << ((safe_ord(h[i + 1]) + (safe_ord(h[i]) << 8)) & 2047)
    return bloom


def bloom_bits(val):
    h = utils.sha3(val)
    return [bits_in_number(1 << ((safe_ord(h[i + 1]) + (safe_ord(h[i]) << 8)) & 2047)) for i in range(0, BUCKETS_PER_VAL * 2, 2)]


def bits_in_number(val):
    assert is_numeric(val)
    return [n for n in range(2048) if (1 << n) & val]


def bloom_query(bloom, val):
    bloom2 = bloom_insert(0, val)
    return (bloom & bloom2) == bloom2


def bloom_combine(*args):
    bloom = 0
    for arg in args:
        bloom |= arg
    return bloom


def bloom_from_list(args):
    return bloom_combine(*[bloom_insert(0, arg) for arg in args])


def b64(int_bloom):
    "returns b256"
    return utils.zpad(utils.int_to_big_endian(int_bloom), 256)
