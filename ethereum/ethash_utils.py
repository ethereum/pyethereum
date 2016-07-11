try:
    from Crypto.Hash import keccak
    sha3_256 = lambda x: keccak.new(digest_bits=256, data=x).digest()
    sha3_512 = lambda x: keccak.new(digest_bits=512, data=x)
except:
    import sha3 as _sha3
    sha3_256 = lambda x: _sha3.sha3_256(x).digest()
    sha3_512 = lambda x: _sha3.sha3_512(x).digest()
from rlp.utils import decode_hex, encode_hex
import sys

WORD_BYTES = 4                    # bytes in word
DATASET_BYTES_INIT = 2**30        # bytes in dataset at genesis
DATASET_BYTES_GROWTH = 2**23      # growth per epoch (~7 GB per year)
CACHE_BYTES_INIT = 2**24          # Size of the dataset relative to the cache
CACHE_BYTES_GROWTH = 2**17        # Size of the dataset relative to the cache
EPOCH_LENGTH = 30000              # blocks per epoch
MIX_BYTES = 128                   # width of mix
HASH_BYTES = 64                   # hash length in bytes
DATASET_PARENTS = 256             # number of parents of each dataset element
CACHE_ROUNDS = 3                  # number of rounds in cache production
ACCESSES = 64                     # number of accesses in hashimoto loop


FNV_PRIME = 0x01000193


def fnv(v1, v2):
    return (v1 * FNV_PRIME ^ v2) % 2**32


# Assumes little endian bit ordering (same as Intel architectures)
def decode_int(s):
    return int(encode_hex(s[::-1]), 16) if s else 0


def encode_int(s):
    a = "%x" % s
    return b'' if s == 0 else decode_hex('0' * (len(a) % 2) + a)[::-1]


def zpad(s, length):
    return s + b'\x00' * max(0, length - len(s))


def serialize_hash(h):
    return b''.join([zpad(encode_int(x), 4) for x in h])


def deserialize_hash(h):
    return [decode_int(h[i:i+WORD_BYTES]) for i in range(0, len(h), WORD_BYTES)]


def hash_words(h, sz, x):
    if isinstance(x, list):
        x = serialize_hash(x)
    y = h(x)
    return deserialize_hash(y)


def to_bytes(x):
    if sys.version_info.major > 2 and isinstance(x, str):
        x = bytes(x, 'utf-8')
    return x


# sha3 hash function, outputs 64 bytes
def sha3_512(x):
    return hash_words(sha3_512(to_bytes(v)).digest(), 64, x)


def sha3_256(x):
    return hash_words(sha3_256(to_bytes(v)).digest(), 32, x)


def xor(a, b):
    return a ^ b


# Works for dataset and cache
def serialize_cache(ds):
    return b''.join([serialize_hash(h) for h in ds])

serialize_dataset = serialize_cache


def deserialize_cache(ds):
    return [deserialize_hash(ds[i:i+HASH_BYTES])
            for i in range(0, len(ds), HASH_BYTES)]

deserialize_dataset = deserialize_cache


class ListWrapper(list):
    def __init__(self, data):
        self.data = data
        self.len = len(data) // HASH_BYTES

    def __len__(self):
        return self.len

    def __getitem__(self, i):
        if i >= self.len:
            raise Exception("listwrap access out of range")
        return deserialize_hash(self.data[i*HASH_BYTES:(i+1)*HASH_BYTES])

    def __iter__(self):
        for i in range(self.len):
            yield self[i]

    def __repr__(self):
        return repr([x for x in self])


def isprime(x):
    for i in range(2, int(x**0.5)):
        if not x % i:
            return False
    return True


def get_cache_size(block_number):
    sz = CACHE_BYTES_INIT + CACHE_BYTES_GROWTH * (block_number // EPOCH_LENGTH)
    sz -= HASH_BYTES
    while not isprime(sz // HASH_BYTES):
        sz -= 2 * HASH_BYTES
    return sz


def get_full_size(block_number):
    sz = DATASET_BYTES_INIT + DATASET_BYTES_GROWTH * (block_number // EPOCH_LENGTH)
    sz -= MIX_BYTES
    while not isprime(sz // MIX_BYTES):
        sz -= 2 * MIX_BYTES
    return sz
