import logging
import time
from dispatch import receiver

from stoppable import StoppableLoopThread
from trie import rlp_hash, rlp_hash_hex
import signals
from db import DB
import utils
import rlp
from blocks import Block

logger = logging.getLogger(__name__)

GENESIS_H = 'ab6b9a5613970faa771b12d449b2e9bb925ab7a369f0a4b86b286e9d540099cf'\
            .decode('hex')


class ChainManager(StoppableLoopThread):

    """
    Manages the chain and requests to it.
    """

    def __init__(self):
        super(ChainManager, self).__init__()
        self.transactions = set()
        self.blockchain = DB(utils.get_db_path())
        self.head = None
        # FIXME: intialize blockchain with genesis block

    def _initialize_blockchain(self):
        genesis = blocks.genesis()

    # Returns True if block is latest
    def add_block(self, block):

        blockhash = block.hash()
        if blockhash == GENESIS_H:
            parent_score = 0
        else:
            try:
                parent = rlp.decode(self.blockchain.get(block.prevhash))
            except:
                raise Exception("Parent of block not found")
            parent_score = utils.big_endian_to_int(parent[1])
        total_score = utils.int_to_big_endian(block.difficulty + parent_score)
        self.blockchain.put(
            blockhash, rlp.encode([block.serialize(), total_score]))
        try:
            head = self.blockchain.get('head')
            head_data = rlp.decode(self.blockchain.get(head))
            head_score = utils.big_endian_to_int(head_data[1])
        except:
            head_score = 0
        if total_score > head_score:
            self.head = blockhash
            self.blockchain.put('head', blockhash)
            return True
        return False

    def configure(self, config):
        self.config = config

    def synchronize_blockchain(self):
        # FIXME: execute once, when connected to required num peers
        if self.head:
            return
        signals.remote_chain_requested.send(
            sender=self, parents=[GENESIS_H], count=30)

    def loop_body(self):
        self.mine()
        time.sleep(10)
        self.synchronize_blockchain()

    def mine(self):
        "in the meanwhile mine a bit, not efficient though"
        pass

    def recv_blocks(self, block_lst):
        """
        block_lst is rlp decoded data
        """

        block_lst.reverse()  # oldest block is sent first in list

        # FIXME validate received chain, compare with local chain
        for data in block_lst:
            logger.debug("processing block: %r" % rlp_hash_hex(data))
            block = Block.deserialize(rlp.encode(data))
            h = rlp_hash(data)
            try:
                self.blockchain.get(h)
            except KeyError:
                self.add_block(block)
                new_blocks_H.add(h)

 #       for h in new_blocks_H:
 #           logger.debug("recv_blocks: ask for child block %r" %
 #                        h.encode('hex'))
 #           signals.remote_chain_requested.send(
 #               sender=self, parents=[h], count=1)
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
    signals.transactions_ready.send(sender=None, data=transactions)


@receiver(signals.blocks_requested)
def blocks_requested_handler(sender, req, **kwargs):
    pass


@receiver(signals.new_blocks_received)
def new_blocks_received_handler(sender, blocks, **kwargs):
    logger.debug("received blocks: %r" % ([rlp_hash_hex(b) for b in blocks]))
    chain_manager.recv_blocks(blocks)
