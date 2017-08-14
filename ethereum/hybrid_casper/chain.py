import json
import random
import time
import itertools
from ethereum import utils
from ethereum.utils import parse_as_bin, big_endian_to_int
from ethereum.meta import apply_block
from ethereum.common import update_block_env_variables
import rlp
from rlp.utils import encode_hex
from ethereum.exceptions import InvalidTransaction, VerificationFailed
from ethereum.slogging import get_logger
from ethereum.config import Env
from ethereum.new_state import State, dict_to_prev_header
from ethereum.block import Block, BlockHeader, BLANK_UNCLES_HASH
from ethereum.pow.consensus import initialize
from ethereum.genesis_helpers import mk_basic_state, state_from_genesis_declaration, initialize_genesis_keys


log = get_logger('eth.chain')
config_string = ':info,eth.chain:debug'
# from ethereum.slogging import configure_logging
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)


class Chain(object):

    def __init__(self, genesis=None, env=None, coinbase=b'\x00' * 20,
                 new_head_cb=None, reset_genesis=False, localtime=None, **kwargs):
        self.env = env or Env()
        # Initialize the state
        if 'head_hash' in self.db:  # new head tag
            self.state = self.mk_poststate_of_blockhash(self.db.get('head_hash'))
            print('Initializing chain from saved head, #%d (%s)' %
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
            print('Initializing chain from provided state snapshot, %d (%s)' %
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
        self.casper_address = self.config['CASPER_ADDRESS']
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

    # ~~~~~~~~~~~~~~~~~~~~ CASPER ~~~~~~~~~~~~~~~~~~~~ #
    def casper_log_handler(self, contract_log, blockhash):
        # We only want logs from the Casper contract
        if contract_log.address != self.casper_address:
            return
        # Check to see if it is a commit
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
            self.store_commit(commit, total_deposits, validator_deposits)
            # Update the checkpoint_head_hash if needed
            self.recompute_head(self.get_block(commit['hash']))

    def store_commit(self, commit, total_deposits, validator_deposits):
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

    def get_score(self, block):
        if self.is_checkpoint(block):
            cp_score = self.get_checkpoint_score(block.hash) * 10000000000000000000
        else:
            cp_score = 0
        difficulty_score = self.get_pow_difficulty(block)
        return cp_score + difficulty_score

    def is_checkpoint(self, block):
        if block.header.number % self.config['EPOCH_LENGTH'] == 0:
            return True
        return False

    def get_checkpoint_child(self, checkpoint_hash):
        try:
            checkpoint_child_hash = self.db.get(b'cp_child:' + checkpoint_hash)
        except KeyError:
            checkpoint_child_hash = checkpoint_hash
        return self.get_block(checkpoint_child_hash)

    def recompute_cp_child(self, candidate):
        parent_cp = self.get_prev_checkpoint_block(candidate)
        current_cp_child = self.get_checkpoint_child(parent_cp.hash)
        # If checkpoint has not yet set a child, set this as a child
        if current_cp_child == parent_cp:
            log.info('We found first pow block: {} {}'.format(candidate.header.number, utils.encode_hex(candidate.hash)))
            self.db.put(b'cp_child:' + parent_cp.hash, candidate.hash)
            return True
        current_cp_child_score = self.get_score(current_cp_child)
        candidate_cp_score = self.get_score(candidate)
        if candidate_cp_score > current_cp_child_score:
            self.db.put(b'cp_child:' + parent_cp.hash, candidate.hash)
            return True
        return False

    def recompute_head(self, candidate):
        # Attempt to update our candidate checkpoint parent's child_cp pointer
        self.recompute_cp_child(candidate)
        # Get the candidate checkpoint
        if self.is_checkpoint(candidate):
            candidate_checkpoint = candidate
        else:
            candidate_checkpoint = self.get_prev_checkpoint_block(candidate)
        # Return False if the candidate checkpoint is not a child of our head or a heavier fork
        if not (self.checkpoint_head_hash == candidate_checkpoint.hash or
                self.is_parent_checkpoint(self.checkpoint_head_hash, candidate_checkpoint.hash) or
                self.is_fork_commits_heavier_than_head(self.checkpoint_head_hash, candidate_checkpoint.hash)):
            return False
        log.info('Update checkpoint to: {} - Update head to: {}'.format(utils.encode_hex(candidate.hash), utils.encode_hex(self.head_hash)))
        child = self.get_checkpoint_child(candidate_checkpoint.hash)
        # Find the longest known child chain
        while self.is_checkpoint(child) and self.get_checkpoint_child(child.hash) != child:
            child = self.get_checkpoint_child(child.hash)
        if self.is_checkpoint(child):
            self.checkpoint_head_hash = child.hash
        else:
            self.checkpoint_head_hash = self.get_prev_checkpoint_block(child).hash
        # self.change_head(child)
        log.info('Setting head: {}'.format(child.header.number))
        self.set_head(child)
        return True

    def is_fork_commits_heavier_than_head(self, head_hash, fork_hash):
        # Get the relevant blocks
        head = self.get_block(head_hash)
        fork = self.get_block(fork_hash)
        # Store our fork's score
        fork_score = self.get_checkpoint_score(fork.header.hash)
        # Create max_head_score which will store the highest commit ration on the head chain
        max_head_score = self.get_checkpoint_score(head.header.hash)
        # Set max_head_score by looping over the head & fork until their previous checkpoints are the same
        while self.get_prev_checkpoint_block(fork) != self.get_prev_checkpoint_block(head):
            if head.header.number > fork.header.number:
                head = self.get_prev_checkpoint_block(head)
                if self.get_checkpoint_score(head.header.hash) > max_head_score:
                    max_head_score = self.get_checkpoint_score(head.header.hash)
            else:
                fork = self.get_prev_checkpoint_block(fork)
        # If the max_head_score is lower than the fork score, return True (choose the fork)
        if max_head_score < fork_score:
            return True
        # Otherwise, return False (continue to use the head)
        return False

    # ~~~~~~~~~~~~~~~~~~~~ ADD BLOCK ~~~~~~~~~~~~~~~~~~~~ #

    # This function should be called periodically so as to
    # process blocks that were received but laid aside because
    # they were received too early
    def process_time_queue(self, new_time=None):
        self.localtime = time.time() if new_time is None else new_time
        i = 0
        while i < len(self.time_queue) and self.time_queue[i].timestamp <= new_time:
            log.info('Adding scheduled block')
            pre_len = len(self.time_queue)
            self.add_block(self.time_queue.pop(i))
            if len(self.time_queue) == pre_len:
                i += 1

    def should_add_block(self, block):
        # Check that the block wasn't recieved too early
        now = self.localtime
        if block.header.timestamp > now:
            i = 0
            while i < len(self.time_queue) and block.timestamp > self.time_queue[i].timestamp:
                i += 1
            self.time_queue.insert(i, block)
            log.info('Block received too early (%d vs %d). Delaying for %d seconds' %
                     (now, block.header.timestamp, block.header.timestamp - now))
            return False
        # Check that the block's parent has already been added
        if block.header.prevhash not in self.env.db:
            if block.header.prevhash not in self.parent_queue:
                self.parent_queue[block.header.prevhash] = []
            self.parent_queue[block.header.prevhash].append(block)
            log.info('Got block %d (%s) with prevhash %s, parent not found. Delaying for now' %
                     (block.number, encode_hex(block.hash), encode_hex(block.prevhash)))
            return False
        # Check that the block doesn't throw an exception
        if block.header.prevhash == self.head_hash:
            temp_state = self.state.ephemeral_clone()
        else:
            temp_state = self.mk_poststate_of_blockhash(block.header.prevhash)
        try:
            apply_block(temp_state, block)
        except (AssertionError, KeyError, ValueError, InvalidTransaction, VerificationFailed) as e:  # FIXME add relevant exceptions here
            log.info('Block %s with parent %s invalid, reason: %s' % (encode_hex(block.header.hash), encode_hex(block.header.prevhash), e))
            return False
        return True

    def add_block_to_head(self, block):
        log.info('Adding to head', head=encode_hex(block.header.prevhash))
        apply_block(self.state, block)
        self.db.put('block:' + str(block.header.number), block.header.hash)
        self.get_pow_difficulty(block)  # side effect: put 'score:' cache in db
        self.head_hash = block.header.hash
        for i, tx in enumerate(block.transactions):
            self.db.put(b'txindex:' + tx.hash, rlp.encode([block.number, i]))

    def set_head(self, block):
        # ~~~ PoW Fork Choice ~~~~ #
        # If block is directly on top of the head, immediately make it our head
        if block.header.prevhash == self.head_hash:
            self.add_block_to_head(block)
        else:  # Otherwise, check if we should change our head
            # Here we should run `is_fork_heavier_than_head` but modify it so it works for both PoW and Casper... ODEE great
            log.info('Receiving block not on head, adding to secondary post state',
                     prevhash=encode_hex(block.header.prevhash))
            self.change_head(block)
        self.db.put('head_hash', self.head_hash)
        self.db.commit()
        log.info('Added block %d (%s) with %d txs and %d gas' %
                 (block.header.number, encode_hex(block.header.hash)[:8],
                  len(block.transactions), block.header.gas_used))
        if self.new_head_cb and block.header.number != 0:
            self.new_head_cb(block)
        # Are there blocks that we received that were waiting for this block?
        # If so, process them.
        if block.header.hash in self.parent_queue:
            for _blk in self.parent_queue[block.header.hash]:
                self.add_block(_blk)
            del self.parent_queue[block.header.hash]
        return True

    # Call upon receiving a block
    def add_block(self, block):
        # ~~~ Validate ~~~~ #
        # Validate that the block should be added
        if not self.should_add_block(block):
            return False
        # ~~~ Store ~~~~ #
        # Store the block
        self.db.put(block.header.hash, rlp.encode(block))
        self.add_child(block)
        # Store the state root
        if block.header.prevhash == self.head_hash:
            temp_state = self.state.ephemeral_clone()
        else:
            temp_state = self.mk_poststate_of_blockhash(block.header.prevhash)
        apply_block(temp_state, block)
        self.db.put(b'state:' + block.header.hash, temp_state.trie.root_hash)
        # ~~~ Finality Gadget Fork Choice ~~~~ #
        for r in temp_state.receipts:
            [self.casper_log_handler(l, block.header.hash) for l in r.logs]
        # Try recomputing the head
        self.recompute_head(block)
        return True

    def change_head(self, block):
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
        self.state = self.mk_poststate_of_blockhash(block.hash)

    # ~~~~~~~~~~~~~~~~~~~~ CASPER UTILS ~~~~~~~~~~~~~~~~~~~~ #

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
        b = block
        for i in range(checkpoint_distance):
            if b'prev_cp' + b.hash in self.db:
                prev_checkpoint = self.get_block(self.db.get(b'prev_cp' + b.hash))
                self.db.put(b'prev_cp' + block.hash, prev_checkpoint.hash)
                return prev_checkpoint
            b = self.get_block(b.header.prevhash)
            if b is None:
                return
        self.db.put(b'prev_cp' + block.hash, b.hash)
        return b

    def is_parent_checkpoint(self, parent, child):
        if parent == b'\x00' * 32:
            # If the parent checkpoint is the genesis checkpoint, then the child must be a decedent
            return True
        parent_block = self.get_block(parent)
        child_block = self.get_block(child)
        while parent_block.header.number < child_block.header.number:
            log.info('child block num: {}'.format(child_block.header.number))
            child_block = self.get_prev_checkpoint_block(child_block)
        if parent_block == child_block:
            return True
        else:
            return False

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

    # ~~~~~~~~~~~~~~~~~~~~ BLOCK UTILS ~~~~~~~~~~~~~~~~~~~~ #

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
    def get_pow_difficulty(self, block):
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

    # Get blockhashes starting from a hash and going backwards
    def get_blockhashes_from_hash(self, hash, max):
        block = self.get_block(hash)
        if block is None:
            return []

        header = block.header
        hashes = []
        for i in xrange(max):
            hash = header.prevhash
            block = self.get_block(hash)
            if block is None:
                break
            header = block.header
            hashes.append(header.hash)
            if header.number == 0:
                break
        return hashes

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

    @property
    def config(self):
        return self.env.config

    @property
    def db(self):
        return self.env.db
