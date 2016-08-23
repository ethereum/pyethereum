import time
from ethereum import utils
from ethereum.utils import parse_as_bin, big_endian_to_int
from ethereum import parse_genesis_declaration
from ethereum.state_transition import apply_block, initialize, \
    pre_seal_finalize, post_seal_finalize, apply_transaction, mk_receipt_sha, \
    mk_transaction_sha, calc_difficulty, Receipt, mk_receipt, \
    update_block_env_variables, validate_uncles, validate_block_header
import rlp
from rlp.utils import encode_hex
from ethereum.exceptions import InvalidNonce, InsufficientStartGas, UnsignedTransaction, \
    BlockGasLimitReached, InsufficientBalance
from ethereum.slogging import get_logger
from ethereum.config import Env
from ethereum.state import State, dict_to_prev_header
from ethereum.block import Block, BlockHeader, FakeHeader, BLANK_UNCLES_HASH
import random
import json
log = get_logger('eth.chain')


class Chain(object):

    def __init__(self, genesis=None, env=None, coinbase=b'\x00' * 20, **kwargs):
        self.env = env or Env()
        # Initialize the state
        if 'head_hash' in self.db:
            self.state = self.mk_poststate_of_blockhash(self.db.get('head_hash'))
            print 'Initializing chain from saved head, #%d (%s)' % \
                (self.state.prev_headers[0].number, encode_hex(self.state.prev_headers[0].hash))
        elif genesis is None:
            raise Exception("Need genesis decl!")
        elif isinstance(genesis, State):
            self.state = genesis
            print 'Initializing chain from provided state'
        elif "extraData" in genesis:
            self.state = parse_genesis_declaration.state_from_genesis_declaration(
                genesis, self.env)
            print 'Initializing chain from provided genesis declaration'
        elif "prev_headers" in genesis:
            self.state = State.from_snapshot(genesis, self.env)
            print 'Initializing chain from provided state snapshot, %d (%s)' % \
                (self.state.block_number, encode_hex(self.state.prev_headers[0].hash[:8]))
        else:
            print 'Initializing chain from new state based on alloc'
            self.state = parse_genesis_declaration.mk_basic_state(genesis, {
                "number": kwargs.get('number', 0),
                "gas_limit": kwargs.get('gas_limit', 4712388),
                "gas_used": kwargs.get('gas_used', 0),
                "timestamp": kwargs.get('timestamp', 1467446877),
                "difficulty": kwargs.get('difficulty', 2**25),
                "hash": kwargs.get('prevhash', '00' * 32),
                "uncles_hash": kwargs.get('uncles_hash', '0x' + encode_hex(BLANK_UNCLES_HASH))
            }, self.env)
        self.head_hash = self.state.prev_headers[0].hash
        self.genesis = Block(self.state.prev_headers[0], [], [])
        self.db.put('state:'+self.head_hash, self.state.trie.root_hash)
        self.db.put('GENESIS_NUMBER', str(self.state.block_number))
        self.db.put('GENESIS_HASH', str(self.state.prev_headers[0].hash))
        assert self.state.block_number == self.state.prev_headers[0].number
        self.db.put('score:' + self.state.prev_headers[0].hash, "0")
        self.db.put('GENESIS_STATE', json.dumps(self.state.to_snapshot()))
        self.db.put(self.head_hash, 'GENESIS')
        self.min_gasprice = kwargs.get('min_gasprice', 5 * 10**9)
        self.coinbase = coinbase
        self.extra_data = 'moo ha ha says the laughing cow.'
        self.time_queue = []
        self.parent_queue = {}

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

    def mk_poststate_of_blockhash(self, blockhash):
        print 'Making poststate from blockhash'
        if blockhash not in self.db:
            raise Exception("Block hash %s not found" % encode_hex(blockhash))
        if self.db.get(blockhash) == 'GENESIS':
            return State.from_snapshot(json.loads(self.db.get('GENESIS_STATE')), self.env)
        state = State(env=self.env)
        state.trie.root_hash = self.db.get('state:'+blockhash)
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
                    if blknum >= state.block_number - state.config['MAX_UNCLE_DEPTH']:
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
            return rlp.decode(self.db.get(blockhash), Block)
        except:
            return None

    # Add a record allowing you to later look up the provided block's
    # parent hash and see that it is one of its children
    def add_child(self, child):
        try:
            existing = self.db.get('child:' + child.header.prevhash)
        except:
            existing = ''
        existing_hashes = []
        for i in range(0, len(existing), 32):
            existing_hashes.append(existing[i: i+32])
        if child.header.hash not in existing_hashes:
            self.db.put('child:' + child.header.prevhash, existing + child.header.hash)

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
            data = self.db.get('child:' + blockhash)
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
        key = 'score:' + block.header.hash
        if key not in self.db:
            try:
                parent_score = self.get_score(self.get_parent(block))
                self.db.put(key, str(parent_score + block.difficulty +
                                     random.randrange(block.difficulty // 10**6 + 1)))
            except:
                return int(self.db.get('score:' + block.prevhash))
        return int(self.db.get(key))

    # These two functions should be called periodically so as to
    # process blocks that were received but laid aside because
    # either the parent was missing or they were received
    # too early
    def process_time_queue(self):
        now = self.time()
        i = 0
        while i < len(self.time_queue) and self.time_queue[i].timestamp <= now:
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

    def time(self):
        return int(time.time())

    # Call upon receiving a block
    def add_block(self, block):
        now = self.time()
        if block.header.timestamp > now:
            i = 0
            while i < len(self.time_queue) and block.timestamp > self.time_queue[i].timestamp:
                i += 1
            self.time_queue.insert(i, block)
            log.info('Block received too early. Delaying for %d seconds' % (block.header.timestamp - now))
            return False
        if block.header.prevhash == self.head_hash:
            log.info('Adding to head', head=encode_hex(block.header.prevhash))
            try:
                apply_block(self.state, block)
            except (KeyError, ValueError), e:  # FIXME add relevant exceptions here
                log.info('Block %s with parent %s invalid, reason: %s' % (encode_hex(block.header.hash), encode_hex(block.header.prevhash), e))
                return False
            self.db.put('block:' + str(block.header.number), block.header.hash)
            self.db.put('state:' + block.header.hash, self.state.trie.root_hash)
            self.head_hash = block.header.hash
            for i, tx in enumerate(block.transactions):
                self.db.put('txindex:' + tx.hash, rlp.encode([block.number, i]))
        elif block.header.prevhash in self.env.db:
            log.info('Receiving block not on head, adding to secondary post state',
                     prevhash=encode_hex(block.header.prevhash))
            temp_state = self.mk_poststate_of_blockhash(block.header.prevhash)
            try:
                apply_block(temp_state, block)
            except (KeyError, ValueError), e:  # FIXME add relevant exceptions here
                log.info('Block %s with parent %s invalid, reason: %s' % (encode_hex(block.header.hash), encode_hex(block.header.prevhash), e))
                return False
            self.db.put('state:' + block.header.hash, temp_state.trie.root_hash)
            block_score = self.get_score(block)
            # Replace the head
            if block_score > self.get_score(self.head):
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
                for i in xrange(replace_from, 2**63 - 1):
                    log.info('Rewriting height %d' % i)
                    key = 'block:' + str(i)
                    orig_at_height = self.db.get(key) if key in self.db else None
                    if orig_at_height:
                        self.db.delete(key)
                        orig_block_at_height = self.get_block(orig_at_height)
                        for tx in orig_block_at_height.transactions:
                            if 'txindex:' + tx.hash in self.db:
                                self.db.delete('txindex:' + tx.hash)
                    if i in new_chain:
                        new_block_at_height = new_chain[i]
                        self.db.put(key, new_block_at_height.header.hash)
                        for i, tx in enumerate(new_block_at_height.transactions):
                            self.db.put('txindex:' + tx.hash,
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

    def get_chain(self, frm=None, to=2**63 - 1):
        if frm is None:
            frm = int(self.db.get('GENESIS_NUMBER')) + 1
        chain = []
        for i in xrange(frm, to):
            h = self.get_blockhash_by_number(i)
            if not h:
                return chain
            chain.append(self.get_block(h))

    # Recover transaction and the block that contains it
    def get_transaction(self, tx):
        if not isinstance(tx, (str, bytes)):
            tx = tx.hash
        if 'txindex:' + tx in self.db:
            data = rlp.decode(self.db.get('txindex:' + tx))
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
