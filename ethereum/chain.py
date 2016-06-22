import os
import time
from ethereum import utils
from ethereum import pruning_trie as trie
from ethereum.refcount_db import RefcountDB
from ethereum.db import OverlayDB
from ethereum.utils import to_string, is_string
import rlp
from rlp.utils import encode_hex
from ethereum import blocks
from ethereum import processblock
from ethereum.exceptions import VerificationFailed, InvalidTransaction
from ethereum.slogging import get_logger
from ethereum.config import Env
log = get_logger('eth.chain')


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

    def __init__(self, env, index_transactions=True):
        assert isinstance(env, Env)
        self.env = env
        self.db = env.db
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
            if blk.number > 0:
                self.db.put_temporarily(self._block_by_number_key(blk.number), blk.hash)
            else:
                self.db.put(self._block_by_number_key(blk.number), blk.hash)
            self.db.commit_refcount_changes(blk.number)
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
        for i, tx in enumerate(blk.get_transactions()):
            self.db.put_temporarily(tx.hash, rlp.encode([blk.hash, i]))
        self.db.commit_refcount_changes(blk.number)

    def get_transaction(self, txhash):
        "return (tx, block, index)"
        blockhash, tx_num_enc = rlp.decode(self.db.get(txhash))
        blk = rlp.decode(self.db.get(blockhash), blocks.Block, env=self.env)
        num = utils.decode_int(tx_num_enc)
        tx_data = blk.get_transaction(num)
        return tx_data, blk, num

    # children ##############

    def _child_db_key(self, blk_hash):
        return b'ci:' + blk_hash

    def add_child(self, parent_hash, child_hash):
        # only efficient for few children per block
        children = list(set(self.get_children(parent_hash) + [child_hash]))
        assert children.count(child_hash) == 1
        self.db.put_temporarily(self._child_db_key(parent_hash), rlp.encode(children))

    def get_children(self, blk_hash):
        "returns block hashes"
        key = self._child_db_key(blk_hash)
        if key in self.db:
            return rlp.decode(self.db.get(key))
        return []


