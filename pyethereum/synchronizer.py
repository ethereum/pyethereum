
from operator import attrgetter
import logging
import blocks
logger = logging.getLogger(__name__)

class HashChainTask(object):
    """
    - get hashes chain until we see a known block hash
    """

    NUM_HASHES_PER_REQUEST = 2000
    GENESIS_HASH = blocks.genesis().hash

    def __init__(self, chain_manager, peer, block_hash):
        self.chain_manager = chain_manager
        self.peer = peer
        self.hash_chain = [] # [youngest, ..., oldest]
        self.request(block_hash)

    def request(self, block_hash):
        logger.debug('%r requesting block_hashes starting from %r', self.peer, block_hash.encode('hex'))
        self.peer.send_GetBlockHashes(block_hash, self.NUM_HASHES_PER_REQUEST)

    def received_block_hashes(self, block_hashes):
        logger.warn('HashChainTask.received_block_hashes %d', len(block_hashes))
        if self.GENESIS_HASH in block_hashes:
            logger.warn('%r has different chain starting from genesis', self.peer)
        for bh in block_hashes:
            if bh in self.chain_manager or bh == self.GENESIS_HASH:
                logger.debug('%r matching block hash found %r', self.peer, bh.encode('hex'))
                return list(reversed(self.hash_chain))
            self.hash_chain.append(bh)
            #logger.debug('hash_chain.append(%r) %d', bh.encode('hex'), len(self.hash_chain))
        self.request(bh)


class SynchronizationTask(object):
    """
    Created if we receive a unknown block w/o known parent. Possibly from a different branch.

    - get hashes chain until we see a known block hash
    - request missing blocks

    - once synced
        - rerequest blocks that lacked a reference before syncing
    """
    NUM_BLOCKS_PER_REQUEST = 200

    def __init__(self, chain_manager, peer, block_hash):
        self.chain_manager = chain_manager
        self.peer = peer
        self.hash_chain = [] # [oldest to youngest]
        logger.debug('%r syncing %r', self.peer, block_hash.encode('hex'))
        self.hash_chain_task = HashChainTask(self.chain_manager, self.peer, block_hash)

    def received_block_hashes(self, block_hashes):
        res = self.hash_chain_task.received_block_hashes(block_hashes)
        if res:
            self.hash_chain = res
            logger.debug('%r hash chain with %d hashes for missing blocks', self.peer, len(self.hash_chain))
            self.request_blocks()

    def received_blocks(self, transient_blocks):
        logger.debug('%r received %d of %d missing blocks', self.peer, len(transient_blocks), len(self.hash_chain))
        for tb in transient_blocks:
            if len(self.hash_chain) and self.hash_chain[0] == tb.hash:
                self.hash_chain.pop(0)
            else:
                logger.debug('%r received unexpected block %r', self.peer, tb)
                return False
        if self.hash_chain:
            # still blocks to fetch
            logger.debug('%r still missing %d blocks', self.peer, len(self.hash_chain))
            self.request_blocks()
        else: # done
            return True

    def request_blocks(self):
        logger.debug('%r requesting %d of %d missing blocks', self.peer, self.NUM_BLOCKS_PER_REQUEST, len(self.hash_chain))
        self.peer.send_GetBlocks(self.hash_chain[:self.NUM_BLOCKS_PER_REQUEST])


class Synchronizer(object):
    """"
    Cases:
        on "recv_Hello": received unknown head_hash w/ sufficient difficulty
        on "recv_Blocks": received block w/o parent (new block mined, competing chain discovered)

    Naive Strategy:
        assert we see a block for which we have no parent
        assume that the sending peer knows the parent
        if we have not yet syncer for this unknown block:
            create new syncer
            sync direction genesis until we see known block_hash
            sync also (re)requests the block we missed, so it can be added on top of the synced chain
        else
            do nothing
            syncing (if finished) will be started with the next broadcasted block w/ missing parent
    """

    def __init__(self, chain_manager):
        self.chain_manager = chain_manager
        self.synchronization_tasks = {} # peer > syncer # syncer.unknown_hash as marker for task

    def stop_synchronization(self, peer):
        logger.debug('%r sync stopped', peer)
        if peer in self.synchronization_tasks:
            del self.synchronization_tasks[peer]

    def synchronize_unknown_block(self, peer, block_hash, force=False):
        "Case: block with unknown parent. Fetches unknown ancestors and this block"
        logger.debug('%r sync %r', peer, block_hash.encode('hex'))
        assert block_hash not in self.chain_manager
        if peer and (not peer in self.synchronization_tasks) or force:
            logger.debug('%r new sync task', peer)
            self.synchronization_tasks[peer] = SynchronizationTask(self.chain_manager, peer, block_hash)
        else:
            logger.debug('%r already has a synctask, sorry', peer)

    def synchronize_hello(self, peer, block_hash, total_difficulty):
        "Case: unknown head with sufficient difficulty"
        logger.debug('%r Hello  with %r %d', peer,  block_hash.encode('hex'), total_difficulty)
        assert block_hash not in self.chain_manager
        # guesstimate the max difficulty difference possible for a sucessfully competing chain
        # worst case if skip it: we are on a stale chain until the other catched up
        # assume difficulty is constant
        num_blocks_behind = 7
        avg_uncles_per_block = 4
        max_diff = self.chain_manager.head.difficulty * num_blocks_behind * (1 + avg_uncles_per_block)
        if total_difficulty + max_diff > self.chain_manager.head.difficulty:
            logger.debug('%r sufficient difficulty, syncing', peer)
            self.synchronize_unknown_block(peer, block_hash)
        else:
            logger.debug('%r insufficient difficulty, not syncing', peer)

    def received_block_hashes(self, peer, block_hashes):
        if peer in self.synchronization_tasks:
            logger.debug("Synchronizer.received_block_hashes %d for: %r", len(block_hashes), peer)
            self.synchronization_tasks[peer].received_block_hashes(block_hashes)

    def received_blocks(self, peer, transient_blocks):
        if peer in self.synchronization_tasks:
            res = self.synchronization_tasks[peer].received_blocks(transient_blocks)
            if res is True:
                logger.debug("Synchronizer.received_blocks: chain w %r synced", peer)
                del self.synchronization_tasks[peer]
