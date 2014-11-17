import time
import os
from operator import attrgetter
from dispatch import receiver
from stoppable import StoppableLoopThread
import signals
from db import DB
import utils
import rlp
import blocks
import processblock
import peermanager
from transactions import Transaction
from miner import Miner
from synchronizer import Synchronizer
from pyethereum.tlogging import log_chain_debug as log_debug
from pyethereum.tlogging import log_chain_info as log_info
from pyethereum.tlogging import log_chain_warn as log_warn
from peer import MAX_GET_CHAIN_SEND_HASHES
from peer import MAX_GET_CHAIN_REQUEST_BLOCKS

rlp_hash_hex = lambda data: utils.sha3(rlp.encode(data)).encode('hex')

NUM_BLOCKS_PER_REQUEST = 256  # MAX_GET_CHAIN_REQUEST_BLOCKS


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

    def __init__(self, db, index_transactions=True):
        self.db = db
        self._index_transactions = index_transactions

    def add_block(self, blk):
        self.add_child(blk.prevhash, blk.hash)
        if self._index_transactions:
            self._add_transactions(blk)

    # block by number #########
    def _block_by_number_key(self, number):
        return 'blocknumber:%d' % number

    def update_blocknumbers(self, blk):
        "start from head and update until the existing indices match the block"
        while True:
            self.db.put(self._block_by_number_key(blk.number), blk.hash)
            if blk.number == 0:
                break
            blk = blk.get_parent()
            if self.has_block_by_number(blk.number) and \
                    self.get_block_by_number(blk.number) == blk.hash:
                break

    def has_block_by_number(self, number):
        return self._block_by_number_key(number) in self.db

    def get_block_by_number(self, number):
        "returns block hash"
        return self.db.get(self._block_by_number_key(number))

    # transactions #############
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
        "return (tx, block, index)"
        blockhash, tx_num_enc = rlp.decode(self.db.get(txhash))
        blk = blocks.get_block(blockhash)
        num = utils.decode_int(tx_num_enc)
        tx_data, msr, gas = blk.get_transaction(num)
        return Transaction.create(tx_data), blk, num

    # children ##############

    def _child_db_key(self, blk_hash):
        return 'ci:' + blk_hash

    def add_child(self, parent_hash, child_hash):
        # only efficient for few children per block
        children = self.get_children(parent_hash) + [child_hash]
        assert children.count(child_hash) == 1
        self.db.put(self._child_db_key(parent_hash), rlp.encode(children))

    def get_children(self, blk_hash):
        "returns block hashes"
        key = self._child_db_key(blk_hash)
        if key in self.db:
            return rlp.decode(self.db.get(key))
        return []


class ChainManager(StoppableLoopThread):

    """
    Manages the chain and requests to it.
    """

    # initialized after configure:
    genesis = None
    index = None
    miner = None
    blockchain = None
    synchronizer = None

    def __init__(self):
        super(ChainManager, self).__init__()

    def configure(self, config, genesis=None):
        self.config = config
        log_info('Opening chain @ %s', utils.get_db_path())
        db = self.blockchain = DB(utils.get_db_path())
        self.index = Index(db)
        if genesis:
            self._initialize_blockchain(genesis)
        log_debug('Chain @ #%d %s', self.head.number, self.head.hex_hash())
        self.genesis = blocks.CachedBlock.create_cached(blocks.genesis())
        self.new_miner()
        self.synchronizer = Synchronizer(self)

    @property
    def head(self):
        if 'HEAD' not in self.blockchain:
            self._initialize_blockchain()
        ptr = self.blockchain.get('HEAD')
        return blocks.get_block(ptr)

    def _update_head(self, block):
        if not block.is_genesis():
            assert self.head.chain_difficulty() < block.chain_difficulty()
            if block.get_parent() != self.head:
                log_debug('New Head %r is on a different branch. Old was:%r', block, self.head)
        self.blockchain.put('HEAD', block.hash)
        self.index.update_blocknumbers(self.head)
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

    def commit(self):
        self.blockchain.commit()

    def _initialize_blockchain(self, genesis=None):
        log_info('Initializing new chain @ %s', utils.get_db_path())
        if not genesis:
            genesis = blocks.genesis()
            self.index.add_block(genesis)
        self._store_block(genesis)
        self._update_head(genesis)
        assert genesis.hash in self

    def loop_body(self):
        ts = time.time()
        pct_cpu = self.config.getint('misc', 'mining')
        if pct_cpu > 0:
            self.mine()
            delay = (time.time() - ts) * (100. / pct_cpu - 1)
            if delay < 0:
                log_warn('delay %r<0!?', delay)
                delay = 1
            assert delay >= 0
            time.sleep(min(delay, 1.))
        else:
            time.sleep(.01)

    def new_miner(self):
        "new miner is initialized if HEAD is updated"
        # prepare uncles
        uncles = set(self.get_uncles(self.head))
