import rlp
from blocks import Block
from transactions import Transaction
import threading
import Queue
import logging


logger = logging.getLogger(__name__)


class ChainProxy():
    """ 
    abstract external access to the blockchain
    stateless, queues are shared between all instances
    """

    chain_queue = Queue.Queue()

    def __init__(self):
        self.network_queue = NetworkProxy.network_queue

    def add_blocks(self, blocks):
        self.chain_queue.put(('add_blocks', blocks))

    def add_transactions(self, transactions):
        self.chain_queue.put(('add_transactions', transactions))
       
    def request_blocks(self, block_hashes, peer):
        self.chain_queue.put(('request_blocks', block_hashes, peer.id()))

    def request_transactions(self, peer):
        self.chain_queue.put(('request_transactions', peer.id()))

    def pingpong(self, reply=False):
        self.chain_queue.put(('pingpong', reply))

    def pop_message(self):
        try:
            return self.network_queue.get(timeout=.1)
        except Queue.Empty:
            return None



class NetworkProxy():
    """
    abstracts access to the network
    stateless, queues are shared between all instances
    """
    network_queue = Queue.Queue()

    def __init__(self):
        self.chain_queue = ChainProxy.chain_queue

    def send_blocks(self, blks, peer_id=False):
        "broadcast if no peer specified"

    def send_transactions(self, transactions, peer_id=False):
        "broadcast if no peer specified"
        self.network_queue.put('send_transactions', transactions, peer_id)

    def send_not_in_chain(self, hash, peer_id):
        "broadcast if no peer specified"
        pass


    def pingpong(self, reply=False):
        self.network_queue.put(('pingpong', reply))

    def pop_message(self):
        try:
            return self.chain_queue.get(timeout=.1)
        except Queue.Empty:
            return None


class ChainManager(threading.Thread):
    """
    Manages the chain and requests to it.
    """
    def __init__(self, config):
        threading.Thread.__init__(self)
        self._stopped = False
        self.lock = threading.Lock()
        self.network = NetworkProxy()
        #self.blockchain = blockchain
        self.transactions = set()

    def stop(self):
        with self.lock:
            if self._stopped:
                return
            self._stopped = True

    def stopped(self):
        with self.lock:
            return self._stopped

    def run(self):
        while not self.stopped():
            self.process_queue()
            self.mine()

    def mine(self):
        "in the meanwhile mine a bit, not efficient though"
        pass

    def process_queue(self):
        msg = self.network.pop_message()
        if not msg:
            return
        cmd, data = msg[0], msg[1:]

        logger.debug('%r received %s datalen:%d' % (self, cmd, len(data)))
        if cmd == "add_blocks":
            self.transactions = set()            
        elif cmd == "add_transactions":
            tx_list = data[0]
            for tx in tx_list:
                self.transactions.add(tx)
        elif cmd == "request_blocks":
            pass
        elif cmd == 'request_transactions':
            peer_id = data[0]
            self.network.send_transactions(self.transactions, peer_id)

        elif cmd == 'pingpong':
            reply = data
            logger.debug('%r received pingpong(reply=%r)' % (self, reply))
            if reply:
                self.network.pingpong()
        else:
            raise Exception('unknown commad')

        



