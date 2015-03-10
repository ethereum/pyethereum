import time
import rlp
from rlp.sedes import BigEndianInt, big_endian_int, Binary, binary, CountableList, raw
import trie
import utils
from utils import address, int64, trie_root, hash32
import processblock
from transactions import Transaction
import bloom
import copy
import sys
from repoze.lru import lru_cache
from exceptions import *
from pyethereum.slogging import get_logger
from pyethereum.genesis_allocation import GENESIS_INITIAL_ALLOC
log = get_logger('eth.block')
log_state = get_logger('eth.msg.state')
Log = processblock.Log


# Genesis block difficulty
GENESIS_DIFFICULTY = 2 ** 17
# Genesis block gas limit
GENESIS_GAS_LIMIT = 10 ** 6
# Genesis block prevhash, coinbase, nonce
GENESIS_PREVHASH = '\00' * 32
GENESIS_COINBASE = ("0" * 40).decode('hex')
GENESIS_NONCE = utils.sha3(chr(42))
# Minimum gas limit
MIN_GAS_LIMIT = 125000
# Gas limit adjustment algo:
# block.gas_limit = block.parent.gas_limit * 1023/1024 +
#                   (block.gas_used * 6 / 5) / 1024
GASLIMIT_EMA_FACTOR = 1024
BLKLIM_FACTOR_NOM = 6
BLKLIM_FACTOR_DEN = 5
# Block reward
BLOCK_REWARD = 1500 * utils.denoms.finney
# GHOST constants
UNCLE_REWARD = 15 * BLOCK_REWARD / 16
NEPHEW_REWARD = BLOCK_REWARD / 32
MAX_UNCLE_DEPTH = 6  # max (block.number - uncle.number)
# Difficulty adjustment constants
DIFF_ADJUSTMENT_CUTOFF = 5
BLOCK_DIFF_FACTOR = 1024


class Account(rlp.Serializable):
    """An Ethereum account.

    :ivar nonce: the account's nonce (the number of transactions sent by the
                 account)
    :ivar balance: the account's balance in wei
    :ivar storage: the root of the account's storage trie
    :ivar code_hash: the SHA3 hash of the code associated with the account
    :ivar db: the database in which the account's code is stored
    """

    fields = [
        ('nonce', big_endian_int),
        ('balance', big_endian_int),
        ('storage', trie_root),
        ('code_hash', hash32)
    ]

    def __init__(self, nonce, balance, storage, code_hash, db):
        self.db = db
        super(Account, self).__init__(nonce, balance, storage, code_hash)

    @property
    def code(self):
        """The EVM code of the account.

        This property will be read from or written to the db at each access,
        with :ivar:`code_hash` used as key.
        """
        return self.db.get(self.code_hash)

    @code.setter
    def code(self, value):
        self.code_hash = utils.sha3(value)
        self.db.put(self.code_hash, value)

    @classmethod
    def blank_account(cls, db):
        """Create a blank account

        The returned account will have zero nonce and balance, a blank storage
        trie and empty code.

        :param db: the db in which the account will store its code.
        """
        code_hash = utils.sha3('')
        db.put(code_hash, '')
        return cls(0, 0, trie.BLANK_ROOT, code_hash, db)


class Receipt(rlp.Serializable):

    fields = [
        ('state_root', trie_root),
        ('gas_used', big_endian_int),
        ('bloom', int64),
        ('logs', CountableList(processblock.Log))
    ]

    def __init__(self, state_root, gas_used, logs, bloom=None):
        self.state_root = state_root
        self.gas_used = gas_used
        self.logs = logs
        if bloom is not None and bloom != self.bloom:
            raise ValueError("Invalid bloom filter")

    @property
    def bloom(self):
        bloomables = [x.bloomables() for x in self.logs]
        return bloom.bloom_from_list(bloomables)


