from ethereum import ethash, ethash_utils, utils
import time
import sys
import sha3
from collections import OrderedDict
from ethereum.slogging import get_logger

log = get_logger('eth.pow')


if sys.version_info.major == 2:
    ETHASH_LIB = 'pyethash'
else:
    ETHASH_LIB = 'ethash'

if ETHASH_LIB == 'ethash':
    mkcache = ethash.mkcache
    EPOCH_LENGTH = ethash_utils.EPOCH_LENGTH
    hashimoto_light = ethash.hashimoto_light
elif ETHASH_LIB == 'pyethash':
    import pyethash
    mkcache = pyethash.mkcache_bytes
    EPOCH_LENGTH = pyethash.EPOCH_LENGTH
    hashimoto_light = lambda s, c, h, n: \
        pyethash.hashimoto_light(s, c, h, utils.big_endian_to_int(n))
else:
    raise Exception("invalid ethash library set")


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


def check_pow(block_number, header_hash, mixhash, nonce, difficulty, debugmode=False):
    """Check if the proof-of-work of the block is valid.

    :param nonce: if given the proof of work function will be evaluated
                  with this nonce instead of the one already present in
                  the header
    :returns: `True` or `False`
    """
    assert len(mixhash) == 32
    assert len(header_hash) == 32
    assert len(nonce) == 8

    # Grab current cache
    cache = get_cache(block_number)
    mining_output = hashimoto_light(block_number, cache, header_hash, nonce)
    if debugmode:
        log.debug('Mining hash: {}'.format(utils.encode_hex(header_hash)))
        log.debug('Mixhash: {}'.format(utils.encode_hex(mining_output['mix digest'])))
        log.debug('Result: {}'.format(utils.encode_hex(mining_output['result'])))
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

        global pyethash
        if not pyethash:
            if sys.version_info.major == 2:
                pyethash = __import__('pyethash')
            else:
                pyethash = __import__('ethereum.ethash')

    def mine(self, rounds=1000):
        """
        It is formally defined as PoW: PoW(H, n) = BE(SHA3(SHA3(RLP(Hn)) o n))
        where:
        RLP(Hn) is the RLP encoding of the block header H, not including the
            final nonce component;
        SHA3 is the SHA3 hash function accepting an arbitrary length series of
            bytes and evaluating to a series of 32 bytes (i.e. 256-bit);
        n is the nonce, a series of 32 bytes;
        o is the series concatenation operator;
        BE(X) evaluates to the value equal to X when interpreted as a
            big-endian-encoded integer.
        """
        blk = self.block
        cache = get_cache(blk.number)
        nonce = utils.big_endian_to_int(blk.nonce)
        TT64M1 = 2**64 - 1
        target = utils.zpad(utils.int_to_big_endian(2**256 // (blk.difficulty or 1)), 32)
        found = False
        log.debug("starting mining", rounds=rounds)
        for i in range(1, rounds + 1):
            blk.nonce = utils.zpad(utils.int_to_big_endian((nonce + i) & TT64M1), 8)
            o = hashimoto_light(blk.number, cache, blk.mining_hash, blk.nonce)
            if o["result"] <= target:
                log.debug("nonce found")
                blk.mixhash = o["mix digest"]
                found = True
                break
        if not found:
            return False

        assert len(blk.nonce) == 8
        assert len(blk.header.nonce) == 8
        assert len(blk.mixhash) == 32
        assert blk.header.check_pow()
        return blk