#        log_debug('%d uncles for next block %r', len(uncles), uncles)
        ineligible = set()  # hashes
        blk = self.head
        for i in range(8):
            for u in blk.uncles:  # assuming uncle headres
                u = utils.sha3(rlp.encode(u))
                if u in self:
#                    log_debug('ineligible uncle %r', u.encode('hex'))
                    uncles.discard(self.get(u))
            if blk.has_parent():
                blk = blk.get_parent()
#        log_debug('%d uncles after filtering %r', len(uncles), uncles)

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
                if not self.add_block(block, forward=True):
                    log_debug("newly mined %r is invalid!?" % block)
                    self.new_miner()

    def receive_chain(self, transient_blocks, peer=None):
        with self.lock:
            old_head = self.head
            # assuming to receive chain order w/ oldest block first
            transient_blocks.sort(key=attrgetter('number'))
            assert transient_blocks[0].number <= transient_blocks[-1].number

            # notify syncer
            self.synchronizer.received_blocks(peer, transient_blocks)

            for t_block in transient_blocks:  # oldest to newest
                log_debug('Deserializing %r', t_block)
                # log_debug(t_block.rlpdata.encode('hex'))
                try:
                    block = blocks.Block.deserialize(t_block.rlpdata)
                except processblock.InvalidTransaction as e:
                    # FIXME there might be another exception in
                    # blocks.deserializeChild when replaying transactions
                    # if this fails, we need to rewind state
                    log_debug('%r w/ invalid Transaction %r', t_block, e)
                    # stop current syncing of this chain and skip the child blocks
                    self.synchronizer.stop_synchronization(peer)
                    return
                except blocks.UnknownParentException:
                    if t_block.prevhash == blocks.GENESIS_PREVHASH:
                        log_debug('Rec Incompatible Genesis %r', t_block)
                        if peer:
                            peer.send_Disconnect(reason='Wrong genesis block')
                    else:  # should be a single newly mined block
                        assert t_block.prevhash not in self
                        assert t_block.prevhash != blocks.genesis().hash
                        log_debug('%s with unknown parent %s, peer:%r', t_block, t_block.prevhash.encode('hex'), peer)
                        if len(transient_blocks) != 1:
                            # strange situation here.
                            # we receive more than 1 block, so it's not a single newly mined one
                            # sync/network/... failed to add the needed parent at some point
                            # well, this happens whenever we can't validate a block!
                            # we should disconnect!
                            log_warn('%s received, but unknown parent.', len(transient_blocks))
                        if peer:
                            # request chain for newest known hash
                            self.synchronizer.synchronize_unknown_block(peer, transient_blocks[-1].hash)
                    break
                if block.hash in self:
                    log_debug('Known %r', block)
                else:
                    assert block.has_parent()
                    # assume single block is newly mined block
                    forward = len(transient_blocks) == 1
                    success = self.add_block(block, forward=forward)
                    if success:
                        log_debug('Added %r', block)
                        # print block.hex_serialize()

    def add_block(self, block, forward=False):
        "returns True if block was added sucessfully"
        # make sure we know the parent
        if not block.has_parent() and not block.is_genesis():
            log_debug('Missing parent for block %r', block)
            return False

        if not block.validate_uncles():
            log_debug('Invalid uncles %r', block)
            return False

        # check PoW and forward asap in order to avoid stale blocks
        if not len(block.nonce) == 32:
            log_debug('Nonce not set %r', block)
            return False
        elif not block.check_proof_of_work(block.nonce) and\
                not block.is_genesis():
            log_debug('Invalid nonce %r', block)
            return False
        # Forward block w/ valid PoW asap (if not syncing)
        if forward:
            signals.broadcast_new_block.send(sender=None, block=block)
            log_debug("broadcasting new %r" % block)

        if block.has_parent():
            try:
                #log_debug('verifying: %s', block)
                #log_debug('GETTING ACCOUNT FOR COINBASE:')
                #acct = block.get_acct(block.coinbase)
                #log_debug('GOT ACCOUNT FOR COINBASE: %r', acct)
                processblock.verify(block, block.get_parent())
            except processblock.VerificationFailed as e:
                log_debug('### VERIFICATION FAILED ### %r', e)
                f = os.path.join(utils.data_dir, 'badblock.log')
                open(f, 'w').write(str(block.hex_serialize()))
                print block.hex_serialize()
                return False

        if block.number < self.head.number:
            log_debug("%r is older than head %r", block, self.head)
            # Q: Should we have any limitations on adding blocks?

        self.index.add_block(block)
        self._store_block(block)

        # set to head if this makes the longest chain w/ most work for that number
        #log_debug('Head: %r @%s  New:%r @%d', self.head, self.head.chain_difficulty(), block, block.chain_difficulty())
        if block.chain_difficulty() > self.head.chain_difficulty():
            log_debug('New Head %r', block)
            self._update_head(block)
        elif block.number > self.head.number:
            log_warn('%r has higher blk number than head %r but lower chain_difficulty of %d vs %d',
                        block, self.head, block.chain_difficulty(), self.head.chain_difficulty())
        self.commit()  # batch commits all changes that came with the new block

        return True

    def get_children(self, block):
        return [self.get(c) for c in self.index.get_children(block.hash)]

    def get_uncles(self, block):
        if not block.has_parent():
            return []
        parent = block.get_parent()
        o = []
        i = 0
        while parent.has_parent() and i < 6:
            grandparent = parent.get_parent()
            o.extend([u for u in self.get_children(grandparent) if u != parent])
            parent = grandparent
            i += 1
        return o

    def add_transaction(self, transaction):
        log_debug("add transaction %r" % transaction)
        with self.lock:
            res = self.miner.add_transaction(transaction)
            if res:
                log_debug("broadcasting valid %r" % transaction)
                signals.send_local_transactions.send(
                    sender=None, transactions=[transaction])
            return res

    def get_transactions(self):
        log_debug("get_transactions called")
        return self.miner.get_transactions()

    def get_chain(self, start='', count=NUM_BLOCKS_PER_REQUEST):
        "return 'count' blocks starting from head or start"
        log_debug("get_chain: start:%s count%d", start.encode('hex'), count)
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
        log_debug("get_descendants: %r ", block)
        assert block.hash in self
        block_numbers = range(block.number+1, min(self.head.number, block.number+count))
        return [self.get(self.index.get_block_by_number(n)) for n in block_numbers]