class BlockHeader(rlp.Serializable):
    """A block header.

    If the block with this header exists as an instance of :class:`Block`, the
    connection can be made explicit by setting :attr:`BlockHeader.block`. Then,
    :attr:`BlockHeader.state_root`, :attr:`BlockHeader.tx_list_root` and
    :attr:`BlockHeader.receipts_root` always refer to the up-to-date value.

    :ivar block: the corresponding block or `None`
    :ivar prevhash: the 32 byte hash of the previous block
    :ivar uncles_hash: the 32 byte hash of the RLP encoded list of uncle
                       headers
    :ivar coinbase: the 20 byte coinbase address
    :ivar state_root: the root of the block's state trie
    :ivar tx_list_root: the root of the block's transaction trie
    :ivar receipts_root: the root of the block's receipts trie
    :ivar bloom: TODO
    :ivar difficulty: the block's difficulty
    :ivar number: the number of ancestors of this block (0 for the genesis
                  block)
    :ivar gas_limit: the block's gas limit
    :ivar gas_used: the total amount of gas used by all transactions in this
                    block
    :ivar timestamp: a UNIX timestamp
    :ivar extra_data: up to 1024 bytes of additional data
    :ivar nonce: a 32 byte nonce constituting a proof-of-work, or the empty
                 string as a placeholder
    """

    fields = [
        ('prevhash', hash32),
        ('uncles_hash', hash32),
        ('coinbase', address),
        ('state_root', trie_root),
        ('tx_list_root', trie_root),
        ('receipts_root', trie_root),
        ('bloom', int64),
        ('difficulty', big_endian_int),
        ('number', big_endian_int),
        ('gas_limit', big_endian_int),
        ('gas_used', big_endian_int),
        ('timestamp', big_endian_int),
        ('extra_data', binary),
        ('nonce', Binary(32, allow_empty=True))
    ]

    def __init__(self,
                 prevhash=GENESIS_PREVHASH,
                 uncles_hash=utils.sha3rlp([]),
                 coinbase=GENESIS_COINBASE,
                 state_root=trie.BLANK_ROOT,
                 tx_list_root=trie.BLANK_ROOT,
                 receipts_root=trie.BLANK_ROOT,
                 bloom=0,
                 difficulty=GENESIS_DIFFICULTY,
                 number=0,
                 gas_limit=GENESIS_GAS_LIMIT,
                 gas_used=0,
                 timestamp=0,
                 extra_data='',
                 nonce=''):
        # at the beginning of a method, locals() is a dict of all arguments
        fields = {k: v for k, v in locals().iteritems() if k != 'self'}
        self.block = None
        super(BlockHeader, self).__init__(**fields)

    @property
    def state_root(self):
        if self.block:
            return self.block.state_root
        else:
            return self._state_root

    @state_root.setter
    def state_root(self, value):
        if self.block:
            self.block.state_root = value
        else:
            self._state_root = value

    @property
    def tx_list_root(self):
        if self.block:
            return self.block.tx_list_root
        else:
            return self._tx_list_root

    @tx_list_root.setter
    def tx_list_root(self, value):
        if self.block:
            self.block.tx_list_root = value
        else:
            self._tx_list_root = value

    @property
    def receipts_root(self):
        if self.block:
            return self.block.receipts_root
        else:
            return self._receipts_root

    @receipts_root.setter
    def receipts_root(self, value):
        if self.block:
            self.block.receipts_root = value
        else:
            self._receipts_root = value

    @property
    def hash(self):
        """The binary block hash"""
        return utils.sha3(rlp.encode(self))

    def hex_hash(self):
        """The hex encoded block hash"""
        return self.hash.encode('hex')

    def check_pow(self, nonce=None):
        """Check if the proof-of-work of the block is valid.

        :param nonce: if given the proof of work function will be evaluated
                      with this nonce instead of the one already present in
                      the header
        :returns: `True` or `False`
        """
        nonce = nonce or self.nonce
        rlp_Hn = rlp.encode(self, BlockHeader.exclude(['nonce']))
        assert len(nonce) == 32
        h = utils.sha3(utils.sha3(rlp_Hn) + nonce)
        return utils.big_endian_to_int(h) < 2 ** 256 / self.difficulty


def mirror_from(source, attributes, only_getters=True):
    """Decorator (factory) for classes that mirror some attributes from an
    instance variable.
    
    :param source: the name of the instance variable to mirror from
    :param attributes: list of attribute names to mirror
    :param setters: if true getters but not setters are created
    """
    def decorator(cls):
        for attribute in attributes:
            def make_gs_etter(source, attribute):
                def getter(self):
                    return getattr(getattr(self, source), attribute)
                def setter(self, value):
                    setattr(getattr(self, source), attribute, value)
                return getter, setter
            getter, setter = make_gs_etter(source, attribute)
            if only_getters:
                setattr(cls, attribute, property(getter)) 
            else:
                setattr(cls, attribute, property(getter, setter)) 
        return cls
    return decorator


@mirror_from('header', [field for field, _ in BlockHeader.fields])
class TransientBlock(rlp.Serializable):
    """A read only, non persistent, not validated representation of a block.

    At initialization all instance variables are copied from the block header
    (e.g. ``transient_block.prevhash`` can be used instead of
    ``transient.block.prevhash``).

    :ivar header: the block's header
    :ivar transaction_list: a list of transactions in the block
    :ivar uncles: a list of uncle headers
    """

    fields = [
        ('header', BlockHeader),
        ('transaction_list', CountableList(Transaction)),
        ('uncles', CountableList(BlockHeader))
    ]

    def __init__(self, header, transaction_list, uncles):
        super(TransientBlock, self).__init__(header, transaction_list, uncles)


    @property
    def hash(self):
        """The binary block hash

        This is equivalent to ``header.hash``.
        """
        return utils.sha3(rlp.encode(self.header))

    def hex_hash(self):
        """The hex encoded block hash.

        This is equivalent to ``header.hex_hash().
        """
        return self.hash.encode('hex')

    def __repr__(self):
        return '<TransientBlock(#%d %s)>' % (self.number,
                                             self.hash.encode('hex')[:8])

    def __structlog__(self):
        return self.hash.encode('hex')


