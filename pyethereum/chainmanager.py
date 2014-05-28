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
import processblock
from transactions import Transaction
import indexdb

logger = logging.getLogger(__name__)

rlp_hash_hex = lambda data: utils.sha3(rlp.encode(data)).encode('hex')


class Miner():

    """
    Mines on the current head
    Stores received transactions
    """

    def __init__(self, parent, uncles, coinbase):
        self.nonce = 0
        block = self.block = blocks.Block.init_from_parent(parent, coinbase)
        block.uncles = [u.hash for u in uncles]
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
            assert transaction in self.block.get_transactions()
        except Exception, e:
            logger.debug('rejected transaction %r: %s', transaction, e)
            return False
        if not success:
            logger.debug('transaction %r not applied', transaction)
        else:
            logger.debug(
                'transaction %r applied to %r res: %r',
                transaction, self.block, res)
        return success

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
                logger.debug(
                    'Nonce found %d %r', nonce, self.block)
                return self.block

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
        self._children_index = None

    def configure(self, config, genesis=None):
        self.config = config
        logger.info('Opening chain @ %s', utils.get_db_path())
        self.blockchain = DB(utils.get_db_path())
        self._children_index = indexdb.Index('ci')
        if genesis:
            self._initialize_blockchain(genesis)
        logger.debug('Chain @ #%d %s', self.head.number, self.head.hex_hash())
        self.log_chain()
        self.new_miner()

    @property
    def head(self):
        if 'HEAD' not in self.blockchain:
            self._initialize_blockchain()
        ptr = self.blockchain.get('HEAD')
        return blocks.get_block(ptr)

    def _update_head(self, block):
        bh = block.hash
        self.blockchain.put('HEAD', block.hash)
        self.blockchain.commit()
        self.new_miner()  # reset mining

    def get(self, blockhash):
        assert isinstance(blockhash, str)
        assert len(blockhash) == 32
        return blocks.get_block(blockhash)

    def has_block(self, blockhash):
        assert isinstance(blockhash, str)
        assert len(blockhash) == 32
        return blockhash in self.blockchain

    def __contains__(self, blockhash):
        return self.has_block(blockhash)

    def _store_block(self, block):
        self.blockchain.put(block.hash, block.serialize())
        self.blockchain.commit()

    def _initialize_blockchain(self, genesis=None):
        logger.info('Initializing new chain @ %s', utils.get_db_path())
        if not genesis:
            genesis = blocks.genesis()
        self._store_block(genesis)
        self._update_head(genesis)

    def synchronize_blockchain(self):
        logger.info('synchronize requested for head %r', self.head)
        signals.remote_chain_requested.send(
            sender=None, parents=[self.head.hash], count=256)

    def loop_body(self):
        ts = time.time()
        pct_cpu = self.config.getint('misc', 'mining')
        if pct_cpu > 0:
            self.mine()
            delay = (time.time() - ts) * (100. / pct_cpu - 1)
            time.sleep(min(delay, 1.))
        else:
            time.sleep(.01)

    def new_miner(self):
        "new miner is initialized if HEAD is updated"
        uncles = self.get_uncles(self.head)
        miner = Miner(self.head, uncles, self.config.get('wallet', 'coinbase'))
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
                logger.debug("broadcasting new %r" % block)
                signals.send_local_blocks.send(
                    sender=None, blocks=[block])

    def receive_chain(self, transient_blocks, disconnect_cb=None):
        old_head = self.head

        # assuming to receive chain order w/ newest block first
        for t_block in reversed(transient_blocks):
            logger.debug('Trying to deserialize %r', t_block)
            try:
                block = blocks.Block.deserialize(t_block.rlpdata)
            except blocks.UnknownParentException:

                number = t_block.number
                if t_block.prevhash == blocks.GENESIS_PREVHASH:
                    logger.debug('Incompatible Genesis %r', t_block)
                    if disconnect_cb:
                        disconnect_cb(reason='Wrong genesis block')
                else:
                    logger.debug('%s with unknown parent', t_block)
                    if number > self.head.number:
                        self.synchronize_blockchain()
                    else:
                        # FIXME synchronize with side chain
                        # check for largest number
                        pass
                break
            if block.hash in self:
                logger.debug('Known %r', block)
            else:
                if block.has_parent():
                    success = self.add_block(block)
                    if success:
                        logger.debug('Added %r', block)
                else:
                    logger.debug('Orphant %r', block)
        if self.head != old_head:
            self.synchronize_blockchain()

    def add_block(self, block):
        "returns True if block was added sucessfully"
        # make sure we know the parent
        if not block.has_parent() and not block.is_genesis():
            logger.debug('Missing parent for block %r', block)
            return False

        # make sure we know the uncles
        for uncle_hash in block.uncles:
            if not uncle_hash in self:
                logger.debug('Missing uncle for block %r', block)
                return False

        # check PoW
        if not len(block.nonce) == 32:
            logger.debug('Nonce not set %r', block)
            return False
        elif not block.check_proof_of_work(block.nonce) and\
                not block.is_genesis():
            logger.debug('Invalid nonce %r', block)
            return False

        with self.lock:
            if block.has_parent():
                try:
                    processblock.verify(block, block.get_parent())
                except AssertionError, e:
                    logger.debug('verification failed: %s', str(e))
                    processblock.verify(block, block.get_parent())
                    return False

            self._children_index.append(block.prevhash, block.hash)
            self._store_block(block)
            # set to head if this makes the longest chain w/ most work
            if block.chain_difficulty() > self.head.chain_difficulty():
                logger.debug('New Head %r', block)
                self._update_head(block)
            return True

    def get_children(self, block):
        return [self.get(c) for c in self._children_index.get(block.hash)]

    def get_uncles(self, block):
        if not block.has_parent():
            return []
        parent = block.get_parent()
        if not parent.has_parent():
            return []
        return [u for u in self.get_children(parent.get_parent())
                if u != parent]

    def add_transaction(self, transaction):
        logger.debug("add transaction %r" % transaction)
        with self.lock:
            res = self.miner.add_transaction(transaction)
            if res:
                logger.debug("broadcasting valid %r" % transaction)
                signals.send_local_transactions.send(
                    sender=None, transactions=[transaction])

    def get_transactions(self):
        logger.debug("get_transactions called")
        return self.miner.get_transactions()

    def get_chain(self, start='', count=256):
        "return 'count' blocks starting from head or start"
        logger.debug("get_chain: start:%s count%d", start.encode('hex'), count)
        blocks = []
        block = self.head
        if start:
            if start not in self:
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

    def log_chain(self):
        num = self.head.number + 1
        for b in reversed(self.get_chain(count=num)):
            logger.debug(b)
            for tx in b.get_transactions():
                logger.debug('\t%r', tx)


