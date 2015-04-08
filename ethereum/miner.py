import time
import sys
from ethereum import blocks
from ethereum import processblock
from ethereum import utils
from rlp.utils import encode_hex
from ethereum.slogging import get_logger
log = get_logger('eth.miner')

pyethash = None
'''if sys.version_info.major == 2:
    import pyethash
else:
    from ethereum import ethash as pyethash'''


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
                  block_hash=encode_hex(self.block.hash),
                  block_difficulty=self.block.difficulty)

        global pyethash
        if not pyethash:
            if sys.version_info.major == 2:
                pyethash = __import__('pyethash')
            else:
                pyethash = __import__('ethereum.ethash')

    def mine(self, steps=1000):
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
        #b = self.block
        sz = blocks.get_cache_size(self.block.number)
        cache = blocks.get_cache_memoized(self.block.db, self.block.header.seed, sz)
        fsz = blocks.get_full_size(self.block.number)
        nonce = utils.big_endian_to_int(self.block.nonce)
        TT64M1 = 2**64 - 1
        target = utils.zpad(utils.int_to_big_endian(2**256 // (self.block.difficulty or 1)), 32)
        near_target = target[1:] + '\x00'
        dtarget = utils.big_endian_to_int(target)
        found = False
        sys.stderr.write("Starting mining\n")
        for i in range(1, steps + 1):
            self.block.nonce = utils.zpad(utils.int_to_big_endian((nonce + i) & TT64M1), 8)
            o = blocks.hashimoto_light(fsz, cache, self.block.mining_hash,
                                       self.block.nonce)
            if o["result"] <= near_target:
                if o["result"] <= target:
                    sys.stderr.write("Success!\n")
                    self.block.mixhash = o["mix digest"]
                    found = True
                    break
                else:
                    r = utils.big_endian_to_int(o["result"])
                    sys.stderr.write('Near miss, %f %% of threshold!\n' %
                                     (dtarget * 100.0 / r))
            steps -= 1
        if not found:
            return False

        assert len(self.block.nonce) == 8
        assert len(self.block.mixhash) == 32
        assert self.block.header.check_pow()
        return self.block
