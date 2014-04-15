import logging
import Queue

from dispatch import receiver

from common import StoppableLoopThread
from trie import rlp_hash, rlp_hash_hex
import signals

logger = logging.getLogger(__name__)


class ChainManager(StoppableLoopThread):

    """
    Manages the chain and requests to it.
    """

    def __init__(self):
        super(ChainManager, self).__init__()
        self.transactions = set()
        self.dummy_blockchain = dict()  # hash > block
        self.request_queue = Queue.Queue()

    def configure(self, config):
        self.config = config

    def bootstrap_blockchain(self):
        # genesis block
        # http://etherchain.org/#/block/
        # ab6b9a5613970faa771b12d449b2e9bb925ab7a369f0a4b86b286e9d540099cf
        if len(self.dummy_blockchain):
            return
        genesis_H = 'ab6b9a5613970faa771b12d449b2e9bb925ab7a369f'\
            '0a4b86b286e9d540099cf'.decode('hex')
        self.out_proxy.send_get_chain(count=1, parents_H=[genesis_H])

    def loop_body(self):
        self.process_request_queue()
        self.mine()

    def mine(self):
        "in the meanwhile mine a bit, not efficient though"
        pass

    def _recv_blocks(self, blocks):
        new_blocks_H = set()
        # memorize
        for block in blocks:
            h = rlp_hash(block)
            print self, "_recv_blocks:",  rlp_hash_hex(block)
            if h not in self.dummy_blockchain:
                new_blocks_H.add(h)
                self.dummy_blockchain[h] = block
        # ask for children
        for h in new_blocks_H:
            print self, "_recv_blocks: ask for child block", h.encode('hex')
            self.out_proxy.send_get_chain(1, [h])

    def process_request_queue(self):
        try:
            command = self.request_queue.get(block=True, timeout=0.1)
        except Queue.Empty:
            return

        cmd, data = command[0], command[1:]

        logger.debug('%r received %s datalen:%d' % (self, cmd, len(data)))
        if cmd == "add_blocks":
            print self, "add_blocks in queue seen"
            self._recv_blocks(data)
        elif cmd == "add_transactions":
            tx_list = data[0]
            for tx in tx_list:
                self.transactions.add(tx)
        elif cmd == "request_blocks":
            pass
        elif cmd == 'request_transactions':
            peer_id = data[0]
            signals.transactions_data_ready(self.transactions, peer_id)
        else:
            raise Exception('unknown commad')


chain_manager = ChainManager()


@receiver(signals.config_ready)
def config_chainmanager(sender, **kwargs):
    chain_manager.configure(sender)


@receiver(signals.transactions_data_requested)
def transactions_data_requested_handler(sender, request_data, **kwargs):
    chain_manager.request_queue.put('request_transactions', request_data)


@receiver(signals.blocks_data_requested)
def blocks_data_requested_handler(sender, request_data, **kwargs):
    chain_manager.request_queue.put('request_blocks', request_data)


@receiver(signals.new_blocks_received)
def new_blocks_received_handler(sender, blocks, **kwargs):
        print "received blocks", [rlp_hash_hex(b) for b in blocks]
        chain_manager.request_queue.add_blocks(blocks)
