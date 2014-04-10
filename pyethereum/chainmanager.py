import rlp
import threading
import Queue
import logging
from sha3 import sha3_256

logger = logging.getLogger(__name__)

rlp_hash = lambda data: sha3_256(rlp.encode(data)).digest()
rlp_hash_hex = lambda data: sha3_256(rlp.encode(data)).hexdigest()


class ChainManagerInProxy(object):

    """
    In port of ChainManager to accept command

    stateless, queues are shared between all instances
    Will we have an  API?
    http://forum.ethereum.org/discussion/247/how-will-the-outside-api-be-like
    """

    in_queue = Queue.Queue()

    def add_blocks(self, blocks):
        logger.debug("chainmanager add blocks:", [rlp_hash(b) for b in blocks])
        self.in_queue.put(('add_blocks', blocks))

    def add_transactions(self, transactions):
        self.in_queue.put(('add_transactions', transactions))

    def request_blocks(self, block_hashes, peer):
        self.in_queue.put(('request_blocks', block_hashes, peer.id()))

    def request_transactions(self, peer):
        self.in_queue.put(('request_transactions', peer.id()))

    def get_next_cmd(self):
        try:
            return self.in_queue.get(timeout=.1)
        except Queue.Empty:
            return None


class ChainManagerOutProxy(object):

    """
    Out port of ChainManager to send out command

    stateless, queues are shared between all instances
    """
    out_queue = Queue.Queue()

    def send_blocks(self, blks, peer_id=False):
        "broadcast if no peer specified"

    def send_transactions(self, transactions, peer_id=False):
        "broadcast if no peer specified"
        self.out_queue.put('send_transactions', transactions, peer_id)

    def send_not_in_chain(self, hash, peer_id):
        "broadcast if no peer specified"
        pass

    def send_get_chain(self, count=1, parents_H=[]):
        self.out_queue.put(('get_chain', count, parents_H))

    def get_next_cmd(self):
        try:
            return self.out_queue.get(timeout=.1)
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
        # self.blockchain = blockchain
        self.transactions = set()
        self.dummy_blockchain = dict()  # hash > block
        self.in_proxy = ChainManagerInProxy()
        self.out_proxy = ChainManagerOutProxy()

    def bootstrap_blockchain(self):
        # genesis block
        # http://etherchain.org/#/block/
        # ab6b9a5613970faa771b12d449b2e9bb925ab7a369f0a4b86b286e9d540099cf
        if len(self.dummy_blockchain):
            return
        genesis_H = 'ab6b9a5613970faa771b12d449b2e9bb925ab7a369f'\
            '0a4b86b286e9d540099cf'.decode('hex')
        self.out_proxy.send_get_chain(count=1, parents_H=[genesis_H])

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
            self.process_in_cmd()
            self.mine()

    def mine(self):
        "in the meanwhile mine a bit, not efficient though"
        pass

    def _rcv_blocks(self, blocks):
        new_blocks_H = set()
        # memorize
        for block in blocks:
            h = rlp_hash(block)
            print self, "_rcv_blocks:",  rlp_hash_hex(block)
            if h not in self.dummy_blockchain:
                new_blocks_H.add(h)
                self.dummy_blockchain[h] = block
        # ask for children
        for h in new_blocks_H:
            print self, "_rcv_blocks: ask for child block", h.encode('hex')
            self.out_proxy.send_get_chain(1, [h])

    def process_in_cmd(self):
        command = self.in_proxy.get_next_cmd()
        if not command:
            return
        cmd, data = command[0], command[1:]

        logger.debug('%r received %s datalen:%d' % (self, cmd, len(data)))
        if cmd == "add_blocks":
            print self, "add_blocks in queue seen"
            self._rcv_blocks(data)
        elif cmd == "add_transactions":
            tx_list = data[0]
            for tx in tx_list:
                self.transactions.add(tx)
        elif cmd == "request_blocks":
            pass
        elif cmd == 'request_transactions':
            peer_id = data[0]
            self.out_proxy.send_transactions(self.transactions, peer_id)
        else:
            raise Exception('unknown commad')
