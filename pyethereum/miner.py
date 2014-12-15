import time
import struct
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
    """

    def __init__(self, parent, uncles, coinbase):
        self.nonce = 0
        ts = max(int(time.time()), parent.timestamp + 1)
        self.block = blocks.Block.init_from_parent(parent, coinbase, timestamp=ts,
                                                   uncles=[u.list_header() for u in uncles])
        self.pre_finalize_state_root = self.block.state_root
        self.block.finalize()
        log.debug('Mining', number=self.block.number, hash=self.block.hex_hash(),
                  difficulty=self.block.difficulty)

    def add_transaction(self, transaction):
        old_state_root = self.block.state_root
        # revert finalization
        self.block.state_root = self.pre_finalize_state_root
        try:
            success, output = processblock.apply_transaction(self.block, transaction)
        except processblock.InvalidTransaction as e:
            # if unsuccessfull the prerequistes were not fullfilled
            # and the tx isinvalid, state must not have changed
            log.debug('invalid tx', transaction=transaction, error=e)
            success = False

        # finalize
        self.pre_finalize_state_root = self.block.state_root
        self.block.finalize()

        if not success:
            log.debug('tx not applied', transaction=transaction)
            assert old_state_root == self.block.state_root
            return False
        else:
            assert transaction in self.block.get_transactions()
            log.debug('transaction applied', transaction=transaction,
                      block=self.block.hex_hash(), result=output)
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

        nonce_bin_prefix = '\x00' * (32 - len(struct.pack('>q', 0)))
        target = 2 ** 256 / self.block.difficulty
        rlp_Hn = self.block.serialize_header_without_nonce()

        for nonce in range(self.nonce, self.nonce + steps):
            nonce_bin = nonce_bin_prefix + struct.pack('>q', nonce)
            # BE(SHA3(SHA3(RLP(Hn)) o n))
            h = utils.sha3(utils.sha3(rlp_Hn) + nonce_bin)
            l256 = utils.big_endian_to_int(h)
            if l256 < target:
                self.block.nonce = nonce_bin
                assert self.block.check_proof_of_work(self.block.nonce) is True
                assert self.block.get_parent()
                log.debug('Nonce found', nonce=nonce, block=self.block.hex_hash())
                return self.block

        self.nonce = nonce
        return False
