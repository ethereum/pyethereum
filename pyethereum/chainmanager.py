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
import transactions
import processblock

logger = logging.getLogger(__name__)

rlp_hash_hex = lambda data: utils.sha3(rlp.encode(data)).encode('hex')


class Miner():

    """
    Mines on the current head
    Stores received transactions
    """

    def __init__(self, parent, coinbase):
        self.nonce = 0
        block = self.block = blocks.Block.init_from_parent(parent, coinbase)
        block.finalize()  # order?
        logger.debug('Mining #%d %s', block.number, block.hex_hash())
        logger.debug('Difficulty %s', block.difficulty)

    def add_transaction(self, transaction):
        """
        (1) The transaction signature is valid;
        (2) the transaction nonce is valid (equivalent to the
            sender accounts current nonce);
        (3) the gas limit is no smaller than the intrinsic gas,
            g0 , used by the transaction;
        (4) the sender account balance contains at least the cost,
            v0, required in up-front payment.
        """
        try:
            success, res = self.block.apply_transaction(transaction)
        except Exception, e:
            logger.debug('rejected transaction %r: %s', transaction, e)
            return False
        if not success:
            logger.debug('transaction %r not applied', transaction)
        else:
            logger.debug(
                'transaction %r applied to %r res: %r', transaction, self.block, res)
        return success

    def get_transactions(self):
        return self.block.get_transactions()

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
        block = self.block

        nonce_bin_prefix = '\x00' * (32 - len(pack('>q', 0)))
        prefix = block.serialize_header_without_nonce() + nonce_bin_prefix

        target = 2 ** 256 / block.difficulty

        for nonce in range(self.nonce, self.nonce + steps):
            h = sha3(sha3(prefix + pack('>q', nonce)))
            l256 = beti(h)
            if l256 < target:
                block.nonce = nonce_bin_prefix + pack('>q', nonce)
                assert block.check_proof_of_work(block.nonce) is True
                logger.debug(
                    'Nonce found %d %r', nonce, block)
                return block

        self.nonce = nonce
        return False


class ChainManager(StoppableLoopThread):

    """
    Manages the chain and requests to it.
    """

    def __init__(self):
        super(ChainManager, self).__init__()
        # initialized after configure
        self.miner = None
        self.blockchain = None

    def configure(self, config):
        self.config = config
        logger.info('Opening chain @ %s', utils.get_db_path())
        self.blockchain = DB(utils.get_db_path())
        logger.debug('Chain @ #%d %s', self.head.number, self.head.hex_hash())
        self.print_chain()
        self.new_miner()

    @property
    def head(self):
        if not 'HEAD' in self.blockchain:
            self._initialize_blockchain()
        ptr = self.blockchain.get('HEAD')
        return blocks.Block.deserialize(self.blockchain.get(ptr))

    def _update_head(self, block):
        self.blockchain.put('HEAD', block.hash)
        self.blockchain.commit()
        self.new_miner()  # reset mining

    def get(self, blockhash):
        return blocks.get_block(blockhash)

    def has_block(self, blockhash):
        return blockhash in self.blockchain

    def __contains__(self, blockhash):
        return self.has_block(blockhash)

    def _store_block(self, block):
        self.blockchain.put(block.hash, block.serialize())
        self.blockchain.commit()

    def _initialize_blockchain(self):
        logger.info('Initializing new chain @ %s', utils.get_db_path())
        genesis = blocks.genesis()
        self._store_block(genesis)
        self._update_head(genesis)
        self.blockchain.commit()

    def synchronize_blockchain(self):
        logger.info('synchronize requested for head %r', self.head)
        signals.remote_chain_requested.send(
            sender=self, parents=[self.head.hash], count=30)

    def loop_body(self):
        ts = time.time()
        pct_cpu = self.config.getint('misc', 'mining')
        if pct_cpu > 0:
            self.mine()
            delay = (time.time() - ts) * (100. / pct_cpu - 1)
            time.sleep(min(delay, 1.))
        else:
            time.sleep(.1)

    def new_miner(self):
        "new miner is initialized if HEAD is updated"
        miner = Miner(self.head, self.config.get('wallet', 'coinbase'))
        if self.miner:
            for tx in self.miner.get_transactions():
                miner.add_transaction(tx)
        self.miner = miner

    def mine(self):
        with self.lock:
            block = self.miner.mine()
            if block:
                # create new block
                self.add_block(block)
                time.sleep(5)
                signals.send_local_blocks.send(sender=self,
                                               blocks=[block])  # FIXME DE/ENCODE

    def receive_chain(self, blocks):
        old_head = self.head
        # assuming chain order w/ newest block first
        for block in blocks:
            if block.hash in self:
                logger.debug('Known %r', block)
            else:
                if block.has_parent():
                    # add block & set HEAD if it's longest chain
                    success = self.add_block(block)
                    if success:
                        logger.debug('Added %r', block)
                else:
                    logger.debug('Orphant %r', block)

        if self.head != old_head:
            self.synchronize_blockchain()

    # Returns True if block is latest
    def add_block(self, block):

        # make sure we know the parent
        # if not block.has_parent() and not block.is_genesis():
        if not block.has_parent() and block.hash != blocks.GENESIS_HASH:
            logger.debug('Missing parent for block %r', block.hex_hash())
            return False  # FIXME

        # check PoW
        if not len(block.nonce) == 32:
            logger.debug('Nonce not set %r', block.hex_hash())
            return False
        elif not block.check_proof_of_work(block.nonce) and not block.is_genesis():
            logger.debug('Invalid nonce %r', block.hex_hash())
            return False

        if block.has_parent():
            try:
                processblock.verify(block, block.get_parent())
            except AssertionError, e:
                logger.debug('verification failed: %s', str(e))
                processblock.verify(block, block.get_parent())
                return False

        self._store_block(block)
        # set to head if this makes the longest chain w/ most work
        if block.chain_difficulty() > self.head.chain_difficulty():
            logger.debug('New Head %r', block)
            self._update_head(block)

        return True

    def add_transaction(self, transaction):
        logger.debug("add transaction %r" % transaction)
        res = self.miner.add_transaction(transaction)
        if res:
            logger.debug("broadcasting valid %r" % transaction)
            signals.send_local_transactions.send(
                sender=self, transactions=[transaction])

    def get_transactions(self):
        logger.debug("get_transactions called")
        return self.miner.get_transactions()

    def get_chain(self, start='', count=100):
        "return 'count' blocks starting from head or start"
        logger.debug("get_chain: start:%s count%d", start.encode('hex'), count)
        blocks = []
        block = self.head
        if start:
            if not start in self:
                return []
            block = self.get(start)
            if not self.in_main_branch(block):
                return []
        for i in range(count):
            blocks.append(block)
            if block.is_genesis():
                break
            block = block.get_parent()
        return blocks

    def in_main_branch(self, block):
        if block.is_genesis():
            return True
        return block == self.get_descendents(block.get_parent(), count=1)[0]

    def get_descendents(self, block, count=1):
        logger.debug("get_descendents: %r ", block)
        assert block.hash in self
        # FIXME inefficient implementation
        res = []
        cur = self.head
        while cur != block:
            res.append(cur)
            if cur.has_parent():
                cur = cur.get_parent()
            else:
                break
            if cur.number == block.number and cur != block:
                # no descendents on main branch
                logger.debug("no descendents on main branch for: %r ", block)
                return []
        res.reverse()
        return res[:count]

    def print_chain(self):
        num = self.head.number + 1
        for b in reversed(self.get_chain(count=num)):
            logger.debug(b)
            for tx in b.get_transactions():
                logger.debug('\t%r', tx)


