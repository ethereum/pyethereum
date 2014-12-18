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
from peer import MAX_GET_CHAIN_SEND_HASHES
from peer import MAX_GET_CHAIN_REQUEST_BLOCKS
from pyethereum.slogging import get_logger
log = get_logger('eth.chain')


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
        blk = blocks.get_block(self.blockchain, blockhash)
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

    def configure(self, config, genesis=None, db=None):
        self.config = config
        if not db:
            db_path = utils.db_path(config.get('misc', 'data_dir'))
            log.info('opening chain', path=db_path)
            db = self.blockchain = DB(db_path)
        self.blockchain = db
        self.index = Index(db)
        if genesis:
            self._initialize_blockchain(genesis)
        log.debug('chain @', head=self.head)
        self.genesis = blocks.genesis(db=db)
        log.debug('got genesis', head=self.genesis)
        self.new_miner()
        self.synchronizer = Synchronizer(self)

    def _initialize_blockchain(self, genesis=None):
        log.info('Initializing new chain')
        if not genesis:
            genesis = blocks.genesis(self.blockchain)
            log.info('new genesis', genesis=genesis)
            self.index.add_block(genesis)
        self._store_block(genesis)
        assert genesis == blocks.get_block(self.blockchain, genesis.hash)
        self._update_head(genesis)
        assert genesis.hash in self

    @property
    def head(self):
        if 'HEAD' not in self.blockchain:
            self._initialize_blockchain()
        ptr = self.blockchain.get('HEAD')
        return blocks.get_block(self.blockchain, ptr)

    def _update_head(self, block):
        if not block.is_genesis():
            assert self.head.chain_difficulty() < block.chain_difficulty()
            if block.get_parent() != self.head:
                log.debug('New Head is on a different branch', new=block, old=self.head)
        self.blockchain.put('HEAD', block.hash)
        self.index.update_blocknumbers(self.head)
        self.new_miner()  # reset mining

    def get(self, blockhash):
        assert isinstance(blockhash, str)
        assert len(blockhash) == 32
        return blocks.get_block(self.blockchain, blockhash)

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


    def loop_body(self):
        ts = time.time()
        pct_cpu = self.config.getint('misc', 'mining')
        if pct_cpu > 0:
            self.mine()
            delay = (time.time() - ts) * (100. / pct_cpu - 1)
            assert delay >= 0
            time.sleep(min(delay, 1.))
        else:
            time.sleep(.01)

    def new_miner(self):
        "new miner is initialized if HEAD is updated"
        # prepare uncles
        uncles = set(self.get_uncles(self.head))
        ineligible = set()  # hashes
        blk = self.head
        for i in range(8):
            for u in blk.uncles:  # assuming uncle headers
                u = utils.sha3(rlp.encode(u))
                if u in self:
                    uncles.discard(self.get(u))
            if blk.has_parent():
                blk = blk.get_parent()

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
                    log.debug("newly mined block is invalid!?", block=block)
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
                log.debug('Checking PoW', block=t_block)
                if not blocks.check_header_pow(t_block.header_args):
                    log.debug('Invalid PoW', block=t_block)
                    continue
                log.debug('Deserializing', block=t_block)
                try:
                    block = blocks.Block.deserialize(self.blockchain, t_block.rlpdata)
                except processblock.InvalidTransaction as e:
                    # FIXME there might be another exception in
                    # blocks.deserializeChild when replaying transactions
                    # if this fails, we need to rewind state
                    log.debug('invalid transaction', block=t_block, error=e)
                    # stop current syncing of this chain and skip the child blocks
                    self.synchronizer.stop_synchronization(peer)
                    return
                except blocks.UnknownParentException:
                    if t_block.prevhash == blocks.GENESIS_PREVHASH:
                        log.debug('Rec Incompatible Genesis', block=t_block)
                        if peer:
                            peer.send_Disconnect(reason='Wrong genesis block')
                    else:  # should be a single newly mined block
                        assert t_block.prevhash not in self
                        assert t_block.prevhash != self.genesis.hash
                        log.debug('unknown parent', block=t_block,
                                  parent=t_block.prevhash.encode('hex'), peer=peer)
                        if len(transient_blocks) != 1:
                            # strange situation here.
                            # we receive more than 1 block, so it's not a single newly mined one
                            # sync/network/... failed to add the needed parent at some point
                            # well, this happens whenever we can't validate a block!
                            # we should disconnect!
                            log.warn(
                                'blocks received, but unknown parent.', num=len(transient_blocks))
                        if peer:
                            # request chain for newest known hash
                            self.synchronizer.synchronize_unknown_block(
                                peer, transient_blocks[-1].hash)
                    break
                if block.hash in self:
                    log.debug('known', block=block)
                else:
                    assert block.has_parent()
                    # assume single block is newly mined block
                    forward = len(transient_blocks) == 1
                    success = self.add_block(block, forward=forward)
                    if success:
                        log.debug('added', block=block)

    def add_block(self, block, forward=False):
        "returns True if block was added sucessfully"
        _log = log.bind(block=block)
        # make sure we know the parent
        if not block.has_parent() and not block.is_genesis():
            _log.debug('missing parent')
            return False

        if not block.validate_uncles():
            _log.debug('invalid uncles')
            return False

        # check PoW and forward asap in order to avoid stale blocks
        if not len(block.nonce) == 32:
            _log.debug('nonce not set')
            return False
        elif not block.check_proof_of_work(block.nonce) and\
                not block.is_genesis():
            _log.debug('invalid nonce')
            return False
        # Forward block w/ valid PoW asap (if not syncing)
        # FIXME: filter peer by wich block was received
        if forward:
            _log.debug("broadcasting new")
            signals.broadcast_new_block.send(sender=None, block=block)

        if block.has_parent():
            try:
                processblock.verify(block, block.get_parent())
            except processblock.VerificationFailed as e:
                _log.critical('VERIFICATION FAILED', error=e)
                f = os.path.join(utils.data_dir, 'badblock.log')
                open(f, 'w').write(str(block.hex_serialize()))
                return False

        if block.number < self.head.number:
            _log.debug("older than head", head=self.head)
            # Q: Should we have any limitations on adding blocks?

        self.index.add_block(block)
        self._store_block(block)

        # set to head if this makes the longest chain w/ most work for that number
        if block.chain_difficulty() > self.head.chain_difficulty():
            _log.debug('new head')
            self._update_head(block)
        elif block.number > self.head.number:
            _log.warn('has higher blk number than head but lower chain_difficulty',
                      head=self.head, block_difficulty=block.chain_difficulty(),
                      head_difficulty=self.head.chain_difficulty())
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
        _log = log.bind(tx=transaction)
        _log.debug("add transaction")
        with self.lock:
            res = self.miner.add_transaction(transaction)
            if res:
                _log.debug("broadcasting valid")
                signals.send_local_transactions.send(
                    sender=None, transactions=[transaction])
            return res

    def get_transactions(self):
        log.debug("get_transactions called")
        return self.miner.get_transactions()

    def get_chain(self, start='', count=NUM_BLOCKS_PER_REQUEST):
        "return 'count' blocks starting from head or start"
        log.debug("get_chain", start=start.encode('hex'), count=count)
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
        log.debug("get_descendants", block=block)
        assert block.hash in self
        block_numbers = range(block.number + 1, min(self.head.number, block.number + count))
        return [self.get(self.index.get_block_by_number(n)) for n in block_numbers]