chain_manager = ChainManager()



# receivers ###########

@receiver(signals.get_block_hashes_received)
def handle_get_block_hashes(sender, block_hash, count, peer, **kwargs):
    log_debug("handle_get_block_hashes: %r %d", block_hash.encode('hex'), count)
    max_hashes = min(count, MAX_GET_CHAIN_SEND_HASHES)
    found = []
    if not block_hash in chain_manager:
        log_debug("unknown block: %r", block_hash.encode('hex'))
        peer.send_BlockHashes([])
    last = chain_manager.get(block_hash)
    while len(found) < max_hashes:
        if last.has_parent():
            last = last.get_parent()
            found.append(last.hash)
        else:
            break
    log_debug("sending: found: %d block_hashes", len(found))
    with peer.lock:
        peer.send_BlockHashes(found)


@receiver(signals.get_blocks_received)
def handle_get_blocks(sender, block_hashes, peer, **kwargs):
    log_debug("handle_get_blocks: %d", len(block_hashes))
    found = []
    for bh in block_hashes[:MAX_GET_CHAIN_REQUEST_BLOCKS]:
        if bh in chain_manager:
            found.append(chain_manager.get(bh))
        else:
            log_debug("Unknown block %r requested", bh.encode('hex'))
    log_debug("sending: found: %d blocks", len(found))
    with peer.lock:
        peer.send_Blocks(found)


