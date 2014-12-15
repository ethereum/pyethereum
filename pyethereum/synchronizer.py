
from operator import attrgetter
import sys
import blocks
from pyethereum.slogging import get_logger
log = get_logger('eth.sync')


class HashChainTask(object):

    """
    - get hashes chain until we see a known block hash
    """

    NUM_HASHES_PER_REQUEST = 2000

    def __init__(self, chain_manager, peer, block_hash):
        self.chain_manager = chain_manager
        self.peer = peer
        self.hash_chain = []  # [youngest, ..., oldest]
        self.request(block_hash)

    def request(self, block_hash):
        log.debug('requesting block_hashes', peer=self.peer, start=block_hash.encode('hex'))
        self.peer.send_GetBlockHashes(block_hash, self.NUM_HASHES_PER_REQUEST)

    def received_block_hashes(self, block_hashes):
        log.debug('HashChainTask.received_block_hashes', num=len(block_hashes))
        if block_hashes and self.chain_manager.genesis.hash == block_hashes[-1]:
            log.debug('has different chain starting from genesis', peer=self.peer)
        for bh in block_hashes:
            if bh in self.chain_manager or bh == self.chain_manager.genesis.hash:
                log.debug('matching block hash found', peer=self.peer,
                          hash=bh.encode('hex'), num_to_fetch=len(self.hash_chain))
                return list(reversed(self.hash_chain))
            self.hash_chain.append(bh)
        if len(block_hashes) == 0:
            return list(reversed(self.hash_chain))
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
        self.hash_chain = []  # [oldest to youngest]
        log.debug('syncing', peer=self.peer, hash=block_hash.encode('hex'))
        self.hash_chain_task = HashChainTask(self.chain_manager, self.peer, block_hash)

    def received_block_hashes(self, block_hashes):
        res = self.hash_chain_task.received_block_hashes(block_hashes)
        if res:
            self.hash_chain = res
            log.debug('receieved hash chain', peer=self.peer, num=len(self.hash_chain))
            self.request_blocks()

    def received_blocks(self, transient_blocks):
        log.debug('blocks received', peer=self.peer, num=len(
            transient_blocks), missing=len(self.hash_chain))
        for tb in transient_blocks:
            if len(self.hash_chain) and self.hash_chain[0] == tb.hash:
                self.hash_chain.pop(0)
            else:
                log.debug('received unexpected block', peer=self.peer, block=tb)
                return False
        if self.hash_chain:
            # still blocks to fetch
            log.debug('still missing blocks', peer=self.peer, num=len(self.hash_chain))
            self.request_blocks()
        else:  # done
            return True

    def request_blocks(self):
        log.debug('requesting missing blocks', peer=self.peer,
                  requested=self.NUM_BLOCKS_PER_REQUEST, missing=len(self.hash_chain))
        self.peer.send_GetBlocks(self.hash_chain[:self.NUM_BLOCKS_PER_REQUEST])


class Synchronizer(object):

    """"
    Cases:
        on "recv_Status": received unknown head_hash w/ sufficient difficulty
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
        self.synchronization_tasks = {}  # peer > syncer # syncer.unknown_hash as marker for task

    def stop_synchronization(self, peer):
        log.debug('sync stopped', peer=peer)
        if peer in self.synchronization_tasks:
            del self.synchronization_tasks[peer]

    def synchronize_unknown_block(self, peer, block_hash, force=False):
        "Case: block with unknown parent. Fetches unknown ancestors and this block"
        log.debug('sync unknown', peer=peer, block=block_hash.encode('hex'))
        if block_hash == self.chain_manager.genesis.hash or block_hash in self.chain_manager:
            log.debug('known_hash, skipping', peer=peer, hash=block_hash.encode('hex'))
            return

        if peer and (not peer in self.synchronization_tasks) or force:
            log.debug('new sync task', peer=peer)
            self.synchronization_tasks[peer] = SynchronizationTask(
                self.chain_manager, peer, block_hash)
        else:
            log.debug('existing synctask', peer=peer)

    def synchronize_status(self, peer, block_hash, total_difficulty):
        "Case: unknown head with sufficient difficulty"
        log.debug('sync status', peer=peer,  hash=block_hash.encode(
            'hex'), total_difficulty=total_difficulty)

        # guesstimate the max difficulty difference possible for a sucessfully competing chain
        # worst case if skip it: we are on a stale chain until the other catched up
        # assume difficulty is constant
        num_blocks_behind = 7
        avg_uncles_per_block = 4
        max_diff = self.chain_manager.head.difficulty * \
            num_blocks_behind * (1 + avg_uncles_per_block)
        if total_difficulty + max_diff > self.chain_manager.head.difficulty:
            log.debug('sufficient difficulty, syncing', peer=peer)
            self.synchronize_unknown_block(peer, block_hash)
        else:
            log.debug('insufficient difficulty, not syncing', peer=peer)

    def received_block_hashes(self, peer, block_hashes):
        if peer in self.synchronization_tasks:
            log.debug("Synchronizer.received_block_hashes", peer=peer, num=len(block_hashes))
            self.synchronization_tasks[peer].received_block_hashes(block_hashes)

    def received_blocks(self, peer, transient_blocks):
        if peer in self.synchronization_tasks:
            res = self.synchronization_tasks[peer].received_blocks(transient_blocks)
            if res is True:
                log.debug("Synchronizer.received_blocks: chain synced", peer=peer)
                del self.synchronization_tasks[peer]
