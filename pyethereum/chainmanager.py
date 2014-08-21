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
import chainlogger
from peer import MAX_GET_CHAIN_SEND_HASHES
from peer import MAX_GET_CHAIN_REQUEST_BLOCKS

logger = logging.getLogger(__name__)

rlp_hash_hex = lambda data: utils.sha3(rlp.encode(data)).encode('hex')

NUM_BLOCKS_PER_REQUEST = 32 # MAX_GET_CHAIN_REQUEST_BLOCKS
MAX_GET_CHAIN_SEND_HASHES = 32 # lower for less traffic

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
        self.block = blocks.Block.init_from_parent(
            parent, coinbase, uncles=[u.list_header() for u in uncles])
        self.pre_finalize_state_root = self.block.state_root
        self.block.finalize()
        logger.debug('Mining #%d %s', self.block.number, self.block.hex_hash())
        logger.debug('Difficulty %s', self.block.difficulty)


    def add_transaction(self, transaction):
        old_state_root = self.block.state_root
        # revert finalization
        self.block.state_root = self.pre_finalize_state_root
        try:
            success, output = processblock.apply_transaction(
                self.block, transaction)
        except processblock.InvalidTransaction as e:
            # if unsuccessfull the prerequistes were not fullfilled
            # and the tx isinvalid, state must not have changed
            logger.debug('Invalid Transaction %r: %r', transaction, e)
            success = False

        # finalize
        self.pre_finalize_state_root = self.block.state_root
        self.block.finalize()

        if not success:
            logger.debug('transaction %r not applied', transaction)
            assert old_state_root == self.block.state_root
            return False
        else:
            assert transaction in self.block.get_transactions()
            logger.debug(
                'transaction %r applied to %r res: %r',
                transaction, self.block, output)
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
                logger.debug(
                    'Nonce found %d %r', nonce, self.block)
                return self.block

        self.nonce = nonce
        return False


class SynchronizationTask(object):
    """
    Created if we receive a block w/o known parent. Possibly from a different branch.

    Strategy:

    1) - divide the chain in MAX_GET_CHAIN_SEND_HASHES slices and
       - query for the first block of every slice

    2) - from the response of the peer use the highest common block and
       - lookup the corresponding slice
       - repeat 1) with the blocks in the slice

    3) - done once we find a block with a known parent in the local chain
    """

    def __init__(self, chain_manager, peer):
        self.chain_manager = chain_manager
        self.peer = peer
        self.slices = [] # containing the 1st block.hash of every slice
        self.request(start=blocks.genesis(), end=chain_manager.head)

    def request(self, start, end):
        """
        GetChain:
        [0x14, Parent1, Parent2, ..., ParentN, Count]
        Parent N being the parent with the lowest block_number
        """
        logger.debug("SynchronizationTask.request for %r start:%r end:%r", self.peer, start, end)
        # evenly divide the chain and select test blocks to be requested
        num = end.number - start.number
        num_slices = min(num, MAX_GET_CHAIN_SEND_HASHES)
        blk_numbers = [int(start.number + i * float(num)/num_slices) for i in range(num_slices)]
        logger.debug("SynchronizationTask.request numbers %r", blk_numbers)
        slices = [self.chain_manager.index.get_block_by_number(n) for n in blk_numbers]
        self.slices = slices
        logger.debug("SynchronizationTask.request blocks %r", [x.encode('hex') for x in slices])
        self.peer.send_GetChain(list(reversed(slices)), count=NUM_BLOCKS_PER_REQUEST)


    def received_blocks(self, transient_blocks):
        """
        if the the blocks are a response to our request:
        - we expect to receive successors of the highest requested block

        returns True if sync was successfull
        """
        logger.debug("SynchronizationTask.received_blocks: %r", transient_blocks)
        blk0 = transient_blocks[-1] # child of the requested one
        blkN = transient_blocks[0] # newest block in the chain following blk0
        assert blkN.number >= blk0.number

        if blk0.prevhash in self.slices: # gives us slot with highest known common block
            logger.debug("blk0 matched a slice")
            if blkN.prevhash not in self.chain_manager: # the chain split must be in this slice
                # we are done, the split is within the result
                # blocks will be added and new head eventually set
                logger.debug("blkN not yet in chain. synced!")
                return True
            else:
                idx = self.slices.index(blk0.prevhash)
                logger.debug("blkN in slice %d of %d", idx, len(self.slices))
                cm = self.chain_manager
                end = list(self.slices + [cm.head.hash])[idx+1]
                self.request(cm.get(blkN.prevhash), cm.get(end))