chain_manager = ChainManager()


@receiver(signals.local_chain_requested)
def handle_local_chain_requested(sender, blocks, count, **kwargs):
    """
    [0x14, Parent1, Parent2, ..., ParentN, Count]
    Request the peer to send Count (to be interpreted as an integer) blocks
    in the current canonical block chain that are children of Parent1
    (to be interpreted as a SHA3 block hash). If Parent1 is not present in
    the block chain, it should instead act as if the request were for Parent2 &c.
    through to ParentN.

    If none of the parents are in the current
    canonical block chain, then NotInChain should be sent along with ParentN
    (i.e. the last Parent in the parents list).

    If the designated parent is the present block chain head,
    an empty reply should be sent.

    If no parents are passed, then reply need not be made.
    """
    logger.debug(
        "local_chain_requested: %r %d", [b.encode('hex') for b in blocks], count)
    res = []
    for i, b in enumerate(blocks):
        if b in chain_manager:
            block = chain_manager.get(b)
            logger.debug("local_chain_requested: found: %r", block)
            res = chain_manager.get_descendents(block, count=count)
            if res:
                logger.debug("sending: found: %r ", res)
                res = [rlp.decode(b.serialize()) for b in res]  # FIXME
                # if b == head: no descendents == no reply
                with sender.lock:
                    sender.send_Blocks(res)
                return

    logger.debug("local_chain_requested: no matches")
    if len(blocks):
        #  If none of the parents are in the current
        sender.send_NotInChain(blocks[-1])
    else:
        # If no parents are passed, then reply need not be made.
        pass


@receiver(signals.config_ready)
def config_chainmanager(sender, **kwargs):
    chain_manager.configure(sender)


@receiver(signals.peer_handshake_success)
def new_peer_connected(sender, **kwargs):
    logger.debug("received new_peer_connected")
    # request transactions
    with sender.lock:
        logger.debug("send get transactions")
        sender.send_GetTransactions()
    # request chain
    blocks = [b.hash for b in chain_manager.get_chain(count=30)]
    with sender.lock:
        sender.send_GetChain(blocks, count=30)
        logger.debug("send get chain %r", [b.encode('hex') for b in blocks])


@receiver(signals.remote_transactions_received)
def remote_transactions_received_handler(sender, transactions, **kwargs):
    "receives rlp.decoded serialized"
    txl = [transactions.Transaction.deserialize(
        rlp.encode(tx)) for tx in transactions]
    logger.debug('remote_transactions_received: %r', txl)
    for tx in txl:
        chain_manager.add_transactions(tx)


@receiver(signals.local_transaction_received)
def local_transaction_received_handler(sender, transaction, **kwargs):
    "receives transaction object"
    logger.debug('local_transaction_received: %r', transaction)
    chain_manager.add_transaction(transaction)


@receiver(signals.local_transactions_requested)
def transactions_requested_handler(sender, req, **kwargs):
    transactions = chain_manager.get_transactions()
    signals.local_transactions_ready.send(sender=None, data=transactions)


@receiver(signals.remote_blocks_received)
def remote_blocks_received_handler(sender, block_lst, **kwargs):
    block_lst = [blocks.Block.deserialize(rlp.encode(b)) for b in block_lst]
    logger.debug("received blocks: %r", block_lst)
    with chain_manager.lock:
        chain_manager.receive_chain(block_lst)