chain_manager = ChainManager()


# receivers ###########
log_api = get_logger('chain.api')


@receiver(signals.get_block_hashes_received)
def handle_get_block_hashes(sender, block_hash, count, peer, **kwargs):
    _log_api = log_api.bind(block_hash=block_hash.encode('hex'))
    _log_api.debug("handle_get_block_hashes", count=count)
    max_hashes = min(count, MAX_GET_CHAIN_SEND_HASHES)
    found = []
    if not block_hash in chain_manager:
        log_api.debug("unknown block")
        peer.send_BlockHashes([])
    last = chain_manager.get(block_hash)
    while len(found) < max_hashes:
        if last.has_parent():
            last = last.get_parent()
            found.append(last.hash)
        else:
            break
    _log_api.debug("sending: found block_hashes", count=len(found))
    with peer.lock:
        peer.send_BlockHashes(found)


@receiver(signals.get_blocks_received)
def handle_get_blocks(sender, block_hashes, peer, **kwargs):
    log_api.debug("handle_get_blocks", count=len(block_hashes))
    found = []
    for bh in block_hashes[:MAX_GET_CHAIN_REQUEST_BLOCKS]:
        if bh in chain_manager:
            found.append(chain_manager.get(bh))
        else:
            log.debug("unknown block requested", block_hash=bh.encode('hex'))
    log_api.debug("found", count=len(found))
    with peer.lock:
        peer.send_Blocks(found)