class Synchronizer(object):

    def __init__(self, chain_manager):
        self.chain_manager = chain_manager
        self.synchronization_tasks = {} # peer . syncer

    def synchronize_newer(self):
        logger.debug('sync successors for head %r', self.chain_manager.head)
        signals.remote_chain_requested.send(sender=None, parents=[self.chain_manager.head.hash],
                                            count=NUM_BLOCKS_PER_REQUEST)

    def synchronize_branch(self, peer):
        logger.debug('sync branch for peer %r', peer)
        if peer and not peer in self.synchronization_tasks:
            self.synchronization_tasks[peer] = SynchronizationTask(self.chain_manager, peer)
        else:
            logger.debug('have existing sync task for %r', peer)

    def received_blocks(self, peer, transient_blocks):
        if peer in self.synchronization_tasks:
            res = self.synchronization_tasks[peer].received_blocks(transient_blocks)
            if res is True:
                logger.debug("Synchronizer.received_blocks: chain w %r synced", peer)
                del self.synchronization_tasks[peer]


class Index(object):
    """"
    Collection of indexes

    children:
        - needed to get the uncles of a block
    blocknumbers:
        - needed to mark the longest chain (path to top)

    transactions:
        - optional to resolve txhash to block:tx

    """
    def __init__(self, db, index_transactions = True):
        self.db = db
        self.children_of = indexdb.Index('ci')
        self._index_transactions = index_transactions

    def add_block(self, blk):
        self.children_of.append(blk.prevhash, blk.hash)
        if self._index_transactions:
            self._add_transactions(blk)

    def update_blocknumbers(self, blk):
        "start from head and update until the existing indices match the block"
        while True:
            self.db.put('blocknumber:%d' % blk.number, blk.hash)
            if blk.number == 0:
                break
            blk = blk.get_parent()
            if blk.hash == self.get_block_by_number(blk.number):
                break

    def _add_transactions(self, blk):
        "'tx_hash' -> 'rlp([blockhash,tx_number])"
        for i in range(blk.transaction_count):
            i_enc = utils.encode_int(i)
            # work on rlp data to avoid unnecessary de/serialization
            td = blk.transactions.get(rlp.encode(i_enc))
            tx = rlp.descend(td, 0)
            key = utils.sha3(tx)
            value = rlp.encode([blk.hash, i_enc])
            self.db.put(key, value)

    def get_transaction(self, txhash):
        "return (tx, block)"
        blockhash, tx_num_enc = rlp.decode(self.db.get(txhash))
        blk = blocks.get_block(blockhash)
        num = utils.decode_int(tx_num_enc)
        tx_data, msr, gas  = blk.get_transaction(num)
        return Transaction.create(tx_data), blk

    def get_block_by_number(self, number):
        "returns block hash"
        return self.db.get('blocknumber:%d' % number)

    def get_children(self, blk_hash):
        "returns block hashes"
        return self.children_of.get(blk_hash)