@mirror_from('header', set(field for field, _ in BlockHeader.fields) -
                       set(['state_root', 'receipts_root', 'tx_list_root']),
             only_getters=False)
class Block(rlp.Serializable):
    """A block.

    :param header: the block header (whose instance variables are copied to
                   the block)
    :param transaction_list: a list of transactions (which are replayed if the
                             state given by the header is not known) or `None`
                             to create a non finalized block without any
                             transactions.
    :param uncles: a list of the headers of the uncles of this block
    :param db: the database in which the block's  state, transactions and
               receipts are stored (required)
    :param parent: optional parent which otherwise may have to be loaded from
                   the database for replay
    :param force_replay: if true transactions are replayed even if state is
                         already known
    """

    fields = [
        ('header', BlockHeader),
        ('transaction_list', CountableList(Transaction)),
        ('uncles', CountableList(BlockHeader))
    ]

    def __init__(self, header, transaction_list=[], uncles=[], db=None,
                 parent=None, force_replay=False):
        if not db:
            raise TypeError("No database object given")
        self.db = db
        self.header = header
        self.uncles = uncles

        self.uncles = uncles
        self.suicides = []
        self.logs = []
        self.refunds = 0
        self.reset_cache()
        self.journal = []

        # do some consistency checks on parent if given
        if parent:
            if self.db != parent.db:
                raise ValueError("Parent lives in different database")
            if self.prevhash != parent.header.hash:
                raise ValueError("Block's prevhash and parent's hash do not "
                                 "match")
            if self.number != parent.header.number + 1:
                raise ValueError("Block's number is not the successor of its "
                                 "parent number")
            if self.gas_limit != calc_gaslimit(parent):
                # TODO: do we need to raise an error?
                raise ValueError("Block's gaslimit is inconsistent with its "
                                 "parent's gaslimit")
            if self.difficulty != calc_difficulty(parent, self.timestamp):
                raise ValueError("Block's difficulty is inconsistent with its "
                                 "parent's difficulty")

        if force_replay and transaction_list is None:
            raise ValueError("Cannot replay if no transactions are given")

        self.transactions = trie.Trie(db, trie.BLANK_ROOT)
        self.receipts = trie.Trie(self.db, trie.BLANK_ROOT)
        # replay if state is unknown or it is is explicitly requested
        state_unknown = (header.prevhash != GENESIS_PREVHASH and
                 header.state_root != trie.BLANK_ROOT and  # TODO: correct?
                 (len(header.state_root) != 32 or header.state_root not in db))
        if state_unknown or force_replay:
            if transaction_list is None:
                raise ValueError("Cannot replay if no transactions are given")
            if not parent:
                parent = self.get_parent()
            self.state = trie.Trie(db, parent.state_root)
            self.transaction_count = 0
            self.gas_used = 0
            # replay
            for tx in transaction_list:
                success, output = processblock.apply_transaction(self, tx)
            self.finalize()
            if self.gas_used != header.gas_used:
                raise ValueError("Gas used does not match")
            if self.state_root != header.state_root:
                raise ValueError("State root hash does not match")
            if self.receipts_root != header.receipts_root:
                raise ValueError("Receipts root hash does not match")
        else:
            # trust the state root in the header
            self.state = trie.Trie(self.db, header._state_root)
            self.transaction_count = 0
            self.gas_used = header.gas_used
            if transaction_list:
                for tx in transaction_list:
                    self.add_transaction_to_list(tx)
            # receipts trie populated by add_transaction_to_list is incorrect
            # as it doesn't know intermediate states, so reset it
            self.receipts = trie.Trie(self.db, header.receipts_root)
        if self.transactions.root_hash != header.tx_list_root:
            raise ValueError("Transaction list root hash does not match")

        # from now on, trie roots are stored in block instead of header
        header.block = self

        if self.number > 0:
            self.ancestors = [self]
        else:
            self.ancestors = [self] + [None] * 256

        # Basic consistency verifications
        if not self.check_fields():
            raise ValueError("Block is invalid")
        if len(self.header.extra_data) > 1024:
            raise ValueError("Extra data cannot exceed 1024 bytes")
        if self.header.coinbase == '':
            raise ValueError("Coinbase cannot be empty address")
        if not self.state.root_hash_valid():
            raise ValueError("State Merkle root of block %r not found in "
                             "database" % self)
        if not self.is_genesis() and self.nonce and not self.header.check_pow():
            raise ValueError("PoW check failed")

        # make sure we are all on the same db
        assert self.state.db.db == self.transactions.db.db  == self.db.db

    @classmethod
    def init_from_header(cls, header_rlp, db):
        """Create a block without specifying transactions or uncles.

        :param header_rlp: the RLP encoded block header
        :param db: the database for the block
        """
        header = rlp.decode(rlpdata, BlockHeader, db=db)
        return cls(header, None, [], db=db)

    @classmethod
    def init_from_parent(cls, parent, coinbase, extra_data='',
                         timestamp=int(time.time()), uncles=[]):
        """Create a new block based on a parent block.

        The block will not include any transactions, will not be finalized and
        will not have a valid nonce.

        :param parent: the parent block
        :param coinbase: the 20 bytes coinbase address
        :param extra_data: up to 1024 bytes of additional data
        :param timestamp: a UNIX timestamp
        :param uncles: a list of the headers of the uncles of this block
        """
        header = BlockHeader(prevhash=parent.hash,
                             uncles_hash=utils.sha3(rlp.encode(uncles)),
                             coinbase=coinbase,
                             state_root=parent.state_root,
                             tx_list_root=trie.BLANK_ROOT,
                             receipts_root=trie.BLANK_ROOT,
                             bloom=0,
                             difficulty=calc_difficulty(parent, timestamp),
                             number=parent.number + 1,
                             gas_limit=calc_gaslimit(parent),
                             gas_used=0,
                             timestamp=timestamp,
                             extra_data=extra_data,
                             nonce='')
        block = Block(header, None, uncles, db=parent.db, parent=parent)
        block.ancestors += parent.ancestors
        return block

    @classmethod
    def init_from_transient(cls, transient_block, db):
        """Create a new block based on a :class:`TransientBlock`.

        :param transient_block: a :class:`TransientBlock`
        :param db: the database for the block
        """
        return Block(transient_block.header, transient_block.transaction_list,
                     transient_block.uncles, db=db)

    def check_fields(self):
        """Check that the values of all fields are well formed."""
        # serialize and deserialize and check that the values didn't change
        l = Block.serialize(self)
        return rlp.decode(rlp.encode(l)) == l

    @property
    def hash(self):
        """The binary block hash

        This is equivalent to ``header.hash``.
        """
        return utils.sha3(rlp.encode(self.header))

    def hex_hash(self):
        """The hex encoded block hash.

        This is equivalent to ``header.hex_hash().
        """
        return self.hash.encode('hex')

    @property
    def tx_list_root(self):
        return self.transactions.root_hash

    @tx_list_root.setter
    def tx_list_root(self, value):
        self.transactions = trie.Trie(self.db, value)

    @property
    def receipts_root(self):
        return self.receipts.root_hash

    @receipts_root.setter
    def receipts_root(self, value):
        self.receipts = trie.Trie(self.db, value)

    @property
    def state_root(self):
        self.commit_state()
        return self.state.root_hash

    @state_root.setter
    def state_root(self, value):
        self.state = trie.Trie(self.db, value)
        self.reset_cache()

    @property
    def transaction_list(self):
        txs = []
        for i in range(self.transaction_count):
            txs.append(self.get_transaction(i))
        return txs

    def validate_uncles(self):
        """Validate the uncles of this block.

        Valid uncles

            * have a valid PoW,
            * are neither a sibling nor the parent of this block,
            * are a child of one of the previous 6 ancestors of this block and
            * are not already included as uncles in the previous 6 blocks.
        """
        if utils.sha3(rlp.encode(self.uncles)) != self.uncles_hash:
            return False
        # Check uncle validity
        ancestor_chain = [a for a in self.get_ancestor_list(MAX_UNCLE_DEPTH + 1) if a]
        ineligible = []
        # Uncles of this block cannot be direct ancestors and cannot also
        # be uncles included 1-6 blocks ago
        for ancestor in ancestor_chain[1:]:
            ineligible.extend(ancestor.uncles)
        ineligible.extend([b.header for b in ancestor_chain])
        eligible_ancestor_hashes = [x.hash for x in ancestor_chain[2:]]
        for uncle in self.uncles:
            if not uncle.check_pow():
                return False
            if uncle.prevhash not in eligible_ancestor_hashes:
                log.error("Uncle does not have a valid ancestor", block=self)
                return False
            if uncle in ineligible:
                log.error("Duplicate uncle", block=self,
                          uncle=utils.sha3(rlp.encode(uncle)).encode('hex'))
                return False
            ineligible.append(uncle)
        return True

    def get_ancestor_list(self, n):
        """Return `n` ancestors of this block.

        The result will also be memoized in :attr:`ancestor_list`.

        :returns: a list [self, p(self), p(p(self)), ..., p^n(self)]
        """
        # TODO: why 256 Nones?
        if self.number == 0:
            self.ancestors = [self] + [None] * 256
        elif len(self.ancestors) <= n:
            first_unknown = self.ancestors[-1].get_parent()
            missing = first_unknown.get_ancestor_list(n - len(self.ancestors))
            self.ancestors += missing
        return self.ancestors[:n + 1]

    def get_ancestor(self, n):
        """Get the `n`th ancestor of this block."""
        return self.get_ancestor_list(n)[-1]

    def is_genesis(self):
        """`True` if this block is the genesis block, otherwise `False`."""
        return all((self.prevhash == GENESIS_PREVHASH,
                    self.nonce == GENESIS_NONCE))

    def get_acct(self, address):
        """Get the account with the given address."""
        if len(address) == 40:
            address = address.decode('hex')
        assert len(address) == 20 or len(address) == 0
        rlpdata = self.state.get(address)
        if rlpdata != trie.BLANK_NODE:
            acct = rlp.decode(rlpdata, Account, db=self.db)
        else:
            acct = Account.blank_account(self.db)
        return acct

    def _get_acct_item(self, address, param):
        """Get a specific parameter of a specific account.

        :param address: the address of the account (binary or hex string)
        :param param: the requested parameter (`'nonce'`, `'balance'`,
                      `'storage'` or `'code'`)
        """
        if param != 'storage':
            if address in self.caches[param]:
                return self.caches[param][address]
            else:
                account = self.get_acct(address)
                o = getattr(account, param)
                self.caches[param][address] = o
                return o
        return getattr(self.get_acct(address), param)

    def _set_acct_item(self, address, param, value):
        """Set a specific parameter of a specific account.

        :param address: the address of the account (binary or hex string)
        :param param: the requested parameter (`'nonce'`, `'balance'`,
                      `'storage'` or `'code'`)
        :param value: the new value
        """
        if len(address) == 40:
            address = address.decode('hex')
        assert len(address) == 20
        self.set_and_journal(param, address, value)
        self.set_and_journal('all', address, True)

    def set_and_journal(self, cache, index, value):
        prev = self.caches[cache].get(index, None)
        if prev != value:
            self.journal.append([cache, index, prev, value])
            self.caches[cache][index] = value

    def _delta_item(self, address, param, value):
        """Add a value to an account item.

        If the resulting value would be negative, it is left unchanged and
        `False` is returned.

        :param address: the address of the account (binary or hex string)
        :param param: the parameter to increase or decrease (`'nonce'`,
                      `'balance'`, `'storage'` or `'code'`)
        :param value: can be positive or negative
        :returns: `True` if the operation was successful, `False` if not
        """
        new_value = self._get_acct_item(address, param) + value
        if new_value < 0:
            return False
        self._set_acct_item(address, param, new_value % 2**256)
        return True

    def mk_transaction_receipt(self, tx):
        """Create a receipt for a transaction."""
        return Receipt(self.state_root, self.gas_used, tx.logs,
                       tx.log_bloom())

    def add_transaction_to_list(self, tx):
        """Add a transaction to the transaction trie.

        Note that this does not execute anything, i.e. the state is not
        updated.
        """
        k = rlp.encode(self.transaction_count)
        self.transactions.update(k, rlp.encode(tx))
        r = self.mk_transaction_receipt(tx)
        self.receipts.update(k, rlp.encode(r))
        self.bloom |= r.bloom  # int
        self.transaction_count += 1

    def get_transaction(self, num):
        """Get the `num`th transaction in this block."""
        index = rlp.encode(num)
        return rlp.decode(self.transactions.get(index), Transaction)


    def get_transactions(self):
        """Build a list of all transactions in this block."""
        txs = []
        for i in range(self.transaction_count):
            txs.append(self.get_transaction(i))
        return txs

    def get_receipt(self, num):
        """Get the receipt of the `num`th transaction.

        :returns: an instance of :class:`Receipt`
        """
        index = rlp.encode(num)
        return rlp.decode(self.receipts.get(index), Receipt)

    def get_nonce(self, address):
        """Get the nonce of an account.

        :param address: the address of the account (binary or hex string)
        """
        return self._get_acct_item(address, 'nonce')

    def set_nonce(self, address, value):
        """Set the nonce of an account.

        :param address: the address of the account (binary or hex string)
        :param value: the new nonce
        :returns: `True` if successful, otherwise `False`
        """
        return self._set_acct_item(address, 'nonce', value)

    def increment_nonce(self, address):
        """Increment the nonce of an account.

        :param address: the address of the account (binary or hex string)
        :returns: `True` if successful, otherwise `False`
        """
        return self._delta_item(address, 'nonce', 1)

    def decrement_nonce(self, address):
        """Decrement the nonce of an account.

        :param address: the address of the account (binary or hex string)
        :returns: `True` if successful, otherwise `False`
        """
        return self._delta_item(address, 'nonce', -1)

    def get_balance(self, address):
        """Get the balance of an account.

        :param address: the address of the account (binary or hex string)
        """
        return self._get_acct_item(address, 'balance')

    def set_balance(self, address, value):
        """Set the balance of an account.

        :param address: the address of the account (binary or hex string)
        :param value: the new balance
        :returns: `True` if successful, otherwise `False`
        """
        self._set_acct_item(address, 'balance', value)

    def delta_balance(self, address, value):
        """Increase the balance of an account.

        :param address: the address of the account (binary or hex string)
        :param value: can be positive or negative
        :returns: `True` if successful, otherwise `False`
        """
        return self._delta_item(address, 'balance', value)

    def transfer_value(self, from_addr, to_addr, value):
        """Transfer a value between two account balances.

        :param from_addr: the address of the sending account (binary or hex
                          string)
        :param to_addr: the address of the receiving account (binary or hex
                        string)
        :param value: the (positive) value to send
        :returns: `True` if successful, otherwise `False`
        """
        assert value >= 0
        if self.delta_balance(from_addr, -value):
            return self.delta_balance(to_addr, value)
        return False

    def get_code(self, address):
        """Get the code of an account.

        :param address: the address of the account (binary or hex string)
        """
        return self._get_acct_item(address, 'code')

    def set_code(self, address, value):
        """Set the code of an account.

        :param address: the address of the account (binary or hex string)
        :param value: the new code
        :returns: `True` if successful, otherwise `False`
        """
        self._set_acct_item(address, 'code', value)

    def get_storage(self, address):
        """Get the trie holding an account's storage.

        :param address: the address of the account (binary or hex string)
        :param value: the new code
        """
        storage_root = self._get_acct_item(address, 'storage')
        return trie.Trie(self.db, storage_root)

    def get_storage_data(self, address, index):
        """Get a specific item in the storage of an account.

        :param address: the address of the account (binary or hex string)
        :param index: the index of the requested item in the storage
        """
        if len(address) == 40:
            address = address.decode('hex')
        assert len(address) == 20
        CACHE_KEY = 'storage:' + address
        if CACHE_KEY in self.caches:
            if index in self.caches[CACHE_KEY]:
                return self.caches[CACHE_KEY][index]
        key = utils.zpad(utils.coerce_to_bytes(index), 32)
        storage = self.get_storage(address).get(key)
        if storage:
            return rlp.decode(storage, big_endian_int)
        else:
            return 0

    def set_storage_data(self, address, index, value):
        """Set a specific item in the storage of an account.

        :param address: the address of the account (binary or hex string)
        :param index: the index of the item in the storage
        :param value: the new value of the item
        """
        if len(address) == 40:
            address = address.decode('hex')
        assert len(address) == 20
        CACHE_KEY = 'storage:' + address
        if CACHE_KEY not in self.caches:
            self.caches[CACHE_KEY] = {}
            self.set_and_journal('all', address, True)
        self.set_and_journal(CACHE_KEY, index, value)

    def commit_state(self):
        """Put journaled account updates on the corresponding tries and clear
        the cache.
        """
        changes = []
        if len(self.journal) == 0:
            # log_state.trace('delta', changes=[])
            return
        for address in self.caches['all']:
            acct = self.get_acct(address)

            # storage
            t = trie.Trie(self.db, acct.storage)
            for k, v in self.caches.get('storage:' + address, {}).iteritems():
                enckey = utils.zpad(utils.coerce_to_bytes(k), 32)
                val = rlp.encode(v)
                changes.append(['storage', address, k, v])
                if v:
                    t.update(enckey, val)
                else:
                    t.delete(enckey)
            acct.storage = t.root_hash
            for field in ('balance', 'nonce', 'code'):
                if address in self.caches[field]:
                    v = self.caches[field][address]
                    changes.append([field, address, v])
                    setattr(acct, field, v)
            self.state.update(address, rlp.encode(acct))
        log_state.trace('delta', changes=changes)
        self.reset_cache()

    def del_account(self, address):
        """Delete an account.

        :param address: the address of the account (binary or hex string)
        """
        if len(address) == 40:
            address = address.decode('hex')
        assert len(address) == 20
        self.commit_state()
        self.state.delete(address)

    def account_to_dict(self, address, with_storage_root=False,
                        with_storage=True):
        """Serialize an account to a readable dictionary.

        :param address: the 20 bytes account address
        :param with_storage_root: include the account's storage root
        :param with_storage: include the whole account's storage
        """
        if len(address) == 40:
            address = address.decode('hex')
        assert len(address) == 20

        if with_storage_root:
            # if there are uncommited account changes the current storage root
            # is meaningless
            assert len(self.journal) == 0
        med_dict = {}

        account = self.get_acct(address)
        for field in ('balance', 'nonce'):
            value = self.caches[field].get(address, getattr(account, field))
            med_dict[field] = str(value)
        code = self.caches['code'].get(address, account.code)
        med_dict['code'] = '0x' + code.encode('hex')

        storage_trie = trie.Trie(self.db, account.storage)
        if with_storage_root:
            med_dict['storage_root'] = storage_trie.get_root_hash()  \
                                                   .encode('hex')
        if with_storage:
            med_dict['storage'] = {}
            d = storage_trie.to_dict()
            subcache = self.caches.get('storage:' + address, {})
            subkeys = [utils.zpad(utils.coerce_to_bytes(kk), 32)
                       for kk in subcache.keys()]
            for k in d.keys() + subkeys:
                v = d.get(k, None)
                v2 = subcache.get(utils.big_endian_to_int(k), None)
                hexkey = '0x' + utils.zunpad(k).encode('hex')
                if v2 is not None:
                    if v2 != 0:
                        med_dict['storage'][hexkey] = \
                            '0x' + utils.int_to_big_endian(v2).encode('hex')
                elif v is not None:
                    med_dict['storage'][hexkey] = '0x' + rlp.decode(v).encode('hex')

        return med_dict

    def reset_cache(self):
        """Reset cache and journal without commiting any changes."""
        self.caches = {
            'all': {},
            'balance': {},
            'nonce': {},
            'code': {},
        }
        self.journal = []

    def snapshot(self):
        """Make a snapshot of the current state to enable later reverting."""
        return {
            'state': self.state.root_hash,
            'gas': self.gas_used,
            'txs': self.transactions,
            'txcount': self.transaction_count,
            'suicides': self.suicides,
            'logs': self.logs,
            'refunds': self.refunds,
            'suicides_size': len(self.suicides),
            'logs_size': len(self.logs),
            'journal': self.journal,  # pointer to reference, so is not static
            'journal_size': len(self.journal)
        }

    def revert(self, mysnapshot):
        """Revert to a previously made snapshot.

        Reverting is for example necessary when a contract runs out of gas
        during execution.
        """
        self.journal = mysnapshot['journal']
        log_state.trace('reverting')
        while len(self.journal) > mysnapshot['journal_size']:
            cache, index, prev, post = self.journal.pop()
            log_state.trace('%r %r %r %r' % (cache, index, prev, post))
            if prev is not None:
                self.caches[cache][index] = prev
            else:
                del self.caches[cache][index]
        self.suicides = mysnapshot['suicides']
        while len(self.suicides) > mysnapshot['suicides_size']:
            self.suicides.pop()
        print 'Popping logs: ', len(self.logs), ' to ', mysnapshot['logs_size']
        self.logs = mysnapshot['logs']
        while len(self.logs) > mysnapshot['logs_size']:
            self.logs.pop()
        self.refunds = mysnapshot['refunds']
        self.state.root_hash = mysnapshot['state']
        self.gas_used = mysnapshot['gas']
        self.transactions = mysnapshot['txs']
        self.transaction_count = mysnapshot['txcount']

    def finalize(self):
        """Apply rewards and commit."""
        self.delta_balance(self.coinbase,
                           BLOCK_REWARD + NEPHEW_REWARD * len(self.uncles))
        for uncle in self.uncles:
            self.delta_balance(uncle.coinbase, UNCLE_REWARD)
        self.commit_state()

    def to_dict(self, with_state=False, full_transactions=False,
                with_storage_roots=False, with_uncles=False):
        """Serialize the block to a readable dictionary.

        :param with_state: include state for all accounts
        :param full_transactions: include serialized transactions (hashes
                                  otherwise)
        :param with_storage_roots: if account states are included also include
                                   their storage roots
        :param with_uncles: include uncle hashes
        """
        b = {}
        for field in ('prevhash', 'uncles_hash', 'extra_data', 'nonce'):
            b[field] = '0x' + getattr(self, field).encode('hex')
        for field in ('state_root', 'tx_list_root', 'receipts_root',
                      'coinbase'):
            b[field] = getattr(self, field).encode('hex')
        for field in ('number', 'difficulty', 'gas_limit', 'gas_used',
                      'timestamp'):
            b[field] = str(getattr(self, field))
        b['bloom'] = int64.serialize(self.bloom).encode('hex')
        assert len(b) == len(BlockHeader.fields)

        txlist = []
        for i, tx in enumerate(self.get_transactions()):
            receipt_rlp = self.receipts.get(rlp.encode(i))
            receipt = rlp.decode(receipt_rlp, Receipt)
            if full_transactions:
                txjson = tx.to_dict()
            else:
                txjson = tx.hash
            txlist.append({
                "tx": txjson,
                "medstate": receipt.state_root.encode('hex'),
                "gas": str(receipt.gas_used),
                "logs": [Log.serialize(log) for log in receipt.logs],
                "bloom": utils.int64.serialize(receipt.bloom)
            })
        b["transactions"] = txlist
        if with_state:
            state_dump = {}
            for address, v in self.state.to_dict().iteritems():
                state_dump[address.encode('hex')] = \
                    self.account_to_dict(address, with_storage_roots)
            b['state'] = state_dump
        if with_uncles:
            b['uncles'] = [utils.sha3(rlp.encode(u)).encode('hex')
                           for u in self.uncles]
        return b

    def get_parent(self):
        """Get the parent of this block."""
        if self.number == 0:
            raise UnknownParentException('Genesis block has no parent')
        try:
            parent = get_block(self.db, self.prevhash)
        except KeyError:
            raise UnknownParentException(self.prevhash.encode('hex'))
        # assert parent.state.db.db == self.state.db.db
        return parent

    def has_parent(self):
        """`True` if this block has a known parent, otherwise `False`."""
        try:
            self.get_parent()
            return True
        except UnknownParentException:
            return False

    def chain_difficulty(self):
        """Get the summarized difficulty.

        If the summarized difficulty is not stored in the database, it will be
        calculated recursively and put in the database.
        """
        if self.is_genesis():
            return self.difficulty
        elif 'difficulty:' + self.hash.encode('hex') in self.db:
            encoded = self.db.get('difficulty:' + self.hash.encode('hex'))
            return utils.decode_int(encoded)
        else:
            o = self.difficulty + self.get_parent().chain_difficulty()
            o += sum([uncle.difficulty for uncle in self.uncles])
            self.state.db.put('difficulty:' + self.hash.encode('hex'),
                              utils.encode_int(o))
            return o

            return rlp.decode(rlp.encode(l)) == l

    def __eq__(self, other):
        return isinstance(other, (Block, CachedBlock)) and  \
               self.hash == other.hash

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        return self.number > other.number

    def __lt__(self, other):
        return self.number < other.number

    def __repr__(self):
        return '<Block(#%d %s)>' % (self.number, self.hash.encode('hex')[:8])

    def __structlog__(self):
        return self.hash.encode('hex')


