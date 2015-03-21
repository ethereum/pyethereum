import sha3
from rlp.utils import decode_hex, encode_hex

WORD_BYTES = 4                    # bytes in word
DATASET_BYTES_INIT = 2**30        # bytes in dataset at genesis
DATASET_BYTES_GROWTH = 113000000  # growth per epoch (~7 GB per year)
CACHE_MULTIPLIER = 1024           # Size of the dataset relative to the cache
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
    return int(s[::-1].encode('hex'), 16) if s else 0


def encode_int(s):
    a = "%x" % s
    return '' if s == 0 else decode_hex('0' * (len(a) % 2) + a)[::-1]


def zpad(s, length):
    return s + '\x00' * max(0, length - len(s))


def serialize_hash(h):
    return ''.join([zpad(encode_int(x), 4) for x in h])


def deserialize_hash(h):
    return [decode_int(h[i:i+WORD_BYTES]) for i in range(0, len(h), WORD_BYTES)]


def hash_words(h, sz, x):
    if isinstance(x, list):
        x = serialize_hash(x)
    y = h(x)
    return deserialize_hash(y)


# sha3 hash function, outputs 64 bytes
def sha3_512(x):
    return hash_words(lambda v: sha3.sha3_512(v).digest(), 64, x)


def sha3_256(x):
    return hash_words(lambda v: sha3.sha3_256(v).digest(), 32, x)


def xor(a, b):
    return a ^ b


# Works for dataset and cache
def serialize_cache(ds):
    return ''.join([serialize_hash(h) for h in ds])

serialize_dataset = serialize_cache


def deserialize_cache(ds):
    return [deserialize_hash(ds[i:i+HASH_BYTES])
            for i in range(0, len(ds), HASH_BYTES)]

deserialize_dataset = deserialize_cache


class ListWrapper(list):
    def __init__(self, data):
        self.data = data
        self.len = len(data) / HASH_BYTES

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


def get_full_size(block_number):
    return 1073739904


def get_cache_size(block_number):
    return 1048384


def get_next_cache_size(block_number):
    return get_cache_size(block_number + EPOCH_LENGTH)


def get_next_full_size(block_number):
    return get_full_size(block_number + EPOCH_LENGTH)
