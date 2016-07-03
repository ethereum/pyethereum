import os
import time
from ethereum import utils
from ethereum import pruning_trie as trie
from ethereum.refcount_db import RefcountDB
from ethereum.db import OverlayDB
from ethereum.utils import to_string, is_string
from ethereum import parse_genesis_declaration
from ethereum.state_transition import apply_block, initialize, \
    finalize, apply_transaction, mk_receipt_sha, mk_transaction_sha
import rlp
from rlp.utils import encode_hex
from ethereum import blocks
from ethereum import processblock
from ethereum.exceptions import VerificationFailed, InvalidTransaction
from ethereum.slogging import get_logger
from ethereum.config import Env
from ethereum.state import State
from ethereum.block import Block
import time
import random
import json
log = get_logger('eth.chain')


class Chain(object):
    def __init__(self, genesis=None, env=Env(), coinbase=b'\x00' * 20):
        self.env = env
        # Initialize the state
        if 'head_hash' in self.db:
            block = rlp.decode(self.db.get(self.db.get('head_hash')), Block)
            self.state = parse_genesis_declaration.mk_poststate_of_block(block, self.env)
            print 'Initializing chain from saved head, #%d (%s)' % (block.header.number, encode_hex(block.header.hash[:8]))
        elif genesis is None:
            raise Exception("Need genesis decl!")
        elif isinstance(genesis, State):
            self.state = genesis
            print 'Initializing chain from provided state'
        elif "extraData" in genesis:
            self.state = parse_genesis_declaration.state_from_genesis_declaration(genesis, self.env)
            print 'Initializing chain from provided genesis declaration'
        elif "prev_headers" in genesis:
            self.state = State.from_snapshot(genesis, self.env)
            print 'Initializing chain from provided state snapshot, %d (%s)' % \
                (self.state.block_number, encode_hex(self.state.prev_headers[0].hash[:8]))
        else:
            self.state = parse_genesis_declaration.mk_basic_state(genesis, {
                "number": 0,
                "gas_limit": 4712388,
                "timestamp": 1467446877,
                "difficulty": 2**25,
                "hash": '\x00' * 32
            }, env)
            print 'Initializing chain from new state based on alloc'
        self.head_hash = self.state.prev_headers[0].hash
        self.db.put('GENESIS_NUMBER', str(self.state.block_number))
        self.transaction_queue = []
        self.min_gasprice = 5*10**9
        self.coinbase = coinbase
        self.extra_data = 'moo ha ha says the laughing cow.'
        self.time_queue = []
        self.parent_queue = {}

    def get_parent(self, block):
        if block.header.number == int(self.db.get('GENESIS_NUMBER')):
            return None
        return rlp.decode(self.db.get(block.header.prevhash), Block)

    def get_block(self, blockhash):
        try:
            return rlp.decode(self.db.get(blockhash), Block)
        except:
            return None

    def add_child(self, child):
        try:
            existing = self.db.get('child:'+child.header.prevhash)
        except:
            existing = ''
        self.db.put('child:'+child.header.prevhash, existing + child.header.hash)

    def get_blockhash_by_number(self, number):
        try:
            return self.db.get('block:'+str(number))
        except:
            return None

    def get_child_hashes(self, blockhash):
        o = []
        try:
            data = self.db.get('child:'+blockhash)
            for i in range(0, len(data), 32):
                o.append(data[i:i+32])
            return o
        except:
            return []

    def get_score(self, block):
        KEY = 'score:'+block.header.hash
        if key not in self.db:
            parent_score = self.get_score(block.parent)
            self.db.put(key, str(parent_score + block.difficulty + random.randrange(10)))
        return int(self.db.get(key))

    def process_time_queue(self):
        now = int(time.time())
        while len(self.time_queue) and self.time_queue[0].timestamp <= now:
            self.add_block(self.time_queue.pop())

    def process_parent_queue(self):
        for parent_hash, blocks in self.parent_queue:
            if parent_hash in self.db:
                for block in blocks:
                    self.add_block(block)
                del self.parent_queue[parent_hash]

    def add_block(self, block):
        now = int(time.time())
        if block.header.timestamp > now:
            i = 0
            while i < len(self.time_queue) and block.timestamp > self.time_queue[i].timestamp:
                i += 1
            self.time_queue.insert(i, block)
            print 'Block received too early. Delaying for now'
            return False
        if block.header.prevhash == self.head_hash:
            try:
                apply_block(self.state, block)
            except Exception, e:
                print 'Block %s with parent %s invalid' % (encode_hex(block.header.hash), encode_hex(block.header.prevhash))
                print e
                return False
            self.db.put(block.header.hash, rlp.encode(block))
            self.db.put('block:'+str(block.header.number), block.header.hash)
            self.head_hash = block.header.hash
        elif block.header.prevhash in self.env.db:
            pre_state = parse_genesis_declaration.mk_poststate_of_block(self.get_parent(block), self.env)
            try:
                apply_block(pre_state, block)
            except:
                print 'Block %s with parent %s invalid' % (encode_hex(block.hash), encode_hex(block.prevhash))
                return False
            block_score = self.get_score(block)
            # Replace the head
            if block_score > int(self.db.get('score:'+ self.head_hash)):
                b = block
                while b.header.number >= int(self.db.get('GENESIS_NUMBER')):
                    if self.db.get('block:'+str(b.header.number)) == b.header.hash:
                        break
                    self.db.put('block:'+str(b.header.number), b.header.hash)
                    b = self.get_parent(b)
                self.head_hash = block.header.hash
        else:
            if block.header.prevhash not in self.parent_queue:
                self.parent_queue[block.header.prevhash] = []
            self.parent_queue[block.header.prevhash].append(block)
            print 'No parent found. Delaying for now'
            return False
        blk_txhashes = {tx.hash:True for tx in block.transactions}
        self.transaction_queue = [x for x in self.transaction_queue if x.hash in blk_txhashes]
        self.add_child(block)
        self.db.commit()
        self.db.put('head_hash', self.head_hash)
        print 'Adding block %d (%s) with %d txs and %d gas' % \
            (block.header.number, encode_hex(block.header.hash[:8]),
             len(block.transactions), block.header.gas_used)
        return True

    def add_transaction(self, tx):
        if tx.gasprice >= self.min_gasprice:
            i = 0
            while i < len(self.transaction_queue) and tx.gasprice < self.transaction_queue[i]:
                i += i
            self.transaction_queue.insert(i, tx)
            print 'Added transaction to queue'
        else:
            print 'Gasprice too low!'

    def get_transaction(self, gaslimit, excluded={}):
        i = 0
        while i < len(self.transaction_queue) and (self.transaction_queue[i].hash in excluded or
                                                   self.transaction_queue[i].startgas > gaslimit):
            i += 1
        return self.transaction_queue[i] if i < len(self.transaction_queue) else None

    def make_head_candidate(self):
        # clone the state so we can play with it without affecting the original
        temp_state = parse_genesis_declaration.state_from_snapshot(parse_genesis_declaration.to_snapshot(state, root_only=True), self.env)
        blk = Block()
        now = int(time.time())
        blk.header.number = temp_state.block_number + 1
        blk.header.difficulty = state_transition.calc_difficulty(temp_state.prev_headers[0], now, self.env.config)
        blk.header.gas_limit = state_transition.calc_gaslimit(temp_state.prev_headers[0], self.env.config)
        blk.header.coinbase = self.coinbase
        blk.header.timestamp = now
        blk.header.extra_data = self.extra_data
        blk.header.prevhash = temp_state.prev_headers[0].hash
        blk.header.bloom = 0
        blk.transactions = []
        blk.uncles = []
        receipts = []
        initialize(temp_state, blk)
        # Add transactions (highest fee first formula)
        excluded = {}
        while 1:
            tx = self.get_transaction(temp_state.gas_limit - temp_state.gas_used)
            if tx is None:
                break
            try:
                success, gas, logs = apply_transaction(temp_state, tx)
                if temp_state.block_number >= self.config["METROPOLIS_FORK_BLKNUM"]:
                    r = Receipt('\x00' * 32, temp_state.gas_used, logs)
                else:
                    r = Receipt(temp_state.trie.root_hash, temp_state.gas_used, logs)
                blk.transactions.append(tx)
                receipts.append(r)
                temp_state.bloom |= r.bloom  # int
            except:
                pass
            excluded[tx.hash] = True
        # Add uncles
        uncles = []
        ineligible = {}
        for h, uncles in temp_state.recent_uncles:
            for u in uncles:
                ineligible[u.hash] = True
        for i in range(1, min(6, len(temp_state.prev_headers))):
            child_hashes = self.get_child_hashes(temp_state[i].hash)
            for c in child_hashes:
                if c not in ineligible and len(uncles) < 2:
                    uncles.append(self.get_block(c).header)
            if len(uncles) == 2:
                break
        blk.uncles = uncles
        finalize(temp_state, blk)
        blk.receipts_root = mk_receipt_sha(receipts)
        blk.receipts_root = mk_transaction_sha(blk.transactions)
        temp_state.commit()
        blk.state_root = temp_state.trie.root_hash
        blk.bloom = temp_state.bloom
        return blk


    @property
    def db(self):
        return self.env.db
