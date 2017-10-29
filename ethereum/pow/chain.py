from __future__ import print_function
from builtins import range
import json
import random
import time
import itertools
from ethereum import utils
from ethereum.utils import parse_as_bin, big_endian_to_int, is_string
from ethereum.meta import apply_block
from ethereum.common import update_block_env_variables
from ethereum.messages import apply_transaction
import rlp
from rlp.utils import encode_hex
from ethereum.exceptions import InvalidNonce, InsufficientStartGas, UnsignedTransaction, \
    BlockGasLimitReached, InsufficientBalance, InvalidTransaction, VerificationFailed
from ethereum.slogging import get_logger, configure_logging
from ethereum.config import Env
from ethereum.state import State, dict_to_prev_header
from ethereum.block import Block, BlockHeader, BLANK_UNCLES_HASH, FakeHeader
from ethereum.pow.consensus import initialize
from ethereum.genesis_helpers import mk_basic_state, state_from_genesis_declaration, \
    initialize_genesis_keys
from ethereum.db import RefcountDB


log = get_logger('eth.chain')
config_string = ':info'  #,eth.chain:debug'
#config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
configure_logging(config_string=config_string)


class Chain(object):

    def __init__(self, genesis=None, env=None,
                 new_head_cb=None, reset_genesis=False, localtime=None, max_history=1000, **kwargs):
        self.env = env or Env()
        # Initialize the state
        if b'head_hash' in self.db:  # new head tag
            self.state = self.mk_poststate_of_blockhash(
                self.db.get('head_hash'))
            self.state.executing_on_head = True
            print('Initializing chain from saved head, #%d (%s)' %
                  (self.state.prev_headers[0].number, encode_hex(self.state.prev_headers[0].hash)))
        elif genesis is None:
            raise Exception("Need genesis decl!")
        elif isinstance(genesis, State):
            assert env is None
            self.state = genesis
            self.env = self.state.env
            print('Initializing chain from provided state')
            reset_genesis = True
        elif "extraData" in genesis:
            self.state = state_from_genesis_declaration(
                genesis, self.env, executing_on_head=True)
            reset_genesis = True
            print('Initializing chain from provided genesis declaration')
        elif "prev_headers" in genesis:
            self.state = State.from_snapshot(
                genesis, self.env, executing_on_head=True)
            reset_genesis = True
            print('Initializing chain from provided state snapshot, %d (%s)' %
                  (self.state.block_number, encode_hex(self.state.prev_headers[0].hash[:8])))
        elif isinstance(genesis, dict):
            print('Initializing chain from new state based on alloc')
            self.state = mk_basic_state(genesis, {
                "number": kwargs.get('number', 0),
                "gas_limit": kwargs.get('gas_limit', self.env.config['BLOCK_GAS_LIMIT']),
                "gas_used": kwargs.get('gas_used', 0),
                "timestamp": kwargs.get('timestamp', 1467446877),
                "difficulty": kwargs.get('difficulty', 2**25),
                "hash": kwargs.get('prevhash', '00' * 32),
                "uncles_hash": kwargs.get('uncles_hash', '0x' + encode_hex(BLANK_UNCLES_HASH))
            }, self.env)
            reset_genesis = True

        assert self.env.db == self.state.db

        initialize(self.state)
        self.new_head_cb = new_head_cb
        
        if self.state.block_number == 0:
            assert self.state.block_number == self.state.prev_headers[0].number
        else:
            assert self.state.block_number - 1 == self.state.prev_headers[0].number

        if reset_genesis:
            if isinstance(self.state.prev_headers[0], FakeHeader):
                header = self.state.prev_headers[0].to_block_header()
            else:
                header = self.state.prev_headers[0]
            self.genesis = Block(header)
            self.state.prev_headers[0] = header
            initialize_genesis_keys(self.state, self.genesis)
        else:
            self.genesis = self.get_block_by_number(0)

        self.head_hash = self.state.prev_headers[0].hash
        self.time_queue = []
        self.parent_queue = {}
        self.localtime = time.time() if localtime is None else localtime
        self.max_history = max_history

    # Head (tip) of the chain
    @property
    def head(self):
        try:
            block_rlp = self.db.get(self.head_hash)
            if block_rlp == b'GENESIS':
                return self.genesis
            else:
                return rlp.decode(block_rlp, Block)
        except Exception as e:
            log.error(e)
            return None

    # Returns the post-state of the block
    def mk_poststate_of_blockhash(self, blockhash):
        if blockhash not in self.db:
            raise Exception("Block hash %s not found" % encode_hex(blockhash))

        block_rlp = self.db.get(blockhash)
        if block_rlp == b'GENESIS':
            return State.from_snapshot(json.loads(
                self.db.get(b'GENESIS_STATE')), self.env)
        block = rlp.decode(block_rlp, Block)

        state = State(env=self.env)
        state.trie.root_hash = block.header.state_root
        update_block_env_variables(state, block)
        state.gas_used = block.header.gas_used
        state.txindex = len(block.transactions)
        state.recent_uncles = {}
        state.prev_headers = []
        b = block
        header_depth = state.config['PREV_HEADER_DEPTH']
        for i in range(header_depth + 1):
            state.prev_headers.append(b.header)
            if i < 6:
                state.recent_uncles[state.block_number - i] = []
                for u in b.uncles:
                    state.recent_uncles[state.block_number - i].append(u.hash)
            try:
                b = rlp.decode(state.db.get(b.header.prevhash), Block)
            except BaseException:
                break
        if i < header_depth:
            if state.db.get(b.header.prevhash) == b'GENESIS':
                jsondata = json.loads(state.db.get(b'GENESIS_STATE'))
                for h in jsondata["prev_headers"][:header_depth - i]:
                    state.prev_headers.append(dict_to_prev_header(h))
                for blknum, uncles in jsondata["recent_uncles"].items():
                    if int(blknum) >= state.block_number - \
                            int(state.config['MAX_UNCLE_DEPTH']):
                        state.recent_uncles[blknum] = [
                            parse_as_bin(u) for u in uncles]
            else:
                raise Exception("Dangling prevhash")
        assert len(state.journal) == 0, state.journal
        return state

    # Gets the parent block of a given block
    def get_parent(self, block):
        if block.header.number == int(self.db.get(b'GENESIS_NUMBER')):
            return None
        return self.get_block(block.header.prevhash)

    # Gets the block with a given blockhash
    def get_block(self, blockhash):
        try:
            block_rlp = self.db.get(blockhash)
            if block_rlp == b'GENESIS':
                if not hasattr(self, 'genesis'):
                    self.genesis = rlp.decode(
                        self.db.get(b'GENESIS_RLP'), sedes=Block)
                return self.genesis
            else:
                return rlp.decode(block_rlp, Block)
        except Exception as e:
            log.debug("Failed to get block", hash=blockhash, error=e)
            return None

    # Add a record allowing you to later look up the provided block's
    # parent hash and see that it is one of its children
    def add_child(self, child):
        try:
            existing = self.db.get(b'child:' + child.header.prevhash)
        except BaseException:
            existing = b''
        existing_hashes = []
        for i in range(0, len(existing), 32):
            existing_hashes.append(existing[i: i + 32])
        if child.header.hash not in existing_hashes:
            self.db.put(
                b'child:' + child.header.prevhash,
                existing + child.header.hash)

    # Gets the hash of the block with the given block number
    def get_blockhash_by_number(self, number):
        try:
            return self.db.get(b'block:%d' % number)
        except BaseException:
            return None

    # Gets the block with the given block number
    def get_block_by_number(self, number):
        return self.get_block(self.get_blockhash_by_number(number))

    # Get the hashes of all known children of a given block
    def get_child_hashes(self, blockhash):
        o = []
        try:
            data = self.db.get(b'child:' + blockhash)
            for i in range(0, len(data), 32):
                o.append(data[i:i + 32])
            return o
        except BaseException:
            return []

    # Get the children of a block
    def get_children(self, block):
        if isinstance(block, Block):
            block = block.header.hash
        if isinstance(block, BlockHeader):
            block = block.hash
        return [self.get_block(h) for h in self.get_child_hashes(block)]

    # Get the score (AKA total difficulty in PoW) of a given block
    def get_score(self, block):
        if not block:
            return 0
        key = b'score:' + block.header.hash

        fills = []
        while key not in self.db:
            fills.insert(0, (block.header.hash, block.difficulty))
            key = b'score:' + block.header.prevhash
            block = self.get_parent(block)
        score = int(self.db.get(key))
        for h, d in fills:
            key = b'score:' + h
            score = score + d + random.randrange(d // 10**6 + 1)
            self.db.put(key, str(score))

        return score

    # This function should be called periodically so as to
    # process blocks that were received but laid aside because
    # they were received too early
    def process_time_queue(self, new_time=None):
        self.localtime = time.time() if new_time is None else new_time
        i = 0
        while i < len(
                self.time_queue) and self.time_queue[i].timestamp <= self.localtime:
            log.info('Adding scheduled block')
            pre_len = len(self.time_queue)
            self.add_block(self.time_queue.pop(i))
            if len(self.time_queue) == pre_len:
                i += 1

    # Call upon receiving a block
    def add_block(self, block):
        now = self.localtime
        # Are we receiving the block too early?
        if block.header.timestamp > now:
            i = 0
            while i < len(
                    self.time_queue) and block.timestamp > self.time_queue[i].timestamp:
                i += 1
            self.time_queue.insert(i, block)
            log.info('Block received too early (%d vs %d). Delaying for %d seconds' %
                     (now, block.header.timestamp, block.header.timestamp - now))
            return False
        # Is the block being added to the head?
        if block.header.prevhash == self.head_hash:
            log.info('Adding to head',
                     head=encode_hex(block.header.prevhash[:4]))
            self.state.deletes = []
            self.state.changed = {}
            try:
                apply_block(self.state, block)
            except (AssertionError, KeyError, ValueError, InvalidTransaction, VerificationFailed) as e:
                log.info('Block %d (%s) with parent %s invalid, reason: %s' %
                         (block.number, encode_hex(block.header.hash[:4]), encode_hex(block.header.prevhash[:4]), str(e)))
                return False
            self.db.put(b'block:%d' % block.header.number, block.header.hash)
            # side effect: put 'score:' cache in db
            block_score = self.get_score(block)
            self.head_hash = block.header.hash
            for i, tx in enumerate(block.transactions):
                self.db.put(b'txindex:' +
                            tx.hash, rlp.encode([block.number, i]))
            assert self.get_blockhash_by_number(
                block.header.number) == block.header.hash
            deletes = self.state.deletes
            changed = self.state.changed
        # Or is the block being added to a chain that is not currently the
        # head?
        elif block.header.prevhash in self.env.db:
            log.info('Receiving block %d (%s) not on head (%s), adding to secondary post state %s' %
                     (block.number, encode_hex(block.header.hash[:4]),
                      encode_hex(self.head_hash[:4]), encode_hex(block.header.prevhash[:4])))
            temp_state = self.mk_poststate_of_blockhash(block.header.prevhash)
            try:
                apply_block(temp_state, block)
            except (AssertionError, KeyError, ValueError, InvalidTransaction, VerificationFailed) as e:
                log.info('Block %s with parent %s invalid, reason: %s' %
                    (encode_hex(block.header.hash[:4]), encode_hex(block.header.prevhash[:4]), str(e)))
                return False
            deletes = temp_state.deletes
            block_score = self.get_score(block)
            changed = temp_state.changed
            # If the block should be the new head, replace the head
            if block_score > self.get_score(self.head):
                b = block
                new_chain = {}
                # Find common ancestor
                while b.header.number >= int(self.db.get(b'GENESIS_NUMBER')):
                    new_chain[b.header.number] = b
                    key = b'block:%d' % b.header.number
                    orig_at_height = self.db.get(
                        key) if key in self.db else None
                    if orig_at_height == b.header.hash:
                        break
                    if b.prevhash not in self.db or self.db.get(
                            b.prevhash) == b'GENESIS':
                        break
                    b = self.get_parent(b)
                replace_from = b.header.number
                # Replace block index and tx indices, and edit the state cache

                # Get a list of all accounts that have been edited along the old and
                # new chains
                changed_accts = {}
                # Read: for i in range(common ancestor block number...new block
                # number)
                for i in itertools.count(replace_from):
                    log.info('Rewriting height %d' % i)
                    key = b'block:%d' % i
                    # Delete data for old blocks
                    orig_at_height = self.db.get(
                        key) if key in self.db else None
                    if orig_at_height:
                        orig_block_at_height = self.get_block(orig_at_height)
                        log.info(
                            '%s no longer in main chain' %
                            encode_hex(
                                orig_block_at_height.header.hash))
                        # Delete from block index
                        self.db.delete(key)
                        # Delete from txindex
                        for tx in orig_block_at_height.transactions:
                            if b'txindex:' + tx.hash in self.db:
                                self.db.delete(b'txindex:' + tx.hash)
                        # Add to changed list
                        acct_list = self.db.get(
                            b'changed:' + orig_block_at_height.hash)
                        for j in range(0, len(acct_list), 20):
                            changed_accts[acct_list[j: j + 20]] = True
                    # Add data for new blocks
                    if i in new_chain:
                        new_block_at_height = new_chain[i]
                        log.info(
                            '%s now in main chain' %
                            encode_hex(
                                new_block_at_height.header.hash))
                        # Add to block index
                        self.db.put(key, new_block_at_height.header.hash)
                        # Add to txindex
                        for j, tx in enumerate(
                                new_block_at_height.transactions):
                            self.db.put(b'txindex:' + tx.hash,
                                        rlp.encode([new_block_at_height.number, j]))
                        # Add to changed list
                        if i < b.number:
                            acct_list = self.db.get(
                                b'changed:' + new_block_at_height.hash)
                            for j in range(0, len(acct_list), 20):
                                changed_accts[acct_list[j: j + 20]] = True
                    if i not in new_chain and not orig_at_height:
                        break
                # Add changed list from new head to changed list
                for c in changed.keys():
                    changed_accts[c] = True
                # Update the on-disk state cache
                for addr in changed_accts.keys():
                    data = temp_state.trie.get(addr)
                    if data:
                        self.state.db.put(b'address:' + addr, data)
                    else:
                        try:
                            self.state.db.delete(b'address:' + addr)
                        except KeyError:
                            pass
                self.head_hash = block.header.hash
                self.state = temp_state
                self.state.executing_on_head = True
        # Block has no parent yet
        else:
            if block.header.prevhash not in self.parent_queue:
                self.parent_queue[block.header.prevhash] = []
            self.parent_queue[block.header.prevhash].append(block)
            log.info('Got block %d (%s) with prevhash %s, parent not found. Delaying for now' %
                     (block.number, encode_hex(block.hash[:4]), encode_hex(block.prevhash[:4])))
            return False
        self.add_child(block)
        
        self.db.put(b'head_hash', self.head_hash)

        self.db.put(block.hash, rlp.encode(block))
        self.db.put(b'changed:' + block.hash,
                    b''.join([k.encode() if not is_string(k) else k for k in list(changed.keys())]))
        print('Saved %d address change logs' % len(changed.keys()))
        self.db.put(b'deletes:' + block.hash, b''.join(deletes))
        log.debug('Saved %d trie node deletes for block %d (%s)' %
                  (len(deletes), block.number, utils.encode_hex(block.hash)))
        # Delete old junk data
        old_block_hash = self.get_blockhash_by_number(
            block.number - self.max_history)
        if old_block_hash:
            try:
                deletes = self.db.get(b'deletes:' + old_block_hash)
                log.debug(
                    'Deleting up to %d trie nodes' %
                    (len(deletes) // 32))
                rdb = RefcountDB(self.db)
                for i in range(0, len(deletes), 32):
                    rdb.delete(deletes[i: i + 32])
                self.db.delete(b'deletes:' + old_block_hash)
                self.db.delete(b'changed:' + old_block_hash)
            except KeyError as e:
                print(e)
                pass
        self.db.commit()
        assert (b'deletes:' + block.hash) in self.db
        log.info('Added block %d (%s) with %d txs and %d gas' %
                 (block.header.number, encode_hex(block.header.hash)[:8],
                  len(block.transactions), block.header.gas_used))
        # Call optional callback
        if self.new_head_cb and block.header.number != 0:
            self.new_head_cb(block)
        # Are there blocks that we received that were waiting for this block?
        # If so, process them.
        if block.header.hash in self.parent_queue:
            for _blk in self.parent_queue[block.header.hash]:
                self.add_block(_blk)
            del self.parent_queue[block.header.hash]
        return True

    def __contains__(self, blk):
        if isinstance(blk, (str, bytes)):
            try:
                blk = rlp.decode(self.db.get(blk), Block)
            except BaseException:
                return False
        try:
            o = self.get_block(self.get_blockhash_by_number(blk.number)).hash
            assert o == blk.hash
            return True
        except Exception as e:
            return False

    def has_block(self, block):
        return block in self

    def has_blockhash(self, blockhash):
        return blockhash in self.db

    def get_chain(self, frm=None, to=2**63 - 1):
        if frm is None:
            frm = int(self.db.get(b'GENESIS_NUMBER')) + 1
        chain = []
        for i in itertools.islice(itertools.count(), frm, to):
            h = self.get_blockhash_by_number(i)
            if not h:
                return chain
            chain.append(self.get_block(h))

    # Get block number and transaction index
    def get_tx_position(self, tx):
        if not isinstance(tx, (str, bytes)):
            tx = tx.hash
        if b'txindex:' + tx in self.db:
            data = rlp.decode(self.db.get(b'txindex:' + tx))
            return big_endian_to_int(data[0]), big_endian_to_int(data[1])
        else:
            return None

    def get_transaction(self, tx):
        print('Deprecated. Use get_tx_position')
        blknum, index = self.get_tx_position(tx)
        blk = self.get_block_by_number(blknum)
        return blk.transactions[index], blk, index

    # Get descendants of a block
    def get_descendants(self, block):
        output = []
        blocks = [block]
        while len(blocks):
            b = blocks.pop()
            blocks.extend(self.get_children(b))
            output.append(b)
        return output

    @property
    def db(self):
        return self.env.db

    # Get blockhashes starting from a hash and going backwards
    def get_blockhashes_from_hash(self, blockhash, max_num):
        block = self.get_block(blockhash)
        if block is None:
            return []

        header = block.header
        hashes = []
        for i in range(max_num):
            block = self.get_block(header.prevhash)
            if block is None:
                break
            header = block.header
            hashes.append(header.hash)
            if header.number == 0:
                break
        return hashes

    @property
    def config(self):
        return self.env.config
