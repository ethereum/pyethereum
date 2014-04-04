import rlp
from blocks import Block
from transactions import Transaction
import threading
import Queue
import logging
from sha3 import sha3_256

logger = logging.getLogger(__name__)

rlp_hash =  lambda data: sha3_256(rlp.encode(data)).digest()
rlp_hash_hex = lambda data: sha3_256(rlp.encode(data)).hexdigest()

class ChainProxy():
    """
    abstract external access to the blockchain
    stateless, queues are shared between all instances

    Will we have an  API?
    http://forum.ethereum.org/discussion/247/how-will-the-outside-api-be-like
    """

    chain_queue = Queue.Queue()

    def __init__(self):
        self.network_queue = NetworkProxy.network_queue

    def add_blocks(self, blocks):
        print "chainmanager add blocks", [rlp_hash(b) for b in blocks]
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

    def send_get_chain(self, count=1, parents_H=[]):
        self.network_queue.put(('get_chain', count, parents_H))

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
        # self.blockchain = blockchain
        self.transactions = set()
        self.dummy_blockchain = dict() # hash > block

    def bootstrap_blockchain(self):
        # genesis block
        # http://etherchain.org/#/block/ab6b9a5613970faa771b12d449b2e9bb925ab7a369f0a4b86b286e9d540099cf
        if len(self.dummy_blockchain):
            return
        genesis_H = 'ab6b9a5613970faa771b12d449b2e9bb925ab7a369f0a4b86b286e9d540099cf'.decode('hex')
        self.network.send_get_chain(count=1, parents_H=[genesis_H])


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

    def rcv_blocks(self, blocks):

        new_blocks_H = set()        
        # memorize
        for block in blocks:
            h = rlp_hash(block) 
            print self, "rcv_blocks:",  rlp_hash_hex(block) 
            if not h in self.dummy_blockchain:
                new_blocks_H.add(h)
                self.dummy_blockchain[h] = block
        # ask for children                
        for h in new_blocks_H:
            print self, "rcv_blocks: ask for child block", h.encode('hex')
            self.network.send_get_chain(1, [h])



    def process_queue(self):
        msg = self.network.pop_message()
        if not msg:
            return
        cmd, data = msg[0], msg[1:]

        logger.debug('%r received %s datalen:%d' % (self, cmd, len(data)))
        if cmd == "add_blocks":
            print self, "add_blocks in queue seen"
            self.rcv_blocks(data)
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
