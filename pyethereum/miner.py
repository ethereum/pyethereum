import time
import struct
import sys
from pyethereum import blocks
from pyethereum import processblock
from pyethereum import utils
import rlp
from rlp.utils import encode_hex
from pyethereum.slogging import get_logger
log = get_logger('eth.miner')

pyethash = None
'''if sys.version_info.major == 2:
    import pyethash
else:
    from pyethereum import ethash as pyethash'''


class Miner():
    """
    Mines on the current head
    Stores received transactions

    The process of finalising a block involves four stages:
    1) Validate (or, if mining, determine) uncles;
    2) validate (or, if mining, determine) transactions;
    3) apply rewards;
    4) verify (or, if mining, compute a valid) state and nonce.
    """

    def __init__(self, parent, uncles, coinbase):
        self.nonce = 0
        self.db = parent.db
        ts = max(int(time.time()), parent.timestamp + 1)
        self.block = blocks.Block.init_from_parent(parent, coinbase, extra_data='', timestamp=ts,
                                                   uncles=uncles[:2])
        self.pre_finalize_state_root = self.block.state_root
        self.block.finalize()
        log.debug('mining', block_number=self.block.number,
                  block_hash=encode_hex(self.block.hash),
                  block_difficulty=self.block.difficulty)
        
        global pyethash
        if not pyethash:
            if sys.version_info.major == 2:
                pyethash = __import__('pyethash')
            else:
                pyethash = __import__('pyethereum.ethash')

    def add_transaction(self, transaction):
        old_state_root = self.block.state_root
        # revert finalization
        self.block.state_root = self.pre_finalize_state_root
        try:
            success, output = processblock.apply_transaction(self.block, transaction)
        except processblock.InvalidTransaction as e:
            # if unsuccessfull the prerequistes were not fullfilled
            # and the tx isinvalid, state must not have changed
            log.debug('invalid tx', tx_hash=transaction, error=e)
            success = False

        # finalize
        self.pre_finalize_state_root = self.block.state_root
        self.block.finalize()

        if not success:
            log.debug('tx not applied', tx_hash=transaction)
            assert old_state_root == self.block.state_root
            return False
        else:
            assert transaction in self.block.get_transactions()
            log.debug('transaction applied', tx_hash=transaction,
                      block_hash=self.block, result=output)
            assert old_state_root != self.block.state_root
            return True

    def get_transactions(self):
        return self.block.get_transactions()

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
        b = self.block
        sz = blocks.get_cache_size(b.number)
        cache = blocks.get_cache_memoized(b.db, b.header.seed, sz)
        fsz = blocks.get_full_size(b.number)
        nonce = utils.big_endian_to_int(b.nonce)
        TT64M1 = 2**64-1
        target = utils.zpad(utils.int_to_big_endian(2**256 // b.difficulty), 32)
        for i in range(1, steps + 1):
            b.nonce = utils.zpad(utils.int_to_big_endian((nonce + i) & TT64M1), 8)
            o = blocks.hashimoto_light(fsz, cache, b.mining_hash, b.nonce)
            if o["result"] <= target:
                b.mixhash = o["mix digest"]
                break
            steps -= 1
        if b.header.check_pow():
            return self.block

        self.nonce = nonce
        return False