# Difficulty adjustment algo
def calc_difficulty(parent, timestamp):
    offset = parent.difficulty / BLOCK_DIFF_FACTOR
    sign = 1 if timestamp - parent.timestamp < DIFF_ADJUSTMENT_CUTOFF else -1
    return parent.difficulty + offset * sign


# Gas limit adjustment algo
def calc_gaslimit(parent):
    prior_contribution = parent.gas_limit * (GASLIMIT_EMA_FACTOR - 1)
    new_contribution = parent.gas_used * BLKLIM_FACTOR_NOM / BLKLIM_FACTOR_DEN
    gl = (prior_contribution + new_contribution) / GASLIMIT_EMA_FACTOR
    return max(gl, MIN_GAS_LIMIT)

# Auxiliary value for must_equal error message
aux = [None]


def set_aux(auxval):
    aux[0] = auxval


def must_equal(what, a, b):
    if a != b:
        if aux[0]:
            sys.stderr.write('%r' % aux[0])
        raise VerificationFailed(what, a, '==', b)


class CachedBlock(Block):
    # note: immutable refers to: do not manipulate!
    _hash_cached = None

    def _set_acct_item(self):
        raise NotImplementedError

    def set_state_root(self):
        raise NotImplementedError

    def revert(self):
        raise NotImplementedError

    def commit_state(self):
        pass

    @property
    def hash(self):
        if not self._hash_cached:
            self._hash_cached = super(CachedBlock, self).hash
        return self._hash_cached

    @classmethod
    def create_cached(cls, blk):
        blk.__class__ = CachedBlock
        return blk