class Chain(object):

    """
    Manages the chain and requests to it.

    :ivar head_candidate: the block which if mined by our miner would become
                          the new head
    """
    head_candidate = None

    def __init__(self, env, genesis=None, new_head_cb=None, coinbase=b'\x00' * 20):
        assert isinstance(env, Env)
        self.env = env
        self.db = self.blockchain = env.db
        self.new_head_cb = new_head_cb
        self.index = Index(self.env)
        self._coinbase = coinbase
        if 'HEAD' not in self.db:
            self._initialize_blockchain(genesis)
        log.debug('chain @', head_hash=self.head)
        self.genesis = self.get(self.index.get_block_by_number(0))
        log.debug('got genesis', nonce=encode_hex(self.genesis.nonce),
                  difficulty=self.genesis.difficulty)
        self._update_head_candidate()

    def _initialize_blockchain(self, genesis=None):
        log.info('Initializing new chain')
        if not genesis:
            genesis = blocks.genesis(self.env)
            log.info('new genesis', genesis_hash=genesis, difficulty=genesis.difficulty)
            self.index.add_block(genesis)
        self._store_block(genesis)
        assert genesis == blocks.get_block(self.env, genesis.hash)
        self._update_head(genesis)
        assert genesis.hash in self
        self.commit()

    @property
    def coinbase(self):
        assert self.head_candidate.coinbase == self._coinbase
        return self._coinbase

    @coinbase.setter
    def coinbase(self, value):
        self._coinbase = value
        # block reward goes to different address => redo finalization of head candidate
        self._update_head(self.head)

    @property
    def head(self):
        if self.blockchain is None or 'HEAD' not in self.blockchain:
            self._initialize_blockchain()
        ptr = self.blockchain.get('HEAD')
        return blocks.get_block(self.env, ptr)

    def _update_head(self, block, forward_pending_transactions=True):
        log.debug('updating head')
        if not block.is_genesis():
            #assert self.head.chain_difficulty() < block.chain_difficulty()
            if block.get_parent() != self.head:
                log.debug('New Head is on a different branch',
                          head_hash=block, old_head_hash=self.head)
        # Some temporary auditing to make sure pruning is working well
        if block.number > 0 and block.number % 500 == 0 and isinstance(self.db, RefcountDB):
            trie.proof.push(trie.RECORDING)
            block.to_dict(with_state=True)
            n = trie.proof.get_nodelist()
            trie.proof.pop()
            # log.debug('State size: %d\n' % sum([(len(rlp.encode(a)) + 32) for a in n]))
        # Fork detected, revert death row and change logs
        if block.number > 0:
            b = block.get_parent()
            h = self.head
            b_children = []
            if b.hash != h.hash:
                log.warn('reverting')
                while h.number > b.number:
                    h.state.db.revert_refcount_changes(h.number)
                    h = h.get_parent()
                while b.number > h.number:
                    b_children.append(b)
                    b = b.get_parent()
                while b.hash != h.hash:
                    h.state.db.revert_refcount_changes(h.number)
                    h = h.get_parent()
                    b_children.append(b)
                    b = b.get_parent()
                for bc in b_children:
                    processblock.verify(bc, bc.get_parent())
        self.blockchain.put('HEAD', block.hash)
        assert self.blockchain.get('HEAD') == block.hash
        self.index.update_blocknumbers(self.head)
        assert self.head == block
        log.debug('set new head', head=self.head)
        self._update_head_candidate(forward_pending_transactions)
        if self.new_head_cb and not block.is_genesis():
            self.new_head_cb(block)

    def _update_head_candidate(self, forward_pending_transactions=True):
        "after new head is set"
        log.debug('updating head candidate', head=self.head)
        # collect uncles
        blk = self.head  # parent of the block we are collecting uncles for
        uncles = set(u.header for u in self.get_brothers(blk))
        for i in range(self.env.config['MAX_UNCLE_DEPTH'] + 2):
            for u in blk.uncles:
                assert isinstance(u, blocks.BlockHeader)
                uncles.discard(u)
            if blk.has_parent():
                blk = blk.get_parent()
        assert not uncles or max(u.number for u in uncles) <= self.head.number
        uncles = list(uncles)[:self.env.config['MAX_UNCLES']]

        # create block
        ts = max(int(time.time()), self.head.timestamp + 1)
        _env = Env(OverlayDB(self.head.db), self.env.config, self.env.global_config)
        head_candidate = blocks.Block.init_from_parent(self.head, coinbase=self._coinbase,
                                                       timestamp=ts, uncles=uncles, env=_env)
        assert head_candidate.validate_uncles()

        self.pre_finalize_state_root = head_candidate.state_root
        head_candidate.finalize()

        # add transactions from previous head candidate
        old_head_candidate = self.head_candidate
        self.head_candidate = head_candidate
        if old_head_candidate is not None:
            tx_hashes = self.head.get_transaction_hashes()
            pending = [tx for tx in old_head_candidate.get_transactions()
                       if tx.hash not in tx_hashes]
            if pending:
                if forward_pending_transactions:
                    log.debug('forwarding pending transactions', num=len(pending))
                    for tx in pending:
                        self.add_transaction(tx)
                else:
                    log.debug('discarding pending transactions', num=len(pending))

    def get_uncles(self, block):
        """Return the uncles of `block`."""
        if not block.has_parent():
            return []
        else:
            return self.get_brothers(block.get_parent())

    def get_brothers(self, block):
        """Return the uncles of the hypothetical child of `block`."""
        o = []
        i = 0
        while block.has_parent() and i < self.env.config['MAX_UNCLE_DEPTH']:
            parent = block.get_parent()
            o.extend([u for u in self.get_children(parent) if u != block])
            block = block.get_parent()
            i += 1
        return o

    def get(self, blockhash):
        assert is_string(blockhash)
        assert len(blockhash) == 32
        return blocks.get_block(self.env, blockhash)

    def get_bloom(self, blockhash):
        h = rlp.decode(rlp.descend(self.db.get(blockhash), 0, 6))
        return utils.big_endian_to_int(h)

    def has_block(self, blockhash):
        assert is_string(blockhash)
        assert len(blockhash) == 32
        return blockhash in self.blockchain

    def __contains__(self, blockhash):
        return self.has_block(blockhash)

    def _store_block(self, block):
        if block.number > 0:
            self.blockchain.put_temporarily(block.hash, rlp.encode(block))
        else:
            self.blockchain.put(block.hash, rlp.encode(block))

    def commit(self):
        self.blockchain.commit()

    def add_block(self, block, forward_pending_transactions=True):
        "returns True if block was added sucessfully"
        _log = log.bind(block_hash=block)
        # make sure we know the parent
        if not block.has_parent() and not block.is_genesis():
            _log.debug('missing parent')
            return False

        if not block.validate_uncles():
            _log.debug('invalid uncles')
            return False

        elif not block.header.check_pow() and not block.is_genesis():
            _log.debug('invalid nonce')
            return False

        if block.has_parent():
            try:
                processblock.verify(block, block.get_parent())
            except VerificationFailed as e:
                _log.critical('VERIFICATION FAILED', error=e)
                f = os.path.join(utils.data_dir, 'badblock.log')
                open(f, 'w').write(to_string(block.hex_serialize()))
                return False

        if block.number < self.head.number:
            _log.debug("older than head", head_hash=self.head)
            # Q: Should we have any limitations on adding blocks?

        self.index.add_block(block)
        self._store_block(block)

        # set to head if this makes the longest chain w/ most work for that number
        if block.chain_difficulty() > self.head.chain_difficulty():
            _log.debug('new head', num_tx=block.num_transactions())
            self._update_head(block, forward_pending_transactions)
        elif block.number > self.head.number:
            _log.warn('has higher blk number than head but lower chain_difficulty',
                      head_hash=self.head, block_difficulty=block.chain_difficulty(),
                      head_difficulty=self.head.chain_difficulty())
        block.transactions.clear_all()
        block.receipts.clear_all()
        block.state.db.commit_refcount_changes(block.number)
        block.state.db.cleanup(block.number)
        self.commit()  # batch commits all changes that came with the new block
        return True

    def get_children(self, block):
        return [self.get(c) for c in self.index.get_children(block.hash)]

    def add_transaction(self, transaction):
        """Add a transaction to the :attr:`head_candidate` block.

        If the transaction is invalid, the block will not be changed.

        :returns: `True` is the transaction was successfully added or `False`
                  if the transaction was invalid
        """
        assert self.head_candidate is not None
        head_candidate = self.head_candidate
        log.debug('add tx', num_txs=self.num_transactions(), tx=transaction, on=head_candidate)
        if self.head_candidate.includes_transaction(transaction.hash):
            log.debug('known tx')
            return
        old_state_root = head_candidate.state_root
        # revert finalization
        head_candidate.state_root = self.pre_finalize_state_root
        try:
            success, output = processblock.apply_transaction(head_candidate, transaction)
        except InvalidTransaction as e:
            # if unsuccessful the prerequisites were not fullfilled
            # and the tx is invalid, state must not have changed
            log.debug('invalid tx', error=e)
            head_candidate.state_root = old_state_root  # reset
            return False

        log.debug('valid tx')

        # we might have a new head_candidate (due to ctx switches in pyethapp)
        if self.head_candidate != head_candidate:
            log.debug('head_candidate changed during validation, trying again')
            return self.add_transaction(transaction)

        self.pre_finalize_state_root = head_candidate.state_root
        head_candidate.finalize()
        log.debug('tx applied', result=output)
        assert old_state_root != head_candidate.state_root
        return True

    def get_transactions(self):
        """Get a list of new transactions not yet included in a mined block
        but known to the chain.
        """
        if self.head_candidate:
            log.debug('get_transactions called', on=self.head_candidate)
            return self.head_candidate.get_transactions()
        else:
            return []

    def num_transactions(self):
        if self.head_candidate:
            return self.head_candidate.transaction_count
        else:
            return 0

    def get_chain(self, start='', count=10):
        "return 'count' blocks starting from head or start"
        log.debug("get_chain", start=encode_hex(start), count=count)
        blocks = []
        block = self.head
        if start:
            if start not in self.index.db:
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
        log.debug("get_descendants", block_hash=block)
        assert block.hash in self
        block_numbers = list(range(block.number + 1, min(self.head.number + 1,
                                                         block.number + count + 1)))
        return [self.get(self.index.get_block_by_number(n)) for n in block_numbers]
