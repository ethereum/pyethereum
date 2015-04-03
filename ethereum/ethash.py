import copy
from ethereum.ethash_utils import *
import sys


def mkcache(cache_size, seed):
    n = cache_size // HASH_BYTES

    # Sequentially produce the initial dataset
    o = [sha3_512(seed)]
    for i in range(1, n):
        o.append(sha3_512(o[-1]))

    for _ in range(CACHE_ROUNDS):
        for i in range(n):
            v = o[i][0] % n
            o[i] = sha3_512(list(map(xor, o[(i - 1 + n) % n], o[v])))

    return o


def calc_dataset_item(cache, i):
    n = len(cache)
    r = HASH_BYTES // WORD_BYTES
    mix = copy.copy(cache[i % n])
    mix[0] ^= i
    mix = sha3_512(mix)
    for j in range(DATASET_PARENTS):
        cache_index = fnv(i ^ j, mix[j % r])
        mix = list(map(fnv, mix, cache[cache_index % n]))
    return sha3_512(mix)


def calc_dataset(full_size, cache):
    o = []
    percent = (full_size // HASH_BYTES) // 100
    for i in range(full_size // HASH_BYTES):
        if i % percent == 0:
            sys.stderr.write("Completed %d items, %d percent\n" % (i, i // percent))
        o.append(calc_dataset_item(cache, i))
    return o


def hashimoto(header, nonce, full_size, dataset_lookup):
    n = full_size // HASH_BYTES
    w = MIX_BYTES // WORD_BYTES
    mixhashes = MIX_BYTES // HASH_BYTES
    s = sha3_512(header + nonce[::-1])
    mix = []
    for _ in range(MIX_BYTES // HASH_BYTES):
        mix.extend(s)
    for i in range(ACCESSES):
        p = fnv(i ^ s[0], mix[i % w]) % (n // mixhashes) * mixhashes
        newdata = []
        for j in range(mixhashes):
            newdata.extend(dataset_lookup(p + j))
        mix = list(map(fnv, mix, newdata))
    cmix = []
    for i in range(0, len(mix), 4):
        cmix.append(fnv(fnv(fnv(mix[i], mix[i + 1]), mix[i + 2]), mix[i + 3]))
    return {
        "mix digest": serialize_hash(cmix),
        "result": serialize_hash(sha3_256(s + cmix))
    }


def hashimoto_light(full_size, cache, header, nonce):
    return hashimoto(header, nonce, full_size,
                     lambda x: calc_dataset_item(cache, x))


def hashimoto_full(dataset, header, nonce):
    return hashimoto(header, nonce, len(datset) * HASH_BYTES,
                     lambda x: dataset[x])


def mine(full_size, dataset, header, difficulty):
    from random import randint
    nonce = randint(0, 2**64)
    while decode_int(hashimoto_full(full_size, dataset, header, nonce)) < difficulty:
        nonce += 1
        nonce %= 2**64
    return nonce