@receiver(signals.config_ready)
def config_chainmanager(sender, config, **kwargs):
    chain_manager.configure(config)


@receiver(signals.peer_status_received)
def peer_status_received(sender, genesis_hash, peer, **kwargs):
    log_api.debug("received status", peer=peer, genesis_hash=genesis_hash.encode('hex'))
    # check genesis
    if genesis_hash != chain_manager.genesis.hash:
        return peer.send_Disconnect(reason='Wrong genesis block')

    # request chain
    with peer.lock:
        chain_manager.synchronizer.synchronize_status(
            peer, peer.status_head_hash, peer.status_total_difficulty)
    # send transactions
    with peer.lock:
        log_api.debug("sending transactions", peer=peer)
        transactions = chain_manager.get_transactions()
        transactions = [rlp.decode(x.serialize()) for x in transactions]
        peer.send_Transactions(transactions)


@receiver(signals.peer_handshake_success)
def peer_handshake(sender, peer, **kwargs):
    # reply with status if not yet sent
    if peer.has_ethereum_capabilities() and not peer.status_sent:
        log_api.debug("handshake, sending status", peer=peer)
        peer.send_Status(
            chain_manager.head.hash, chain_manager.head.chain_difficulty(), chain_manager.genesis.hash)
    else:
        log_api.debug("handshake, but peer has no 'eth' capablities", peer=peer)


@receiver(signals.remote_transactions_received)
def remote_transactions_received_handler(sender, transactions, peer, **kwargs):
    "receives rlp.decoded serialized"
    txl = [Transaction.deserialize(rlp.encode(tx)) for tx in transactions]
    log_api.debug('remote_transactions_received', num=len(txl))
    for tx in txl:
        peermanager.txfilter.add(tx, peer)  # FIXME
        chain_manager.add_transaction(tx)


@receiver(signals.local_transaction_received)
def local_transaction_received_handler(sender, transaction, **kwargs):
    "receives transaction object"
    log_api.debug('local_transaction_received', tx=transaction)
    chain_manager.add_transaction(transaction)


@receiver(signals.new_block_received)
def new_block_received_handler(sender, block, peer, **kwargs):
    log_api.debug("recv new remote block", block=block)
    chain_manager.receive_chain([block], peer)


@receiver(signals.remote_blocks_received)
def remote_blocks_received_handler(sender, transient_blocks, peer, **kwargs):
    log_api.debug("recv remote blocks", count=len(transient_blocks),
                  highest_number=max(map(lambda x: x.number, transient_blocks)))
    if transient_blocks:
        chain_manager.receive_chain(transient_blocks, peer)


@receiver(signals.remote_block_hashes_received)
def remote_block_hashes_received_handler(sender, block_hashes, peer, **kwargs):
    if block_hashes:
        log_api.debug("recv remote block_hashes", count=len(block_hashes),
                      first=block_hashes[0].encode('hex'), last=block_hashes[-1].encode('hex'))
    else:
        log_api.debug("recv 0 remore block hashes, signifying genesis block")
    chain_manager.synchronizer.received_block_hashes(peer, block_hashes)
