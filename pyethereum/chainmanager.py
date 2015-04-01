import time
from operator import attrgetter
from pyethereum.dispatch import receiver
from pyethereum.stoppable import StoppableLoopThread
from pyethereum import signals
from pyethereum.db import DB, EphemDB
from pyethereum import utils
import rlp
from rlp.utils import decode_hex, encode_hex
from pyethereum import blocks
from pyethereum import processblock
from pyethereum import peermanager
from pyethereum.transactions import Transaction
from pyethereum.miner import Miner
from pyethereum.synchronizer import Synchronizer
from pyethereum.peer import MAX_GET_CHAIN_SEND_HASHES
from pyethereum.peer import MAX_GET_CHAIN_REQUEST_BLOCKS
from pyethereum.slogging import get_logger
from pyethereum.chain import Chain
log = get_logger('eth.chainmgr')


rlp_hash_hex = lambda data: encode_hex(utils.sha3(rlp.encode(data)))

NUM_BLOCKS_PER_REQUEST = 256  # MAX_GET_CHAIN_REQUEST_BLOCKS


class ChainManager(StoppableLoopThread):

    """
    Manages the chain and requests to it.
    """

    # initialized after configure:
    chain = None
    genesis = None
    miner = None
    synchronizer = None
    config = None

    def __init__(self):
        super(ChainManager, self).__init__()

    def configure(self, config, genesis=None, db=None):
        self.config = config
        if not db:
            db_path = utils.db_path(config.get('misc', 'data_dir'))
            log.info('opening chain', db_path=db_path)
            db = DB(db_path)
        coinbase = decode_hex(config.get('wallet', 'coinbase'))
        self.chain = Chain(db, genesis, new_head_cb=self._on_new_head, coinbase=coinbase)
        self.synchronizer = Synchronizer(self)

    def _on_new_head(self, block):
        """Called when a new block is added to the chain.
        
        This will reset the mining and initiate firther broadcasting of the
        new head.

        :param block: the new chain head
        """
        self.miner = Miner(self.chain.head_candidate) # reset mining
        # if we are not syncing, forward all blocks
        if not self.synchronizer.synchronization_tasks:
            log.debug("broadcasting new head", block=block)
            signals.broadcast_new_block.send(sender=None, block=block)

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

    def mine(self):
        with self.lock:
            block = self.miner.mine()
            if block:
                # create new block
                if not self.chain.add_block(block):
                    log.debug("newly mined block is invalid!?", block_hash=block)

    def receive_chain(self, transient_blocks, peer=None):
        with self.lock:
            _db = EphemDB()
            # assuming to receive chain order w/ oldest block first
            transient_blocks.sort(key=attrgetter('number'))
            assert transient_blocks[0].number <= transient_blocks[-1].number

            # notify syncer
            self.synchronizer.received_blocks(peer, transient_blocks)

            for t_block in transient_blocks:  # oldest to newest
                log.debug('Checking PoW', block_hash=t_block.hash)
                if not t_block.header.check_pow(_db):
                    log.debug('Invalid PoW', block_hash=t_block.hash)
                    continue
                log.debug('Deserializing', block_hash=t_block.hash)
                try:
                    block = blocks.Block(t_block.header, t_block.transaction_list, t_block.uncles,
                                         db=self.chain.db)
                except processblock.InvalidTransaction as e:
                    # FIXME there might be another exception in
                    # blocks.deserializeChild when replaying transactions
                    # if this fails, we need to rewind state
                    log.debug('invalid transaction', block_hash=t_block, error=e)
                    # stop current syncing of this chain and skip the child blocks
                    self.synchronizer.stop_synchronization(peer)
                    return
                except blocks.UnknownParentException:
                    if t_block.prevhash == blocks.GENESIS_PREVHASH:
                        log.debug('Rec Incompatible Genesis', block_hash=t_block)
                        if peer:
                            peer.send_Disconnect(reason='Wrong genesis block')
                    else:  # should be a single newly mined block
                        assert t_block.prevhash not in self
                        assert t_block.prevhash != self.chain.genesis.hash
                        log.debug('unknown parent', block_hash=t_block,
                                  parent_hash=encode_hex(t_block.prevhash), remote_id=peer)
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
                if block.hash in self.chain:
                    log.debug('known', block_hash=block)
                else:
                    assert block.has_parent()
                    # assume single block is newly mined block
                    success = self.chain.add_block(block)
                    if success:
                        log.debug('added', block_hash=block)


