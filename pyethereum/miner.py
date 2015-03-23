import struct
import time
import pyethash
import rlp
import blocks
import processblock
import utils
from pyethereum.slogging import get_logger
log = get_logger('eth.miner')


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
                  block_hash=self.block.hash.encode('hex'),
                  block_difficulty=self.block.difficulty)

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

        :param steps: the number of nonces to try
        :returns: either the newly mined block with updated nonce, or `False`
                  if mining was not successful (in which case the nonce is
                  not changed)
        """
        target = 2 ** 256 / self.block.difficulty
        rlp_Hn = rlp.encode(block.header, blocks.BlockHeader.exclude(['nonce']))

        for nonce in range(self.nonce, self.nonce + steps):
            nonce_bin = struct.pack('>q', nonce)
            # BE(SHA3(SHA3(RLP(Hn)) o n))
            h = utils.sha3(utils.sha3(rlp_Hn) + nonce_bin)
            l256 = utils.big_endian_to_int(h)
            if l256 < target:
                self.block.nonce = nonce_bin
                assert self.block.header.check_pow() is True
                assert self.block.get_parent()
                log.debug('nonce found', block_nonce=nonce,
                          block_hash=self.block.hash.encode('hex'))
                return self.block

        self.nonce = nonce
        return False
