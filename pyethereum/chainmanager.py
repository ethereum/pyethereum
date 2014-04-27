import logging
import time
import struct
from dispatch import receiver

from stoppable import StoppableLoopThread
import signals
from db import DB
import utils
import rlp
import blocks

logger = logging.getLogger(__name__)

rlp_hash_hex = lambda data: utils.sha3(rlp.encode(data)).encode('hex')


class ChainManager(StoppableLoopThread):

    """
    Manages the chain and requests to it.
    """

    coinbase = "0" * 40  # FIXME

    def __init__(self):
        super(ChainManager, self).__init__()
        self.transactions = set()
        self.blockchain = DB(utils.get_db_path())
        logger.debug('Chain @ #%d %s' %
                     (self.head.number, self.head.hex_hash()))
        self._mining_nonce = 0

    def configure(self, config):
        self.config = config

    @property
    def head(self):
        if not 'HEAD' in self.blockchain:
            self._initialize_blockchain()
        ptr = self.blockchain.get('HEAD')
        return blocks.Block.deserialize(self.blockchain.get(ptr))

    def _update_head(self, block):
        self.blockchain.put('HEAD', block.hash())
        self._mining_nonce = 0  # reset

    def get(self, blockhash):
        return blocks.get_block(blockhash)

    def has_block(self, blockhash):
        return blockhash in self.blockchain

    def __contains__(self, blockhash):
        return self.has_block(blockhash)

    def _store_block(self, block):
        self.blockchain.put(block.hash(), block.serialize())

    def _initialize_blockchain(self):
        logger.info('Initializing new chain @ %s', utils.get_db_path())
        genesis = blocks.genesis()
        self._store_block(genesis)
        self._update_head(genesis)
        self.blockchain.commit()

    # Returns True if block is latest
    def add_block(self, block):

        def summarized_difficulty(block):
            # calculate the summarized_difficulty (on the fly for now)
            if block.hash() == blocks.GENESIS_HASH:
                return block.difficulty
            else:
                return block.difficulty + summarized_difficulty(block.get_parent())

        # make sure we know the parent
        if not block.has_parent() and block.hash() != blocks.GENESIS_HASH:
            logger.debug('Missing parent for block %r' % block.hex_hash())
            return False  # FIXME

        # check PoW
        if not len(block.nonce) == 32:
            logger.debug('Nonce not set %r' % block.hex_hash())
            return False
        elif not block.is_genesis() and not block.check_proof_of_work(block.nonce):
            logger.debug('Invalid nonce %r' % block.hex_hash())
            return False

        self._store_block(block)

        # set to head if this makes the longest chain w/ most work
        if summarized_difficulty(block) > summarized_difficulty(self.head):
            self._update_head(block)
            self.blockchain.commit()
            return True

        self.blockchain.commit()
        return False

    def synchronize_blockchain(self):
        # FIXME: execute once, when connected to required num peers
        signals.remote_chain_requested.send(
            sender=self, parents=[self.head.hash()], count=30)

    def loop_body(self):
        self.mine()
        time.sleep(.01)
        # self.synchronize_blockchain()

    def mine(self, steps=1000):
        """
        It is formally defined as PoW:
        PoW(H, n) = BE(SHA3(SHA3(RLP(Hn)) o n))
        where: RLP(Hn) is the RLP encoding of the block header H,
        not including the final nonce component; SHA3 is the SHA3 hash function accepting
        an arbitrary length series of bytes and evaluating to a series of 32 bytes
        (i.e. 256-bit); n is the nonce, a series of 32 bytes; o is the series concatenation
        operator; BE(X) evaluates to the value equal to X when interpreted as a 
        big-endian-encoded integer.
        """

        pack = struct.pack
        sha3 = utils.sha3
        beti = utils.big_endian_to_int

        nonce = self._mining_nonce
        block = blocks.Block.init_from_parent(
            self.head, coinbase=self.coinbase)
        if nonce == 0:
            logger.debug('Mining %s', block.hex_hash())
            logger.debug('Difficulty %s', block.difficulty)

        nonce_bin_prefix = '\x00' * (32 - len(pack('>q', 0)))
        prefix = block.serialize_header_without_nonce() + nonce_bin_prefix

        target = 2 ** 256 / block.difficulty

        for nonce in range(nonce, nonce + steps):
            h = sha3(sha3(prefix + pack('>q', nonce)))
            l256 = beti(h)
            if l256 < target:
                block.nonce = nonce_bin_prefix + pack('>q', nonce)
                assert block.check_proof_of_work(block.nonce) is True
                assert len(block.nonce) == 32
                logger.debug('Nonce found %d %r', nonce, block.nonce)
                time.sleep(1)
                # create new block
                self.add_block(block)
                return

        self._mining_nonce = nonce

    def recv_blocks(self, block_lst):
        """
        block_lst is rlp decoded data
        """
        old_head = self.head

        new_blocks = set()
        for data in block_lst:
            logger.debug("processing block: %r", rlp_hash_hex(data))
            block = blocks.Block.deserialize(rlp.encode(data))
            if self.has_block(block.hash()):
                logger.debug('Known block %s', block.hex_hash())
            else:
                new_blocks.add(block)

        # no assumption about order of blocks revceived
        while new_blocks:
            could_append = False
            for block in set(new_blocks):
                if self.has_block(block.prevhash):
                    logger.debug('Adding new block %s', block.hex_hash())
                    self.add_block(block)
                    new_blocks.remove(block)
                    could_append = True
            if not could_append:
                logger.debug(
                    'Discarding blocks %r', [b.hex_hash() for b in new_blocks])
                break

        if self.head != old_head:
            self.synchronize_blockchain()

    def add_transactions(self, transactions):
        logger.debug("add transactions %r" % transactions)
        for tx in transactions:
            self.transactions.add(tx)

    def get_transactions(self):
        logger.debug("get transactions")
        return self.transactions

chain_manager = ChainManager()


@receiver(signals.config_ready)
def config_chainmanager(sender, **kwargs):
    chain_manager.configure(sender)


@receiver(signals.new_transactions_received)
def new_transactions_received_handler(sender, transactions, **kwargs):
    chain_manager.add_transactions(transactions)


@receiver(signals.transactions_requested)
def transactions_requested_handler(sender, req, **kwargs):
    transactions = chain_manager.get_transactions()
    signals.transactions_ready.send(sender=None, data=list(transactions))


@receiver(signals.blocks_requested)
def blocks_requested_handler(sender, req, **kwargs):
    pass


@receiver(signals.new_blocks_received)
def new_blocks_received_handler(sender, blocks, **kwargs):
    logger.debug("received blocks: %r" % ([rlp_hash_hex(b) for b in blocks]))
    chain_manager.recv_blocks(blocks)