chain_manager = ChainManager()


@receiver(signals.local_chain_requested)
def handle_local_chain_requested(sender, peer, block_hashes, count, **kwargs):
    """
    [0x14, Parent1, Parent2, ..., ParentN, Count]
    Request the peer to send Count (to be interpreted as an integer) blocks
    in the current canonical block chain that are children of Parent1
    (to be interpreted as a SHA3 block hash). If Parent1 is not present in
    the block chain, it should instead act as if the request were for Parent2
    &c.  through to ParentN.

    If none of the parents are in the current
    canonical block chain, then NotInChain should be sent along with ParentN
    (i.e. the last Parent in the parents list).

    If the designated parent is the present block chain head,
    an empty reply should be sent.

    If no parents are passed, then reply need not be made.
    """
    logger.debug(
        "local_chain_requested: %r %d",
        [b.encode('hex') for b in block_hashes], count)
    found_blocks = []
    for i, b in enumerate(block_hashes):
        if b in chain_manager:
            block = chain_manager.get(b)
            logger.debug("local_chain_requested: found: %r", block)
            found_blocks = chain_manager.get_descendents(block, count=count)
            if found_blocks:
                logger.debug("sending: found: %r ", found_blocks)
                # if b == head: no descendents == no reply
                with peer.lock:
                    peer.send_Blocks(found_blocks)
                return

    if len(block_hashes):
        #  If none of the parents are in the current
        logger.debug(
            "Sending NotInChain: %r", block_hashes[-1].encode('hex')[:4])
        peer.send_NotInChain(block_hashes[-1])
    else:
        # If no parents are passed, then reply need not be made.
        pass


@receiver(signals.config_ready)
def config_chainmanager(sender, config, **kwargs):
    chain_manager.configure(config)


@receiver(signals.peer_handshake_success)
def new_peer_connected(sender, peer, **kwargs):
    logger.debug("received new_peer_connected")
    # request transactions
    with peer.lock:
        logger.debug("send get transactions")
        peer.send_GetTransactions()
    # request chain
    blocks = [b.hash for b in chain_manager.get_chain(count=256)]
    with peer.lock:
        peer.send_GetChain(blocks, count=256)
        logger.debug("send get chain %r", [b.encode('hex') for b in blocks])


@receiver(signals.remote_transactions_received)
def remote_transactions_received_handler(sender, transactions, **kwargs):
    "receives rlp.decoded serialized"
    txl = [Transaction.deserialize(rlp.encode(tx)) for tx in transactions]
    logger.debug('remote_transactions_received: %r', txl)
    for tx in txl:
        chain_manager.add_transaction(tx)


@receiver(signals.local_transaction_received)
def local_transaction_received_handler(sender, transaction, **kwargs):
    "receives transaction object"
    logger.debug('local_transaction_received: %r', transaction)
    chain_manager.add_transaction(transaction)


@receiver(signals.gettransactions_received)
def gettransactions_received_handler(sender, peer, **kwargs):
    transactions = chain_manager.get_transactions()
    transactions = [rlp.decode(x.serialize()) for x in transactions]
    peer.send_Transactions(transactions)


@receiver(signals.remote_blocks_received)
def remote_blocks_received_handler(sender, transient_blocks, peer, **kwargs):
    logger.debug("recv %d remote blocks: %r", len(
        transient_blocks), transient_blocks)
    chain_manager.receive_chain(
        transient_blocks, disconnect_cb=peer.send_Disconnect)
