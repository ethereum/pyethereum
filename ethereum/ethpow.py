from ethereum import ethash, ethash_utils, utils
import time
import sys
import sha3
import warnings
from collections import OrderedDict
from ethereum.slogging import get_logger

log = get_logger('eth.pow')

if sys.version_info.major == 2:
    from repoze.lru import lru_cache
else:
    from functools import lru_cache

try:
    import pyethash
    ETHASH_LIB = 'pyethash'  # the C++ based implementation
except ImportError:
    ETHASH_LIB = 'ethash'
    warnings.warn('using pure python implementation', ImportWarning)

if ETHASH_LIB == 'ethash':
    mkcache = ethash.mkcache
    EPOCH_LENGTH = ethash_utils.EPOCH_LENGTH
    hashimoto_light = ethash.hashimoto_light
elif ETHASH_LIB == 'pyethash':
    mkcache = pyethash.mkcache_bytes
    EPOCH_LENGTH = pyethash.EPOCH_LENGTH
    hashimoto_light = lambda s, c, h, n: \
        pyethash.hashimoto_light(s, c, h, utils.big_endian_to_int(n))
else:
    raise Exception("invalid ethash library set")

TT64M1 = 2**64 - 1
cache_seeds = ['\x00' * 32]
cache_by_seed = OrderedDict()
cache_by_seed.max_items = 10


def get_cache(block_number):
    while len(cache_seeds) <= block_number // EPOCH_LENGTH:
        cache_seeds.append(sha3.sha3_256(cache_seeds[-1]).digest())
    seed = cache_seeds[block_number // EPOCH_LENGTH]
    if seed in cache_by_seed:
        c = cache_by_seed.pop(seed)  # pop and append at end
        cache_by_seed[seed] = c
        return c
    c = mkcache(block_number)
    cache_by_seed[seed] = c
    if len(cache_by_seed) > cache_by_seed.max_items:
        cache_by_seed.pop(cache_by_seed.keys()[0])  # remove last recently accessed
    return c


@lru_cache(maxsize=32)
def check_pow(block_number, header_hash, mixhash, nonce, difficulty):
    """Check if the proof-of-work of the block is valid.

    :param nonce: if given the proof of work function will be evaluated
                  with this nonce instead of the one already present in
                  the header
    :returns: `True` or `False`
    """
    log.debug('checking pow', block_number=block_number)
    if len(mixhash) != 32 or len(header_hash) != 32 or len(nonce) != 8:
        return False

    # Grab current cache
    cache = get_cache(block_number)
    mining_output = hashimoto_light(block_number, cache, header_hash, nonce)
    if mining_output['mix digest'] != mixhash:
        return False
    return utils.big_endian_to_int(mining_output['result']) <= 2**256 / (difficulty or 1)


class Miner():

    """
    Mines on the current head
    Stores received transactions

    The process of finalising a block involves four stages:
    1) Validate (or, if mining, determine) uncles;
    2) validate (or, if mining, determine) transactions;
    3) apply rewards;
    4) verify (or, if mining, compute a valid) state and nonce.

    :param block: the block for which to find a valid nonce
    """

    def __init__(self, block):
        self.nonce = 0
        self.block = block
        log.debug('mining', block_number=self.block.number,
                  block_hash=utils.encode_hex(self.block.hash),
                  block_difficulty=self.block.difficulty)

    def mine(self, rounds=1000, start_nonce=0):
        blk = self.block
        bin_nonce, mixhash = mine(blk.number, blk.difficulty, blk.mining_hash,
                                  start_nonce=start_nonce, rounds=rounds)
        if bin_nonce:
            blk.mixhash = mixhash
            blk.nonce = bin_nonce
            return blk


def mine(block_number, difficulty, mining_hash, start_nonce=0, rounds=1000):
    assert utils.isnumeric(start_nonce)
    cache = get_cache(block_number)
    nonce = start_nonce
    target = utils.zpad(utils.int_to_big_endian(2**256 // (difficulty or 1)), 32)
    for i in range(1, rounds + 1):
        bin_nonce = utils.zpad(utils.int_to_big_endian((nonce + i) & TT64M1), 8)
        o = hashimoto_light(block_number, cache, mining_hash, bin_nonce)
        if o["result"] <= target:
            log.debug("nonce found")
            assert len(bin_nonce) == 8
            assert len(o["mix digest"]) == 32
            return bin_nonce, o["mix digest"]
    return None, None
