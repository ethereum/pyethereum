import copy
from ethash_utils import *


def mkcache(cache_size, seed):
    n = cache_size // HASH_BYTES

    # Sequentially produce the initial dataset
    o = [sha3_512(seed)]
    for i in range(1, n):
        o.append(sha3_512(o[-1]))
    print o[0], o[30]

    for _ in range(CACHE_ROUNDS):
        for i in range(n):
            v = o[i][0] % n
            o[i] = sha3_512(map(xor, o[(i-1+n) % n], o[v]))
        print o[0]

    return o


def calc_dag_item(cache, i):
    n = len(cache)
    r = HASH_BYTES // WORD_BYTES
    mix = copy.copy(cache[i % n])
    mix[0] ^= i
    mix = sha3_512(mix)
    for j in range(DAG_PARENTS):
        cache_index = fnv(i ^ j, mix[j % r])
        mix = map(fnv, mix, cache[cache_index % n])
    return sha3_512(mix)


def calc_dag(dag_size, cache):
    return [calc_dag_item(cache, i) for i in range(dag_size // MIX_BYTES)]


def hashimoto(header, nonce, dagsize, dag_lookup):
    n = dagsize / HASH_BYTES
    w = MIX_BYTES / WORD_BYTES
    mixhashes = MIX_BYTES / HASH_BYTES
    s = sha3_512(header + nonce)
    mix = []
    for _ in range(MIX_BYTES / HASH_BYTES):
        mix.extend(s)
    for i in range(ACCESSES):
        p = fnv(i ^ s[0], mix[i % w]) % (n // mixhashes) * mixhashes
        newdata = []
        for j in range(MIX_BYTES / HASH_BYTES):
            newdata.extend(dag_lookup(p + j))
        mix = map(fnv, mix, newdata)
    cmix = []
    for i in range(0, len(mix), 4):
        cmix.append(fnv(fnv(fnv(mix[i], mix[i+1]), mix[i+2]), mix[i+3]))
    return {
        "mixhash": serialize_hash(cmix),
        "result": serialize_hash(sha3_256(s+cmix))
    }


def hashimoto_light(full_size, cache, header, nonce):
    return hashimoto(header, nonce, full_size, lambda x: calc_dag_item(cache, x))


def hashimoto_full(full_size, dag, header, nonce):
    return hashimoto(header, nonce, len(dag), lambda x: dag[x])


def get_datasize(block_number):
    return DATASET_BYTES_INIT + DATASET_BYTES_GROWTH * (block_number // EPOCH_LENGTH)


def get_cachesize(block_number):
    return (DATASET_BYTES_INIT + DATASET_BYTES_GROWTH * (block_number // EPOCH_LENGTH)) / CACHE_MULTIPLIER


def mine(full_size, dag, header, difficulty):
    from random import randint
    nonce = randint(0, 2**64)
    while decode_int(hashimoto_full(full_size, dag, header, nonce)) < difficulty:
        nonce += 1
        nonce %= 2**64
    return nonce
