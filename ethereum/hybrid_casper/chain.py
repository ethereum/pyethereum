import time
import itertools
from ethereum import utils
from ethereum.utils import parse_as_bin, big_endian_to_int
from ethereum import genesis_helpers
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
from ethereum.slogging import get_logger
from ethereum.config import Env
from ethereum.new_state import State, dict_to_prev_header
from ethereum.block import Block, BlockHeader, FakeHeader, BLANK_UNCLES_HASH
from ethereum.pow.consensus import initialize
from ethereum.genesis_helpers import mk_basic_state, state_from_genesis_declaration
import random
import json
log = get_logger('eth.chain')

from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.chain:debug'
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)


class Chain(object):

    def __init__(self, genesis=None, env=None, coinbase=b'\x00' * 20, \
                 new_head_cb=None, localtime=None, **kwargs):
        self.env = env or Env()
        # Initialize the state
        if 'head_hash' in self.db:
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
            print('Initializing chain from provided genesis declaration')
        elif "prev_headers" in genesis:
            self.state = State.from_snapshot(genesis, self.env)
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

        assert self.env.db == self.state.db

        initialize(self.state)
        self.new_head_cb = new_head_cb

        self.head_hash = self.state.prev_headers[0].hash
        self.checkpoint_head_hash = None
        self.casper_address = self.env.config['CASPER_ADDRESS']
        self.db.put('slashed_validators', [])
        self.genesis = Block(self.state.prev_headers[0], [], [])
        self.db.put(b'state:' + self.head_hash, self.state.trie.root_hash)
        self.db.put('GENESIS_NUMBER', str(self.state.block_number))
        self.db.put('GENESIS_HASH', self.state.prev_headers[0].hash)
        assert self.state.block_number == self.state.prev_headers[0].number
        self.db.put(b'score:' + self.state.prev_headers[0].hash, "0")
        self.db.put('GENESIS_STATE', json.dumps(self.state.to_snapshot()))
        self.db.put(self.head_hash, 'GENESIS')
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
    # 1. Each commit, store that commit for the checkpoint, then attempt to change the head
    # 2. Each call to checkpoint score, make a poststate of the checkpoint block, and add up all desposits from *non-slashed* validators
    # 3. Each slash, add the validator to the slashed validators list

    def casper_log_handler(self, contract_log, fork_state, blockhash):
        # We only want logs from the Casper contract
        if contract_log.address != self.casper_address:
            return
        # Check to see if it is a prepare or a commit
        if contract_log.topics[0] == utils.bytearray_to_int(utils.sha3("prepare()")):
            log.info('Recieved prepare')
        elif contract_log.topics[0] == utils.bytearray_to_int(utils.sha3("commit()")):
            log.info('Recieved commit')
            new_commit = self.get_decoded_commit(contract_log.data)
            checkpoint_id = self.mk_checkpoint_id(new_commit['epoch'], new_commit['hash'])
            try:
                commits = self.db.get(b'cp_commits:' + checkpoint_id)
            except KeyError:
                commits = dict()
            if new_commit['sig'] in commits:
                return
            commits[new_commit['sig']] = contract_log.data
            self.db.put(b'cp_commits:' + checkpoint_id, commits)
            self.maybe_update_checkpoint_head_hash(new_commit['hash'])
        else:
            raise(Exception('Recieved unexpected topic!'))

    def get_decoded_commit(self, commit_rlp):
        commit_array = rlp.decode(commit_rlp)
        commit = dict()
        for i, field in enumerate(['validator_index', 'epoch', 'hash', 'prev_commit_epoch', 'sig']):
            commit[field] = commit_array[i]
        commit['raw_rlp'] = commit_rlp
        return commit

    def get_checkpoint_score(self, blockhash, commits):
        state = self.mk_poststate_of_blockhash(blockhash)
        casper = tester.ABIContract(tester.State(state), casper_utils.casper_abi, self.casper_address)
        epoch = casper.get_current_epoch()
        curr_dynasty_deposits = 0
        prev_dynasty_deposits = 0
        # Calculate the current & previous dynasty scores
        for sig in commits:
            commit = self.get_decoded_commit(commits[sig])
            if commit['validator_index'] in self.db.get('slashed_validators'):
                continue
            epochcheck = casper.check_eligible_in_epoch(commit['validator_index'], epoch)
            if epochcheck >= 2:
                curr_dynasty_deposits += casper.get_validators__deposit(commit['validator_index'])
            if epochcheck % 2:
                prev_dynasty_deposits += casper.get_validators__deposit(commit['validator_index'])
        return min(curr_dynasty_deposits, prev_dynasty_deposits)

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

    def mk_checkpoint_id(self, epoch, blockhash):
        return utils.sha3(bytes(epoch) + blockhash)

    def get_commits(self, checkpoint_id):
        try:
            return self.db.get(b'cp_commits:' + checkpoint_id)
        except KeyError:
            return {}

    def maybe_update_checkpoint_head_hash(self, fork_hash):
        # If we have not yet set a checkpoint head, just use the first one we are given
        if not self.checkpoint_head_hash:
            self.checkpoint_head_hash = fork_hash
            return
        # Check that the fork is heavier than the head
        if not self.is_fork_commits_heavier_than_head(self.checkpoint_head_hash, fork_hash):
            return
        # TODO: Look for prepares
        # TODO: Update head_hash -- ie. self.head_hash = self.db.get('cp_head:' + fork_checkpoint_id)
        log.info('Update head to: %s' % str(fork_hash))
        print('Update head to: %s' % str(fork_hash))
        self.checkpoint_head_hash = fork_hash

    def is_fork_commits_heavier_than_head(self, checkpoint_head_hash, fork_hash):
        epoch_length = self.env.config['EPOCH_LENGTH']
        # Get the related blocks
        hc = self.get_block(self.checkpoint_head_hash)
        fc = self.get_block(fork_hash)
        # Calculate the score for the fork checkpoint
        fork_checkpoint_id = self.mk_checkpoint_id(utils.int_to_big_endian(fc.header.number // epoch_length), fc.header.hash)
        fork_score = self.get_checkpoint_score(fc.header.hash, self.get_commits(fork_checkpoint_id))
        # Loop over the hc & fc until they are equal (we find a shared parent)
        while fc != hc:
            if fc.header.number > hc.header.number:
                fc = self.get_prev_checkpoint_block(fc)
                continue
            checkpoint_id = self.mk_checkpoint_id(utils.int_to_big_endian(hc.header.number // epoch_length), hc.header.hash)
            head_score = self.get_checkpoint_score(hc.header.hash, self.get_commits(checkpoint_id))
            # If the fork score is lower than the head at any point, return False
            if fork_score < head_score:
                return False
            hc = self.get_prev_checkpoint_block(hc)
        # We've compared the fork score to all head scores, and so return True
        return True

    def mk_poststate_of_blockhash(self, blockhash):
        if blockhash not in self.db:
            raise Exception("Block hash %s not found" % encode_hex(blockhash))
        if self.db.get(blockhash) == 'GENESIS':
            return State.from_snapshot(json.loads(self.db.get('GENESIS_STATE')), self.env)
        state = State(env=self.env)
        state.trie.root_hash = self.db.get(b'state:' + blockhash)
        block = rlp.decode(self.db.get(blockhash), Block)
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
        return rlp.decode(self.db.get(block.header.prevhash), Block)

    def get_block(self, blockhash):
        try:
            block_rlp = self.db.get(blockhash)
            if block_rlp == 'GENESIS':
                return self.genesis
            else:
                return rlp.decode(block_rlp, Block)
        except:
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
        if isinstance(block, (BlockHeader, FakeHeader)):
            block = block.hash
        return [self.get_block(h) for h in self.get_child_hashes(block)]

    # Get the score (AKA total difficulty in PoW) of a given block
    def get_score(self, block):
        if not block:
            return 0
        key = b'score:' + block.header.hash
        if key not in self.db:
            try:
                parent_score = self.get_score(self.get_parent(block))
                self.db.put(key, str(parent_score + block.difficulty +
                                     random.randrange(block.difficulty // 10**6 + 1)))
            except:
                return int(self.db.get(b'score:' + block.prevhash))
        return int(self.db.get(key))

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
        for parent_hash, blocks in self.parent_queue.items():
            if parent_hash in self.db:
                for block in blocks:
                    self.add_block(block)
                del self.parent_queue[parent_hash]

    # Call upon receiving a block
    def add_block(self, block):  # TODO: Refactor this massive function
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
        if block.header.number > int(self.db.get('GENESIS_NUMBER')) + 1:
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
            head_cp_block = self.get_block(self.checkpoint_head_hash) if self.checkpoint_head_hash else fork_cp_block
            while(fork_cp_block.header.number > head_cp_block.header.number):
                fork_cp_block = self.get_prev_checkpoint_block(fork_cp_block)
            # Replace the head only if the fork block is a child of the head checkpoint
            if (head_cp_block.hash == fork_cp_block.hash and block_score > self.get_score(self.head)) or block.hash == self.checkpoint_head_hash:
                print('REPLACE HEAD')
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
        blk_txhashes = {tx.hash: True for tx in block.transactions}
        self.add_child(block)
        self.db.put('head_hash', self.head_hash)
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

    @property
    def config(self):
        return self.env.config