chain_manager = ChainManager()


# receivers ###########
log_api = get_logger('chain.api')


@receiver(signals.get_block_hashes_received)
def handle_get_block_hashes(sender, block_hash, count, peer, **kwargs):
    _log_api = log_api.bind(block_hash=encode_hex(block_hash))
    _log_api.debug("handle_get_block_hashes", count=count)
    max_hashes = min(count, MAX_GET_CHAIN_SEND_HASHES)
    found = []
    if not block_hash in chain_manager.chain:
        log_api.debug("unknown block")
        peer.send_BlockHashes([])
    last = chain_manager.chain.get(block_hash)
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
        if bh in chain_manager.chain:
            found.append(chain_manager.chain.get(bh))
        else:
            log.debug("unknown block requested", block_hash=encode_hex(bh))
    log_api.debug("found", count=len(found))
    with peer.lock:
        peer.send_Blocks(found)


@receiver(signals.config_ready)
def config_chainmanager(sender, config, **kwargs):
    chain_manager.configure(config)


@receiver(signals.peer_status_received)
def peer_status_received(sender, genesis_hash, peer, **kwargs):
    log_api.debug("received status", remote_id=peer, genesis_hash=encode_hex(genesis_hash))
    # check genesis
    if genesis_hash != chain_manager.chain.genesis.hash:
        return peer.send_Disconnect(reason='wrong genesis block')

    # request chain
    with peer.lock:
        chain_manager.synchronizer.synchronize_status(
            peer, peer.status_head_hash, peer.status_total_difficulty)
    # send transactions
    with peer.lock:
        log_api.debug("sending transactions", remote_id=peer)
        transactions = chain_manager.get_transactions()
        transactions = [rlp.decode(x.serialize()) for x in transactions]
        peer.send_Transactions(transactions)


@receiver(signals.peer_handshake_success)
def peer_handshake(sender, peer, **kwargs):
    # reply with status if not yet sent
    if peer.has_ethereum_capabilities() and not peer.status_sent:
        log_api.debug("handshake, sending status", remote_id=peer)
        peer.send_Status(chain_manager.chainhead.hash, chain_manager.chain.head.chain_difficulty(),
                         chain_manager.chain.genesis.hash)
    else:
        log_api.debug("handshake, but peer has no 'eth' capablities", remote_id=peer)


@receiver(signals.remote_transactions_received)
def remote_transactions_received_handler(sender, transactions, peer, **kwargs):
    "receives rlp.decoded serialized"
    txl = [Transaction.deserialize(rlp.encode(tx)) for tx in transactions]
    log_api.debug('remote_transactions_received', count=len(txl), remote_id=peer)
    for tx in txl:
        peermanager.txfilter.add(tx, peer)  # FIXME
        chain_manager.add_transaction(tx)


@receiver(signals.local_transaction_received)
def local_transaction_received_handler(sender, transaction, **kwargs):
    "receives transaction object"
    log_api.debug('local_transaction_received', tx_hash=transaction)
    chain_manager.add_transaction(transaction)


@receiver(signals.new_block_received)
def new_block_received_handler(sender, block, peer, **kwargs):
    log_api.debug("recv new remote block", block_hash=block, remote_id=peer)
    chain_manager.receive_chain([block], peer)


@receiver(signals.remote_blocks_received)
def remote_blocks_received_handler(sender, transient_blocks, peer, **kwargs):
    log_api.debug("recv remote blocks", count=len(transient_blocks), remote_id=peer,
                  highest_number=max(x.number for x in transient_blocks))
    if transient_blocks:
        chain_manager.receive_chain(transient_blocks, peer)


@receiver(signals.remote_block_hashes_received)
def remote_block_hashes_received_handler(sender, block_hashes, peer, **kwargs):
    if block_hashes:
        log_api.debug("recv remote block_hashes", count=len(block_hashes), remote_id=peer,
                      first=encode_hex(block_hashes[0]), last=encode_hex(block_hashes[-1]))
    else:
        log_api.debug("recv 0 remore block hashes, signifying genesis block")
    chain_manager.synchronizer.received_block_hashes(peer, block_hashes)