@receiver(signals.config_ready)
def config_chainmanager(sender, config, **kwargs):
    chain_manager.configure(config)


@receiver(signals.peer_status_received)
def peer_status_received(sender, peer, **kwargs):
    log_debug("%r received status", peer)
    # request chain
    with peer.lock:
        chain_manager.synchronizer.synchronize_status(
            peer, peer.status_head_hash, peer.status_total_difficulty)
    # send transactions
    with peer.lock:
        log_debug("%r sending transactions", peer)
        transactions = chain_manager.get_transactions()
        transactions = [rlp.decode(x.serialize()) for x in transactions]
        peer.send_Transactions(transactions)


@receiver(signals.peer_handshake_success)
def peer_handshake(sender, peer, **kwargs):
    # reply with status if not yet sent
    if peer.has_ethereum_capabilities() and not peer.status_sent:
        log_debug("%r handshake, sending status", peer)
        peer.send_Status(
            chain_manager.head.hash, chain_manager.head.chain_difficulty(), blocks.genesis().hash)
    else:
        log_debug("%r handshake, but peer has no 'eth' capablities", peer)


@receiver(signals.remote_transactions_received)
def remote_transactions_received_handler(sender, transactions, peer, **kwargs):
    "receives rlp.decoded serialized"
    txl = [Transaction.deserialize(rlp.encode(tx)) for tx in transactions]
    log_debug('remote_transactions_received: %r', txl)
    for tx in txl:
        peermanager.txfilter.add(tx, peer)  # FIXME
        chain_manager.add_transaction(tx)


@receiver(signals.local_transaction_received)
def local_transaction_received_handler(sender, transaction, **kwargs):
    "receives transaction object"
    log_debug('local_transaction_received: %r', transaction)
    chain_manager.add_transaction(transaction)


@receiver(signals.new_block_received)
def new_block_received_handler(sender, block, peer, **kwargs):
    log_debug("recv new remote block: %r", block.number)
    chain_manager.receive_chain([block], peer)


@receiver(signals.remote_blocks_received)
def remote_blocks_received_handler(sender, transient_blocks, peer, **kwargs):
    log_debug("recv %d remote blocks: %r", len(transient_blocks), map(lambda x: x.number, transient_blocks))
    if transient_blocks:
        chain_manager.receive_chain(transient_blocks, peer)

@receiver(signals.remote_block_hashes_received)
def remote_block_hashes_received_handler(sender, block_hashes, peer, **kwargs):
    if block_hashes:
        log_debug("recv %d remote block_hashes: %r", len(block_hashes), [block_hashes[0].encode('hex'), '...', block_hashes[-1].encode('hex')])
    else:
        log_debug("recv 0 remore block hashes, signifying genesis block")
    chain_manager.synchronizer.received_block_hashes(peer, block_hashes)

