import json
import random
import time
import itertools
from ethereum import utils
from ethereum.utils import parse_as_bin, big_endian_to_int
from ethereum.meta import apply_block
from ethereum.common import update_block_env_variables
from ethereum.messages import apply_transaction
from ethereum import transactions
from ethereum.hybrid_casper import casper_utils
from ethereum.tools import tester
import rlp
from rlp.utils import encode_hex
from ethereum.exceptions import InvalidNonce, InsufficientStartGas, UnsignedTransaction, \
    BlockGasLimitReached, InsufficientBalance, InvalidTransaction, VerificationFailed
from ethereum.slogging import get_logger, configure_logging
from ethereum.config import Env
from ethereum.state import State, dict_to_prev_header
from ethereum.block import Block, BlockHeader, BLANK_UNCLES_HASH
from ethereum.pow.consensus import initialize
from ethereum.genesis_helpers import mk_basic_state, state_from_genesis_declaration, \
        initialize_genesis_keys


log = get_logger('eth.chain')
config_string = ':info,eth.chain:debug'
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)


class Chain(object):

    def __init__(self, genesis=None, env=None, coinbase=b'\x00' * 20, \
                 new_head_cb=None, reset_genesis=False, localtime=None, **kwargs):
        self.env = env or Env()
        # Initialize the state
        if 'head_hash' in self.db:  # new head tag
            self.state = self.mk_poststate_of_blockhash(self.db.get('head_hash'))
            print('Initializing chain from saved head, #%d (%s)' % \
                (self.state.prev_headers[0].number, encode_hex(self.state.prev_headers[0].hash)))
        elif genesis is None:
            raise Exception("Need genesis decl!")
        elif isinstance(genesis, State):
            assert env is None
            self.state = genesis
            self.env = self.state.env
            print('Initializing chain from provided state')
        elif "extraData" in genesis:
            self.state = state_from_genesis_declaration(
                genesis, self.env)
            reset_genesis = True
            print('Initializing chain from provided genesis declaration')
        elif "prev_headers" in genesis:
            self.state = State.from_snapshot(genesis, self.env)
            reset_genesis = True
            print('Initializing chain from provided state snapshot, %d (%s)' % \
                (self.state.block_number, encode_hex(self.state.prev_headers[0].hash[:8])))
        else:
            print('Initializing chain from new state based on alloc')
            self.state = mk_basic_state(genesis, {
                "number": kwargs.get('number', 0),
                "gas_limit": kwargs.get('gas_limit', 4712388),
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

        self.head_hash = self.state.prev_headers[0].hash
        self.checkpoint_head_hash = b'\x00' * 32
        self.commit_logs = []
        self.casper_address = self.env.config['CASPER_ADDRESS']
        self.db.put('GENESIS_NUMBER', str(self.state.block_number))
        assert self.state.block_number == self.state.prev_headers[0].number
        if reset_genesis:
            self.genesis = Block(self.state.prev_headers[0], [], [])
            initialize_genesis_keys(self.state, self.genesis)
        else:
            self.genesis = self.get_block_by_number(0)
        self.min_gasprice = kwargs.get('min_gasprice', 5 * 10**9)
        self.coinbase = coinbase
        self.extra_data = 'moo ha ha says the laughing cow.'
        self.time_queue = []
        self.parent_queue = {}
        self.localtime = time.time() if localtime is None else localtime

    @property
    def head(self):
        try:
            block_rlp = self.db.get(self.head_hash)
            if block_rlp == 'GENESIS':
                return self.genesis
            else:
                return rlp.decode(block_rlp, Block)
        except Exception as e:
            log.error(e)
            return None

    # Casper fork choice outline:
    # TODO

    def casper_log_handler(self, contract_log, fork_state, blockhash):
        # We only want logs from the Casper contract
        if contract_log.address != self.casper_address:
            return
        # Check to see if it is a prepare or a commit
        if contract_log.topics[0] == utils.bytearray_to_int(utils.sha3("prepare()")):
            log.info('Recieved prepare')
        elif contract_log.topics[0] == utils.bytearray_to_int(utils.sha3("commit()")):
            self.commit_logs.append(contract_log.data)
            # Wait until we have all three commit events before processing the commit
            if len(self.commit_logs) != 3:
                # If we don't have all three, return.
                return
            log.info('Recieved commit')
            # Extract the raw commit RLP, total deposits for the dynasty, and this validator's deposits
            raw_commit, total_deposits, validator_deposits = self.commit_logs.pop(0), self.commit_logs.pop(0), self.commit_logs.pop(0)
            commit = self.get_decoded_commit(raw_commit)
            checkpoint_hash = commit['hash']
            # Store the total deposits for this checkpoint if we haven't already
            if b'cp_total_deposits:' + checkpoint_hash not in self.db:
                self.db.put(b'cp_total_deposits:' + checkpoint_hash, total_deposits)
            # Store this validator's deposit for this checkpoint
            try:
                deposits = self.db.get(b'cp_deposits:' + checkpoint_hash)
            except KeyError:
                deposits = dict()
            if commit['validator_index'] in deposits:
                log.info('Validator deposit already stored!')
            deposits[commit['validator_index']] = validator_deposits
            self.db.put(b'cp_deposits:' + checkpoint_hash, deposits)
            # Update the checkpoint_head_hash if needed
            self.maybe_update_checkpoint_head_hash(commit['hash'])

    def get_decoded_commit(self, commit_rlp):
        commit_array = rlp.decode(commit_rlp)
        commit = dict()
        for i, field in enumerate(['validator_index', 'epoch', 'hash', 'prev_commit_epoch', 'sig']):
            commit[field] = commit_array[i]
        commit['raw_rlp'] = commit_rlp
        return commit

    def get_prev_checkpoint_block(self, block):
        epoch_length = self.env.config['EPOCH_LENGTH']
        checkpoint_distance = (block.header.number) % epoch_length
        if checkpoint_distance == 0:
            checkpoint_distance = epoch_length
        for i in range(checkpoint_distance):
            if block.header.prevhash == b'\x00' * 32:
                return block
            block = self.get_block(block.header.prevhash)
        return block

    def is_parent_checkpoint(self, parent, child):
        parent_block = self.get_block(parent)
        child_block = self.get_block(child)
        while parent_block.header.number > child_block.header.number:
            parent_block = self.get_prev_checkpoint_block(parent_block)
        if parent_block == child_block:
            return True
        else:
            return False

    def maybe_update_checkpoint_head_hash(self, fork_hash):
        # If our checkpoint head is the initial head hash value, immediately use the fork hash
        if self.checkpoint_head_hash == b'\x00' * 32:
            self.checkpoint_head_hash = fork_hash
            return
        # Check that the fork isn't a direct decendent of head
        if self.is_parent_checkpoint(self.checkpoint_head_hash, fork_hash):
            return
        # Check that the fork is heavier than the head
        if not self.is_fork_commits_heavier_than_head(self.checkpoint_head_hash, fork_hash):
            return
        self.checkpoint_head_hash = fork_hash
        # Set the head_hash to equal the latest block known for our checkpoint
        try:
            self.head_hash = self.db.get(b'cp_head_hash:' + self.checkpoint_head_hash)
        except KeyError:
            self.head_hash = fork_hash
        log.info('Update checkpoint to: {} - Update head to: {}'.format(utils.encode_hex(fork_hash), utils.encode_hex(self.head_hash)))

    def is_fork_commits_heavier_than_head(self, head_hash, fork_hash):
        # Get the related blocks
        hc = self.get_block(head_hash)
        fc = self.get_block(fork_hash)
        # Calculate the score for the fork checkpoint
        fork_score = self.get_checkpoint_score(fc.header.hash)
        # Loop over the hc & fc until they are equal (we find a shared parent)
        while fc != hc:
            if fc.header.number > hc.header.number:
                fc = self.get_prev_checkpoint_block(fc)
                continue
            head_score = self.get_checkpoint_score(hc.header.hash)
            # If the fork score is lower than the head at any point, return False
            if fork_score < head_score:
                return False
            hc = self.get_prev_checkpoint_block(hc)
        # We've compared the fork score to all head scores, and so return True
        return True

    def get_checkpoint_score(self, checkpoint_hash):
        try:
            total_deposits = self.db.get(b'cp_total_deposits:' + checkpoint_hash)
        except KeyError:
            return 0
        prev_dyn_total_deposits, curr_dyn_total_deposits = utils.big_endian_to_int(total_deposits[:32]), utils.big_endian_to_int(total_deposits[32:])
        deposits = self.db.get(b'cp_deposits:' + checkpoint_hash)
        prev_dyn_deposits = 0
        curr_dyn_deposits = 0
        for key, d in deposits.items():
            prev_dyn_deposits += utils.big_endian_to_int(d[:32])
            curr_dyn_deposits += utils.big_endian_to_int(d[32:])
        prev_dyn_score = prev_dyn_deposits / prev_dyn_total_deposits if prev_dyn_total_deposits > 0 else 1
        curr_dyn_score = curr_dyn_deposits / curr_dyn_total_deposits if curr_dyn_total_deposits > 0 else 1
        return min(prev_dyn_score, curr_dyn_score)

    def mk_poststate_of_blockhash(self, blockhash, convert=False):
        if blockhash not in self.db:
            raise Exception("Block hash %s not found" % encode_hex(blockhash))

        block_rlp = self.db.get(blockhash)
        if block_rlp == 'GENESIS':
            return State.from_snapshot(json.loads(self.db.get('GENESIS_STATE')), self.env)
        block = rlp.decode(block_rlp, Block)

        state = State(env=self.env)
        state.trie.root_hash = block.header.state_root if convert else self.db.get(b'state:'+blockhash)
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
            except:
                break
        if i < header_depth:
            if state.db.get(b.header.prevhash) == 'GENESIS':
                jsondata = json.loads(state.db.get('GENESIS_STATE'))
                for h in jsondata["prev_headers"][:header_depth - i]:
                    state.prev_headers.append(dict_to_prev_header(h))
                for blknum, uncles in jsondata["recent_uncles"].items():
                    if int(blknum) >= state.block_number - int(state.config['MAX_UNCLE_DEPTH']):
                        state.recent_uncles[blknum] = [parse_as_bin(u) for u in uncles]
            else:
                raise Exception("Dangling prevhash")
        assert len(state.journal) == 0, state.journal
        return state

    def get_parent(self, block):
        if block.header.number == int(self.db.get('GENESIS_NUMBER')):
            return None
        return self.get_block(block.header.prevhash)

    def get_block(self, blockhash):
        try:
            block_rlp = self.db.get(blockhash)
            if block_rlp == 'GENESIS':
                if not hasattr(self, 'genesis'):
                    self.genesis = rlp.decode(self.db.get('GENESIS_RLP'), sedes=Block)
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
        except:
            existing = b''
        existing_hashes = []
        for i in range(0, len(existing), 32):
            existing_hashes.append(existing[i: i+32])
        if child.header.hash not in existing_hashes:
            self.db.put(b'child:' + child.header.prevhash, existing + child.header.hash)

    def get_blockhash_by_number(self, number):
        try:
            return self.db.get('block:' + str(number))
        except:
            return None

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
        except:
            return []

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
            if block is None:
                return 0
        score = int(self.db.get(key))
        for h, d in fills:
            key = b'score:' + h
            score = score + d + random.randrange(d // 10**6 + 1)
            self.db.put(key, str(score))

        return score

    # These two functions should be called periodically so as to
    # process blocks that were received but laid aside because
    # either the parent was missing or they were received
    # too early
    def process_time_queue(self, new_time=None):
        self.localtime = time.time() if new_time is None else new_time
        i = 0
        while i < len(self.time_queue) and self.time_queue[i].timestamp <= new_time:
            log.info('Adding scheduled block')
            pre_len = len(self.time_queue)
            self.add_block(self.time_queue.pop(i))
            if len(self.time_queue) == pre_len:
                i += 1

    def process_parent_queue(self):
        deletions = []
        for parent_hash, blocks in self.parent_queue.items():
            if parent_hash in self.db:
                for block in blocks:
                    self.add_block(block)
                deletions.append(parent_hash)
        for parent_hash in deletions:
            del self.parent_queue[parent_hash]

    # Call upon receiving a block
    def add_block(self, block):
        now = self.localtime
        if block.header.timestamp > now:
            i = 0
            while i < len(self.time_queue) and block.timestamp > self.time_queue[i].timestamp:
                i += 1
            self.time_queue.insert(i, block)
            log.info('Block received too early (%d vs %d). Delaying for %d seconds' %
                     (now, block.header.timestamp, block.header.timestamp - now))
            return False
        # Check what the current checkpoint head should be
        if block.header.number > int(self.db.get('GENESIS_NUMBER')) + 1 and block.header.prevhash in self.env.db:
            temp_state = self.mk_poststate_of_blockhash(block.header.prevhash)
            try:
                apply_block(temp_state, block)
            except (KeyError, ValueError) as e:  # FIXME add relevant exceptions here
                log.info('Block %s with parent %s invalid, reason: %s' % (encode_hex(block.header.hash), encode_hex(block.header.prevhash), e))
                return False
            self.db.put(b'state:' + block.header.hash, temp_state.trie.root_hash)
            # Check to see if we need to update the checkpoint_head
            for r in temp_state.receipts:
                [self.casper_log_handler(l, temp_state, block.header.hash) for l in r.logs]
        if block.header.prevhash == self.head_hash:
            log.info('Adding to head', head=encode_hex(block.header.prevhash))
            try:
                apply_block(self.state, block)
            except (AssertionError, KeyError, ValueError, InvalidTransaction, VerificationFailed) as e:  # FIXME add relevant exceptions here
                log.info('Block %s with parent %s invalid, reason: %s' % (encode_hex(block.header.hash), encode_hex(block.header.prevhash), e))
                return False
            self.db.put('block:' + str(block.header.number), block.header.hash)
            self.db.put(b'state:' + block.header.hash, self.state.trie.root_hash)
            block_score = self.get_score(block)  # side effect: put 'score:' cache in db
            self.head_hash = block.header.hash
            for i, tx in enumerate(block.transactions):
                self.db.put(b'txindex:' + tx.hash, rlp.encode([block.number, i]))
        elif block.header.prevhash in self.env.db:
            log.info('Receiving block not on head, adding to secondary post state',
                     prevhash=encode_hex(block.header.prevhash))
            temp_state = self.mk_poststate_of_blockhash(block.header.prevhash)
            try:
                apply_block(temp_state, block)
            except (AssertionError, KeyError, ValueError, InvalidTransaction, VerificationFailed) as e:  # FIXME add relevant exceptions here
                log.info('Block %s with parent %s invalid, reason: %s' % (encode_hex(block.header.hash), encode_hex(block.header.prevhash), e))
                return False
            self.db.put(b'state:' + block.header.hash, temp_state.trie.root_hash)
            block_score = self.get_score(block)
            # Get the checkpoint in the fork with the same block number as our head checkpoint, if they are equal, the block is a child
            # TODO: Clean up this logic--it's super ugly
            fork_cp_block = self.get_prev_checkpoint_block(block)
            head_cp_block = self.get_block(self.checkpoint_head_hash) if self.checkpoint_head_hash != b'\x00'*32 else fork_cp_block
            while(fork_cp_block.header.number > head_cp_block.header.number):
                fork_cp_block = self.get_prev_checkpoint_block(fork_cp_block)
            # Replace the head only if the fork block is a child of the head checkpoint
            if (head_cp_block.hash == fork_cp_block.hash and block_score > self.get_score(self.head)):
                log.info('Replacing head')
                b = block
                new_chain = {}
                while b.header.number >= int(self.db.get('GENESIS_NUMBER')):
                    new_chain[b.header.number] = b
                    key = 'block:' + str(b.header.number)
                    orig_at_height = self.db.get(key) if key in self.db else None
                    if orig_at_height == b.header.hash:
                        break
                    if b.prevhash not in self.db or self.db.get(b.prevhash) == 'GENESIS':
                        break
                    b = self.get_parent(b)
                replace_from = b.header.number
                for i in itertools.count(replace_from):
                    log.info('Rewriting height %d' % i)
                    key = 'block:' + str(i)
                    orig_at_height = self.db.get(key) if key in self.db else None
                    if orig_at_height:
                        self.db.delete(key)
                        orig_block_at_height = self.get_block(orig_at_height)
                        for tx in orig_block_at_height.transactions:
                            if b'txindex:' + tx.hash in self.db:
                                self.db.delete(b'txindex:' + tx.hash)
                    if i in new_chain:
                        new_block_at_height = new_chain[i]
                        self.db.put(key, new_block_at_height.header.hash)
                        for i, tx in enumerate(new_block_at_height.transactions):
                            self.db.put(b'txindex:' + tx.hash,
                                        rlp.encode([new_block_at_height.number, i]))
                    if i not in new_chain and not orig_at_height:
                        break
                self.head_hash = block.header.hash
                self.state = temp_state
        else:
            if block.header.prevhash not in self.parent_queue:
                self.parent_queue[block.header.prevhash] = []
            self.parent_queue[block.header.prevhash].append(block)
            log.info('No parent found. Delaying for now')
            return False
        self.add_child(block)
        self.db.put('head_hash', self.head_hash)
        self.db.put(b'cp_head_hash:' + self.checkpoint_head_hash, self.head_hash)
        self.db.put(block.header.hash, rlp.encode(block))
        self.db.commit()
        log.info('Added block %d (%s) with %d txs and %d gas' % \
            (block.header.number, encode_hex(block.header.hash)[:8],
             len(block.transactions), block.header.gas_used))
        if self.new_head_cb and block.header.number != 0:
            self.new_head_cb(block)
        return True

    def __contains__(self, blk):
        if isinstance(blk, (str, bytes)):
            try:
                blk = rlp.decode(self.db.get(blk), Block)
            except:
                return False
        try:
            o = self.get_block(self.get_blockhash_by_number(blk.number)).hash
            assert o == blk.hash
            return True
        except:
            return False

    def has_block(self, block):
        return block in self

    def has_blockhash(self, blockhash):
        return blockhash in self.db

    def get_chain(self, frm=None, to=2**63 - 1):
        if frm is None:
            frm = int(self.db.get('GENESIS_NUMBER')) + 1
        chain = []
        for i in itertools.islice(itertools.count(), frm, to):
            h = self.get_blockhash_by_number(i)
            if not h:
                return chain
            chain.append(self.get_block(h))

    # Recover transaction and the block that contains it
    def get_transaction(self, tx):
        if not isinstance(tx, (str, bytes)):
            tx = tx.hash
        if b'txindex:' + tx in self.db:
            data = rlp.decode(self.db.get(b'txindex:' + tx))
            blk, index = self.get_block_by_number(
                big_endian_to_int(data[0])), big_endian_to_int(data[1])
            tx = blk.transactions[index]
            return tx, blk, index
        else:
            return None

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

    def get_blockhashes_from_hash(self, hash, max):
        try:
            header = blocks.get_block_header(self.db, hash)
        except KeyError:
            return []

        hashes = []
        for i in xrange(max):
            hash = header.prevhash
            try:
                header = blocks.get_block_header(self.db, hash)
            except KeyError:
                break
            hashes.append(hash)
            if header.number == 0:
                break
        return hashes

    @property
    def config(self):
        return self.env.config