@lru_cache(500)
def get_block(db, blockhash):
    """
    Assumption: blocks loaded from the db are not manipulated
                -> can be cached including hash
    """
    blk = rlp.decode(db.get(blockhash), Block, db=db)
    return CachedBlock.create_cached(blk)


#def has_block(blockhash):
#    return blockhash in db.DB(utils.get_db_path())


def genesis(db, start_alloc=GENESIS_INITIAL_ALLOC, difficulty=GENESIS_DIFFICULTY):
    """Build the genesis block."""
    # https://ethereum.etherpad.mozilla.org/11
    # TODO: check values
    header = BlockHeader(
        prevhash=GENESIS_PREVHASH,
        uncles_hash=utils.sha3(rlp.encode([])),
        coinbase=GENESIS_COINBASE,
        state_root=trie.BLANK_ROOT,
        tx_list_root=trie.BLANK_ROOT,
        receipts_root=trie.BLANK_ROOT,
        bloom=0,
        difficulty=difficulty,
        number=0,
        gas_limit=GENESIS_GAS_LIMIT,
        gas_used=0,
        timestamp=0,
        extra_data='',
        nonce=GENESIS_NONCE,
    )
    block = Block(header, [], [], db=db)
    for addr, balance in start_alloc.iteritems():
        block.set_balance(addr, balance)
    block.commit_state()
    block.state.db.commit()
    # genesis block has predefined state root (so no additional finalization
    # necessary)
    return block


def dump_genesis_block_tests_data(db):
    import json
    g = genesis(db)
    data = dict(
        genesis_state_root=g.state_root.encode('hex'),
        genesis_hash=g.hex_hash(),
        genesis_rlp_hex=g.serialize().encode('hex'),
        initial_alloc=dict()
    )
    for addr, balance in GENESIS_INITIAL_ALLOC.iteritems():
        data['initial_alloc'][addr] = str(balance)

    print json.dumps(data, indent=1)