class ChainManager(StoppableLoopThread):

    """
    Manages the chain and requests to it.
    """

    def __init__(self):
        super(ChainManager, self).__init__()
        # initialized after configure
        self.miner = None
        self.blockchain = None
        self.synchronizer = Synchronizer(self)

    def configure(self, config, genesis=None):
        self.config = config
        logger.info('Opening chain @ %s', utils.get_db_path())
        db = self.blockchain = DB(utils.get_db_path())
        self.index = Index(db)
        if genesis:
            self._initialize_blockchain(genesis)
        logger.debug('Chain @ #%d %s', self.head.number, self.head.hex_hash())
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
        self.index.update_blocknumbers(self.head)
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
            self.index.add_block(genesis)
        self._store_block(genesis)
        self._update_head(genesis)

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

    def receive_chain(self, transient_blocks, peer=None):
        with self.lock:
            old_head = self.head
            # assuming to receive chain order w/ newest block first
            assert transient_blocks[0].number >= transient_blocks[-1].number

            # notify syncer
            self.synchronizer.received_blocks(peer, transient_blocks)

            for t_block in reversed(transient_blocks): # oldest to newest
                logger.debug('Deserializing %r', t_block)
                #logger.debug(t_block.rlpdata.encode('hex'))
                try:
                    block = blocks.Block.deserialize(t_block.rlpdata)
                except processblock.InvalidTransaction as e:
                    # FIXME there might be another exception in
                    # blocks.deserializeChild when replaying transactions
                    # if this fails, we need to rewind state
                    logger.debug(
                        'Malicious %r w/ invalid Transaction %r', t_block, e)
                    continue
                except blocks.UnknownParentException:
                    if t_block.prevhash == blocks.GENESIS_PREVHASH:
                        logger.debug('Rec Incompatible Genesis %r', t_block)
                        if peer:
                            peer.send_Disconnect(reason='Wrong genesis block')
                    else:
                        logger.debug('%s with unknown parent, peer:%r', t_block, peer)
                        if peer:
                            self.synchronizer.synchronize_branch(peer)
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
                self.synchronizer.synchronize_newer()

    def add_block(self, block):
        "returns True if block was added sucessfully"
        # make sure we know the parent
        if not block.has_parent() and not block.is_genesis():
            logger.debug('Missing parent for block %r', block)
            return False

        # make sure we know the uncles
        # for uncle_hash in block.uncles:
        #     if not uncle_hash in self:
        #         logger.debug('Missing uncle for block %r', block)
        #        return False

        # check PoW and forward asap in order to avoid stale blocks
        if not len(block.nonce) == 32:
            logger.debug('Nonce not set %r', block)
            return False
        elif not block.check_proof_of_work(block.nonce) and\
                not block.is_genesis():
            logger.debug('Invalid nonce %r', block)
            return False

        # FIXME: Forward blocks w/ valid PoW asap

        if block.has_parent():
            try:
                logger.debug('verifying: %s', block)
                logger.debug('GETTING ACCOUNT FOR COINBASE:')
                acct = block.get_acct(block.coinbase)
                logger.debug('GOT ACCOUNT FOR COINBASE: %r', acct)

                processblock.verify(block, block.get_parent())
            except AssertionError as e:
                logger.debug('verification failed: %s', str(e))
                processblock.verify(block, block.get_parent())
                return False

        self.index.add_block(block)
        self._store_block(block)

        if block.number < self.head.number:
            logger.debug("%r is older than head %r", block, self.head)

        # FIXME: Should we have any limitations on adding blocks?

        # set to head if this makes the longest chain w/ most work for that number
        if block.chain_difficulty() > self.head.chain_difficulty():
            logger.debug('New Head %r', block)
            self._update_head(block)

        return True

    def get_children(self, block):
        return [self.get(c) for c in self.index.get_children(block.hash)]

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

    def get_chain(self, start='', count=NUM_BLOCKS_PER_REQUEST):
        "return 'count' blocks starting from head or start"
        logger.debug("get_chain: start:%s count%d", start.encode('hex'), count)
        blocks = []
        block = self.head
        if start:
            if start in self.index.db:
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
        try:
            return block.hash == self.index.get_block_by_number(block.number)
        except KeyError:
            return False

    def get_descendants(self, block, count=1):
        logger.debug("get_descendants: %r ", block)
        assert block.hash in self
        block_numbers = range(block.number+1, min(self.head.number, block.number+count))
        return [self.get(self.index.get_block_by_number(n)) for n in block_numbers]

    def log_chain(self):
        num = self.head.number + 1
        for b in reversed(self.get_chain(count=num)):
            #chainlogger.log_block(b)
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
            found_blocks = chain_manager.get_descendants(block, count=count)
            if found_blocks:
                logger.debug("sending: found: %r ", found_blocks)
                # if b == head: no descendants == no reply
                with peer.lock:
                    peer.send_Blocks(found_blocks)
                return

    if len(block_hashes):
        # handle genesis special case
        if False: # FIXME, current logic does not work
            if block_hashes[-1] in chain_manager:
                assert chain_manager.get(block_hashes[-1]).is_genesis()
                block_hashes.pop(-1)
                if not block_hashes:
                    return
            assert block_hashes[-1] not in chain_manager
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
    with peer.lock:
        chain_manager.synchronizer.synchronize_branch(peer)

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
    if transient_blocks:
        chain_manager.receive_chain(transient_blocks, peer)