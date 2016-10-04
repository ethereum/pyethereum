#  ####### dev hack flags ###############

dump_block_on_failed_verification = False

#  ######################################
import time
from itertools import count
import sys
from collections import Iterable
import rlp
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from rlp.utils import decode_hex, encode_hex
from ethereum import pruning_trie as trie
from ethereum.pruning_trie import Trie
from ethereum.securetrie import SecureTrie
from ethereum import utils
from ethereum.utils import address, int256, trie_root, hash32, to_string, big_endian_to_int
from ethereum import processblock
from ethereum.transactions import Transaction
from ethereum import bloom
from ethereum.exceptions import UnknownParentException, VerificationFailed
from ethereum.slogging import get_logger
from ethereum.ethpow import check_pow
from ethereum.db import BaseDB
from ethereum.config import Env, default_config

if sys.version_info.major == 2:
    from repoze.lru import lru_cache
else:
    from functools import lru_cache


log = get_logger('eth.block')
log_state = get_logger('eth.msg.state')
Log = processblock.Log


class lazy_encode(object):
    def __init__(self, data):
        self.data = data

    def encode_entry(self, entry):
        def safe_encode(value):
            # handle binary data (assuming all str are binary)
            if isinstance(value, (str, unicode)):
                return encode_hex(value)

            # handle non binary data, eg.: floats, ints ...
            return repr(value)

        if not isinstance(entry, Iterable):
            raise ValueError('entry must be iterable')

        entry = list(entry)  # consume the iterable

        if len(entry) == 3:
            name, addr, v = entry
            if name == 'code':
                return [name, safe_encode(addr), safe_encode(v)]
            else:
                return [name, safe_encode(addr), v]

        if len(entry) == 4:
            name, addr, k, v = entry
            return [
                name,
                safe_encode(addr),
                safe_encode(k),
                safe_encode(v),
            ]

        raise ValueError('Unexpected entry format {}'.format(entry))

    def __repr__(self):
        return repr([self.encode_entry(entry) for entry in self.data])

    def __str__(self):
        return str(repr(self))


# Difficulty adjustment algo
def calc_difficulty(parent, timestamp):
    config = parent.config
    offset = parent.difficulty // config['BLOCK_DIFF_FACTOR']
    if parent.number >= (config['METROPOLIS_FORK_BLKNUM'] - 1):
        sign = max(len(parent.uncles) - ((timestamp - parent.timestamp) // config['METROPOLIS_DIFF_ADJUSTMENT_CUTOFF']), -99)
    elif parent.number >= (config['HOMESTEAD_FORK_BLKNUM'] - 1):
        sign = max(1 - ((timestamp - parent.timestamp) // config['HOMESTEAD_DIFF_ADJUSTMENT_CUTOFF']), -99)
    else:
        sign = 1 if timestamp - parent.timestamp < config['DIFF_ADJUSTMENT_CUTOFF'] else -1
    # If we enter a special mode where the genesis difficulty starts off below
    # the minimal difficulty, we allow low-difficulty blocks (this will never
    # happen in the official protocol)
    o = int(max(parent.difficulty + offset * sign, min(parent.difficulty, config['MIN_DIFF'])))
    period_count = (parent.number + 1) // config['EXPDIFF_PERIOD']
    if period_count >= config['EXPDIFF_FREE_PERIODS']:
        o = max(o + 2 ** (period_count - config['EXPDIFF_FREE_PERIODS']), config['MIN_DIFF'])
    # print('Calculating difficulty of block %d, timestamp difference %d, parent diff %d, child diff %d' % (parent.number + 1, timestamp - parent.timestamp, parent.difficulty, o))
    return o


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
        assert isinstance(db, BaseDB)
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
        # Technically a db storage leak, but doesn't really matter; the only
        # thing that fails to get garbage collected is when code disappears due
        # to a suicide
        self.db.inc_refcount(self.code_hash, value)

    @classmethod
    def blank_account(cls, db, initial_nonce=0):
        """Create a blank account

        The returned account will have zero nonce and balance, a blank storage
        trie and empty code.

        :param db: the db in which the account will store its code.
        """
        code_hash = utils.sha3(b'')
        db.put(code_hash, b'')
        return cls(initial_nonce, 0, trie.BLANK_ROOT, code_hash, db)


class Receipt(rlp.Serializable):

    fields = [
        ('state_root', trie_root),
        ('gas_used', big_endian_int),
        ('bloom', int256),
        ('logs', CountableList(processblock.Log))
    ]

    def __init__(self, state_root, gas_used, logs, bloom=None):
        # does not call super.__init__ as bloom should not be an attribute but a property
        self.state_root = state_root
        self.gas_used = gas_used
        self.logs = logs
        if bloom is not None and bloom != self.bloom:
            raise ValueError("Invalid bloom filter")
        self._cached_rlp = None
        self._mutable = True

    @property
    def bloom(self):
        bloomables = [x.bloomables() for x in self.logs]
        return bloom.bloom_from_list(utils.flatten(bloomables))


class BlockHeader(rlp.Serializable):

    """A block header.

    If the block with this header exists as an instance of :class:`Block`, the
    connection can be made explicit by setting :attr:`BlockHeader.block`. Then,
    :attr:`BlockHeader.state_root`, :attr:`BlockHeader.tx_list_root` and
    :attr:`BlockHeader.receipts_root` always refer to the up-to-date value in
    the block instance.

    :ivar block: an instance of :class:`Block` or `None`
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
        ('bloom', int256),
        ('difficulty', big_endian_int),
        ('number', big_endian_int),
        ('gas_limit', big_endian_int),
        ('gas_used', big_endian_int),
        ('timestamp', big_endian_int),
        ('extra_data', binary),
        ('mixhash', binary),
        ('nonce', Binary(8, allow_empty=True))
    ]

    def __init__(self,
                 prevhash=default_config['GENESIS_PREVHASH'],
                 uncles_hash=utils.sha3rlp([]),
                 coinbase=default_config['GENESIS_COINBASE'],
                 state_root=trie.BLANK_ROOT,
                 tx_list_root=trie.BLANK_ROOT,
                 receipts_root=trie.BLANK_ROOT,
                 bloom=0,
                 difficulty=default_config['GENESIS_DIFFICULTY'],
                 number=0,
                 gas_limit=default_config['GENESIS_GAS_LIMIT'],
                 gas_used=0,
                 timestamp=0,
                 extra_data='',
                 mixhash=default_config['GENESIS_MIXHASH'],
                 nonce=''):
        # at the beginning of a method, locals() is a dict of all arguments
        fields = {k: v for k, v in locals().items() if k != 'self'}
        if len(fields['coinbase']) == 40:
            fields['coinbase'] = decode_hex(fields['coinbase'])
        assert len(fields['coinbase']) == 20
        self.block = None
        super(BlockHeader, self).__init__(**fields)

    @classmethod
    def from_block_rlp(self, rlp_data):
        block_data = rlp.decode_lazy(rlp_data)
        r = super(BlockHeader, self).deserialize(block_data[0])
        assert isinstance(r, BlockHeader)
        return r

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
        return encode_hex(self.hash)

    @property
    def mining_hash(self):
        return utils.sha3(rlp.encode(self, BlockHeader.exclude(['mixhash', 'nonce'])))

    def check_pow(self, nonce=None):
        """Check if the proof-of-work of the block is valid.

        :param nonce: if given the proof of work function will be evaluated
                      with this nonce instead of the one already present in
                      the header
        :returns: `True` or `False`
        """
        log.debug('checking pow', block=self.hex_hash()[:8])
        return check_pow(self.number, self.mining_hash, self.mixhash, nonce or self.nonce,
                         self.difficulty)

    def to_dict(self):
        """Serialize the header to a readable dictionary."""
        d = {}
        for field in ('prevhash', 'uncles_hash', 'extra_data', 'nonce',
                      'mixhash'):
            d[field] = b'0x' + encode_hex(getattr(self, field))
        for field in ('state_root', 'tx_list_root', 'receipts_root',
                      'coinbase'):
            d[field] = encode_hex(getattr(self, field))
        for field in ('number', 'difficulty', 'gas_limit', 'gas_used',
                      'timestamp'):
            d[field] = to_string(getattr(self, field))
        d['bloom'] = encode_hex(int256.serialize(self.bloom))
        assert len(d) == len(BlockHeader.fields)
        return d

    def __repr__(self):
        return '<%s(#%d %s)>' % (self.__class__.__name__, self.number,
                                 encode_hex(self.hash)[:8])

    def __eq__(self, other):
        """Two blockheader are equal iff they have the same hash."""
        return isinstance(other, BlockHeader) and self.hash == other.hash

    def __hash__(self):
        return big_endian_to_int(self.hash)

    def __ne__(self, other):
        return not self.__eq__(other)


def mirror_from(source, attributes, only_getters=True):
    """Decorator (factory) for classes that mirror some attributes from an
    instance variable.

    :param source: the name of the instance variable to mirror from
    :param attributes: list of attribute names to mirror
    :param only_getters: if true only getters but not setters are created
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


@mirror_from('header', set(field for field, _ in BlockHeader.fields) -
             set(['state_root', 'receipts_root', 'tx_list_root']),
             only_getters=False)
class Block(rlp.Serializable):

    """A block.

    All attributes from the block header are accessible via properties
    (i.e. ``block.prevhash`` is equivalent to ``block.header.prevhash``). It
    is ensured that no discrepancies between header and block occur.

    :param header: the block header
    :param transaction_list: a list of transactions which are replayed if the
                             state given by the header is not known. If the
                             state is known, `None` can be used instead of the
                             empty list.
    :param uncles: a list of the headers of the uncles of this block
    :param db: the database in which the block's  state, transactions and
               receipts are stored (required)
    :param parent: optional parent which if not given may have to be loaded from
                   the database for replay
    """

    fields = [
        ('header', BlockHeader),
        ('transaction_list', CountableList(Transaction)),
        ('uncles', CountableList(BlockHeader))
    ]

    def __init__(self, header, transaction_list=[], uncles=[], env=None,
                 parent=None, making=False):
        assert isinstance(env, Env), "No Env object given"
        assert isinstance(env.db, BaseDB), "No database object given"
        self.env = env  # don't re-set after init
        self.db = env.db
        self.config = env.config

        self.header = header
        self.uncles = uncles

        self.suicides = []
        self.logs = []
        self.log_listeners = []
        self.refunds = 0

        self.ether_delta = 0
        self._get_transactions_cache = []

        # Journaling cache for state tree updates
        self.caches = {
            'balance': {},
            'nonce': {},
            'code': {},
            'storage': {},
            'all': {}
        }
        self.journal = []

        if self.number > 0:
            self.ancestor_hashes = [self.prevhash]
        else:
            self.ancestor_hashes = [None] * 256

        # do some consistency checks on parent if given
        if parent:
            if hasattr(parent, 'db') and self.db != parent.db and self.db.db != parent.db:
                raise ValueError("Parent lives in different database")
            if self.prevhash != parent.header.hash:
                raise ValueError("Block's prevhash and parent's hash do not match")
            if self.number != parent.header.number + 1:
                raise ValueError("Block's number is not the successor of its parent number")
            if not check_gaslimit(parent, self.gas_limit):
                raise ValueError("Block's gaslimit is inconsistent with its parent's gaslimit")
            if self.difficulty != calc_difficulty(parent, self.timestamp):
                raise ValueError("Block's difficulty is inconsistent with its parent's difficulty")
            if self.gas_used > self.gas_limit:
                raise ValueError("Gas used exceeds gas limit")
            if self.timestamp <= parent.header.timestamp:
                raise ValueError("Timestamp equal to or before parent")
            if self.timestamp >= 2 ** 256:
                raise ValueError("Timestamp waaaaaaaaaaayy too large")

        if self.gas_limit > self.config['MAX_GAS_LIMIT']:
            raise ValueError("Block's gaslimit went too high!")

        for uncle in uncles:
            assert isinstance(uncle, BlockHeader)

        original_values = {
            'gas_used': header.gas_used,
            'timestamp': header.timestamp,
            'difficulty': header.difficulty,
            'uncles_hash': header.uncles_hash,
            'bloom': header.bloom,
            'header_mutable': self.header._mutable,
        }
        assert self._mutable
        self._cached_rlp = None
        self.header._mutable = True

        self.transactions = Trie(self.db, trie.BLANK_ROOT)
        self.receipts = Trie(self.db, trie.BLANK_ROOT)
        # replay transactions if state is unknown
        state_unknown = (header.prevhash != self.config['GENESIS_PREVHASH'] and
                         header.number != 0 and
                         header.state_root != trie.BLANK_ROOT and
                         (len(header.state_root) != 32 or
                          b'validated:' + self.hash not in self.db) and
                         not making)
        if state_unknown:
            assert transaction_list is not None
            if not parent:
                parent = self.get_parent_header()
            self.state = SecureTrie(Trie(self.db, parent.state_root))
            self.transaction_count = 0
            self.gas_used = 0
            # replay
            self.initialize(parent)
            for tx in transaction_list:
                success, output = processblock.apply_transaction(self, tx)
            self.finalize()
        else:
            # trust the state root in the header
            self.state = SecureTrie(Trie(self.db, header._state_root))
            self.transaction_count = 0
            if transaction_list:
                for tx in transaction_list:
                    self.add_transaction_to_list(tx)
            if self.transactions.root_hash != header.tx_list_root:
                raise ValueError("Transaction list root hash does not match")
            # receipts trie populated by add_transaction_to_list is incorrect
            # (it doesn't know intermediate states), so reset it
            self.receipts = Trie(self.db, header.receipts_root)

        # checks ##############################

        def must(what, f, symb, a, b):
            if not f(a, b):
                if dump_block_on_failed_verification:
                    sys.stderr.write('%r' % self.to_dict())
                raise VerificationFailed(what, a, symb, b)

        def must_equal(what, a, b):
            return must(what, lambda x, y: x == y, "==", a, b)

        def must_ge(what, a, b):
            return must(what, lambda x, y: x >= y, ">=", a, b)

        def must_le(what, a, b):
            return must(what, lambda x, y: x <= y, "<=", a, b)

        if parent:
            must_equal('prev_hash', self.prevhash, parent.hash)
        must_equal('gas_used', original_values['gas_used'], self.gas_used)
        must_equal('timestamp', self.timestamp, original_values['timestamp'])
        must_equal('difficulty', self.difficulty, original_values['difficulty'])
        must_equal('uncles_hash', utils.sha3(rlp.encode(uncles)), original_values['uncles_hash'])
        assert header.block is None
        must_equal('state_root', self.state.root_hash, header.state_root)
        must_equal('tx_list_root', self.transactions.root_hash, header.tx_list_root)
        must_equal('receipts_root', self.receipts.root_hash, header.receipts_root)
        must_equal('bloom', self.bloom, original_values['bloom'])

        # from now on, trie roots refer to block instead of header
        header.block = self
        self.header._mutable = original_values['header_mutable']

        # Basic consistency verifications
        if not self.check_fields():
            raise ValueError("Block is invalid")
        if len(to_string(self.header.extra_data)) > self.config['MAX_EXTRADATA_LENGTH']:
            raise ValueError("Extra data cannot exceed %d bytes"
                             % default_config['MAX_EXTRADATA_LENGTH'])
        if self.header.coinbase == '':
            raise ValueError("Coinbase cannot be empty address")
        if not self.state.root_hash_valid():
            raise ValueError("State Merkle root of block %r not found in "
                             "database" % self)
        if (not self.is_genesis() and self.nonce and not self.header.check_pow()):
            raise ValueError("PoW check failed")
        if b'validated:' + self.hash not in self.db:
            if self.number == 0:
                self.db.put(b'validated:' + self.hash, '1')
            else:
                self.db.put_temporarily(b'validated:' + self.hash, '1')

    @classmethod
    def init_from_header(cls, header_rlp, env):
        """Create a block without specifying transactions or uncles.

        :param header_rlp: the RLP encoded block header
        :param env: the database for the block
        """
        header = rlp.decode(header_rlp, BlockHeader, env=env)
        return cls(header, None, [], env=env)

    @classmethod
    def init_from_parent(cls, parent, coinbase, nonce=b'', extra_data=b'',
                         timestamp=int(time.time()), uncles=[], env=None):
        """Create a new block based on a parent block.

        The block will not include any transactions and will not be finalized.
        """
        header = BlockHeader(prevhash=parent.hash,
                             uncles_hash=utils.sha3(rlp.encode(uncles)),
                             coinbase=coinbase,
                             state_root=parent.state_root,
                             tx_list_root=trie.BLANK_ROOT,
                             receipts_root=trie.BLANK_ROOT,
                             bloom=0,
                             difficulty=calc_difficulty(parent, timestamp),
                             mixhash='',
                             number=parent.number + 1,
                             gas_limit=calc_gaslimit(parent),
                             gas_used=0,
                             timestamp=timestamp,
                             extra_data=extra_data,
                             nonce=nonce)
        block = Block(header, [], uncles, env=env or parent.env,
                      parent=parent, making=True)
        block.ancestor_hashes = [parent.hash] + parent.ancestor_hashes
        block.log_listeners = parent.log_listeners
        return block

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
        return encode_hex(self.hash)

    @property
    def tx_list_root(self):
        return self.transactions.root_hash

    @tx_list_root.setter
    def tx_list_root(self, value):
        self.transactions = Trie(self.db, value)

    @property
    def receipts_root(self):
        return self.receipts.root_hash

    @receipts_root.setter
    def receipts_root(self, value):
        self.receipts = Trie(self.db, value)

    @property
    def state_root(self):
        self.commit_state()
        return self.state.root_hash

    @state_root.setter
    def state_root(self, value):
        self.state = SecureTrie(Trie(self.db, value))
        self.reset_cache()

    @property
    def uncles_hash(self):
        return utils.sha3(rlp.encode(self.uncles))

    @property
    def transaction_list(self):
        txs = []
        for i in range(self.transaction_count):
            txs.append(self.get_transaction(i))
        return txs

    def validate_uncles(self):
        """Validate the uncles of this block."""
        if utils.sha3(rlp.encode(self.uncles)) != self.uncles_hash:
            return False
        if len(self.uncles) > self.config['MAX_UNCLES']:
            return False
        for uncle in self.uncles:
            assert uncle.prevhash in self.db
            if uncle.number == self.number:
                log.error("uncle at same block height", block=self)
                return False

        # Check uncle validity
        MAX_UNCLE_DEPTH = self.config['MAX_UNCLE_DEPTH']
        ancestor_chain = [self] + [a for a in self.get_ancestor_list(MAX_UNCLE_DEPTH + 1) if a]
        assert len(ancestor_chain) == min(self.header.number + 1, MAX_UNCLE_DEPTH + 2)
        ineligible = []
        # Uncles of this block cannot be direct ancestors and cannot also
        # be uncles included 1-6 blocks ago
        for ancestor in ancestor_chain[1:]:
            ineligible.extend(ancestor.uncles)
        ineligible.extend([b.header for b in ancestor_chain])
        eligible_ancestor_hashes = [x.hash for x in ancestor_chain[2:]]
        for uncle in self.uncles:
            parent = get_block(self.env, uncle.prevhash)
            if uncle.difficulty != calc_difficulty(parent, uncle.timestamp):
                return False
            if uncle.number != parent.number + 1:
                return False
            if uncle.timestamp < parent.timestamp:
                return False
            if not uncle.check_pow():
                return False
            if uncle.prevhash not in eligible_ancestor_hashes:
                log.error("Uncle does not have a valid ancestor", block=self,
                          eligible=[encode_hex(x) for x in eligible_ancestor_hashes],
                          uncle_prevhash=encode_hex(uncle.prevhash))
                return False
            if uncle in ineligible:
                log.error("Duplicate uncle", block=self,
                          uncle=encode_hex(utils.sha3(rlp.encode(uncle))))
                return False
            ineligible.append(uncle)
        return True

    def get_ancestor_list(self, n):
        """Return `n` ancestors of this block.

        :returns: a list [p(self), p(p(self)), ..., p^n(self)]
        """
        if n == 0 or self.header.number == 0:
            return []
        p = self.get_parent()
        return [p] + p.get_ancestor_list(n - 1)

    def get_ancestor_hash(self, n):
        assert n > 0
        while len(self.ancestor_hashes) < n:
            if self.number == len(self.ancestor_hashes) - 1:
                self.ancestor_hashes.append(None)
            else:
                self.ancestor_hashes.append(
                    get_block(self.env,
                              self.ancestor_hashes[-1]).get_parent().hash)
        return self.ancestor_hashes[n - 1]

    # def get_ancestor(self, n):
    #     return self.get_block(self.get_ancestor_hash(n))

    def is_genesis(self):
        """`True` if this block is the genesis block, otherwise `False`."""
        return self.header.number == 0

    def _get_acct(self, address):
        """Get the account with the given address.

        Note that this method ignores cached account items.
        """
        if len(address) == 40:
            address = decode_hex(address)
        assert len(address) == 20 or len(address) == 0
        rlpdata = self.state.get(address)
        if rlpdata != trie.BLANK_NODE:
            acct = rlp.decode(rlpdata, Account, db=self.db)
            acct._mutable = True
            acct._cached_rlp = None
        else:
            acct = Account.blank_account(self.db, self.config['ACCOUNT_INITIAL_NONCE'])
        return acct

    def _get_acct_item(self, address, param):
        """Get a specific parameter of a specific account.

        :param address: the address of the account (binary or hex string)
        :param param: the requested parameter (`'nonce'`, `'balance'`,
                      `'storage'` or `'code'`)
        """
        if len(address) == 40:
            address = decode_hex(address)
        assert len(address) == 20 or len(address) == 0
        if address in self.caches[param]:
            return self.caches[param][address]
        else:
            account = self._get_acct(address)
            o = getattr(account, param)
            self.caches[param][address] = o
            return o

    def _set_acct_item(self, address, param, value):
        """Set a specific parameter of a specific account.

        :param address: the address of the account (binary or hex string)
        :param param: the requested parameter (`'nonce'`, `'balance'`,
                      `'storage'` or `'code'`)
        :param value: the new value
        """
        if len(address) == 40:
            address = decode_hex(address)
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
        self._set_acct_item(address, param, new_value % 2 ** 256)
        return True

    def mk_transaction_receipt(self, tx):
        """Create a receipt for a transaction."""
        if self.number >= self.config["METROPOLIS_FORK_BLKNUM"]:
            return Receipt(b'\x00' * 32, self.gas_used, self.logs)
        else:
            return Receipt(self.state_root, self.gas_used, self.logs)

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
        """Get the `num`th transaction in this block.

        :raises: :exc:`IndexError` if the transaction does not exist
        """
        index = rlp.encode(num)
        tx = self.transactions.get(index)
        if tx == trie.BLANK_NODE:
            raise IndexError('Transaction does not exist')
        else:
            return rlp.decode(tx, Transaction)

    def num_transactions(self):
        return self.transaction_count

    def get_transactions(self):
        """Build a list of all transactions in this block."""
        num = self.transaction_count
        if len(self._get_transactions_cache) != num:
            txs = []
            for i in range(num):
                txs.append(self.get_transaction(i))
            self._get_transactions_cache = txs
        return self._get_transactions_cache

    def get_transaction_hashes(self):
        "helper to check if blk contains a tx"
        return [utils.sha3(self.transactions.get(rlp.encode(i)))
                for i in range(self.transaction_count)]

    def includes_transaction(self, tx_hash):
        assert isinstance(tx_hash, bytes)
        #assert self.get_transaction_hashes() == [tx.hash for tx in self.get_transactions()]
        return tx_hash in self.get_transaction_hashes()

    def get_receipt(self, num):
        """Get the receipt of the `num`th transaction.

        :returns: an instance of :class:`Receipt`
        """
        index = rlp.encode(num)
        receipt = self.receipts.get(index)
        if receipt == trie.BLANK_NODE:
            raise IndexError('Receipt does not exist')
        else:
            return rlp.decode(receipt, Receipt)

    def get_receipts(self):
        """Build a list of all receipts in this block."""
        receipts = []
        for i in count():
            try:
                receipts.append(self.get_receipt(i))
            except IndexError:
                return receipts

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
        if self.get_nonce(address) == 0:
            return self._delta_item(address, 'nonce', self.config['ACCOUNT_INITIAL_NONCE'] + 1)
        else:
            return self._delta_item(address, 'nonce', 1)

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
        return SecureTrie(Trie(self.db, storage_root))

    def reset_storage(self, address):
        self._set_acct_item(address, 'storage', b'')
        CACHE_KEY = b'storage:' + address
        if CACHE_KEY in self.caches:
            for k in self.caches[CACHE_KEY]:
                self.set_and_journal(CACHE_KEY, k, 0)

    def get_storage_data(self, address, index):
        """Get a specific item in the storage of an account.

        :param address: the address of the account (binary or hex string)
        :param index: the index of the requested item in the storage
        """
        if len(address) == 40:
            address = decode_hex(address)
        assert len(address) == 20
        CACHE_KEY = b'storage:' + address
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
            address = decode_hex(address)
        assert len(address) == 20
        CACHE_KEY = b'storage:' + address
        if CACHE_KEY not in self.caches:
            self.caches[CACHE_KEY] = {}
            self.set_and_journal('all', address, True)
        self.set_and_journal(CACHE_KEY, index, value)

    def account_exists(self, address):
        if len(address) == 40:
            address = decode_hex(address)
        assert len(address) == 20
        return len(self.state.get(address)) > 0 or address in self.caches['all']

    def add_log(self, log):
        self.logs.append(log)
        for L in self.log_listeners:
            L(log)

    def commit_state(self):
        """Commit account caches"""
        """Write the acount caches on the corresponding tries."""
        changes = []
        if len(self.journal) == 0:
            # log_state.trace('delta', changes=[])
            return
        addresses = sorted(list(self.caches['all'].keys()))
        for addr in addresses:
            acct = self._get_acct(addr)

            # storage
            for field in ('balance', 'nonce', 'code', 'storage'):
                if addr in self.caches[field]:
                    v = self.caches[field][addr]
                    changes.append([field, addr, v])
                    setattr(acct, field, v)

            t = SecureTrie(Trie(self.db, acct.storage))
            for k, v in self.caches.get(b'storage:' + addr, {}).items():
                enckey = utils.zpad(utils.coerce_to_bytes(k), 32)
                val = rlp.encode(v)
                changes.append(['storage', addr, k, v])
                # if self.number > 18280 and False:
                #     try:
                #         self.db.logging = True
                #     except:
                #         pass
                #     sys.stderr.write("pre: %r\n" % self.account_to_dict(addr)['storage'])
                #     sys.stderr.write("pre: %r\n" % encode_hex(self.get_storage(addr).root_hash))
                #     sys.stderr.write("changed: %s %s %s\n" % (encode_hex(addr), encode_hex(enckey), encode_hex(val)))
                if v:
                    t.update(enckey, val)
                else:
                    t.delete(enckey)
            acct.storage = t.root_hash
            self.state.update(addr, rlp.encode(acct))
        log_state.trace('delta', changes=lazy_encode(changes))
        self.reset_cache()
        self.db.put_temporarily(b'validated:' + self.hash, '1')

    def del_account(self, address):
        """Delete an account.

        :param address: the address of the account (binary or hex string)
        """
        if len(address) == 40:
            address = decode_hex(address)
        assert len(address) == 20
        self.commit_state()
        self.state.delete(address)

    def account_to_dict(self, address, with_storage_root=False,
                        with_storage=True):
        """Serialize an account to a dictionary with human readable entries.

        :param address: the 20 bytes account address
        :param with_storage_root: include the account's storage root
        :param with_storage: include the whole account's storage
        """
        if len(address) == 40:
            address = decode_hex(address)
        assert len(address) == 20

        if with_storage_root:
            # if there are uncommited account changes the current storage root
            # is meaningless
            assert len(self.journal) == 0
        med_dict = {}

        account = self._get_acct(address)
        for field in ('balance', 'nonce'):
            value = self.caches[field].get(address, getattr(account, field))
            med_dict[field] = to_string(value)
        code = self.caches['code'].get(address, account.code)
        med_dict['code'] = b'0x' + encode_hex(code)

        storage_trie = SecureTrie(Trie(self.db, account.storage))
        if with_storage_root:
            med_dict['storage_root'] = encode_hex(storage_trie.get_root_hash())
        if with_storage:
            med_dict['storage'] = {}
            d = storage_trie.to_dict()
            subcache = self.caches.get(b'storage:' + address, {})
            subkeys = [utils.zpad(utils.coerce_to_bytes(kk), 32)
                       for kk in list(subcache.keys())]
            for k in list(d.keys()) + subkeys:
                v = d.get(k, None)
                v2 = subcache.get(big_endian_to_int(k), None)
                hexkey = b'0x' + encode_hex(utils.zunpad(k))
                if v2 is not None:
                    if v2 != 0:
                        med_dict['storage'][hexkey] = \
                            b'0x' + encode_hex(utils.int_to_big_endian(v2))
                elif v is not None:
                    med_dict['storage'][hexkey] = b'0x' + encode_hex(rlp.decode(v))

        return med_dict

    def reset_cache(self):
        """Reset cache and journal without commiting any changes."""
        self.caches = {
            'all': {},
            'balance': {},
            'nonce': {},
            'code': {},
            'storage': {},
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
            'journal_size': len(self.journal),
            'ether_delta': self.ether_delta
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
        self.logs = mysnapshot['logs']
        while len(self.logs) > mysnapshot['logs_size']:
            self.logs.pop()
        self.refunds = mysnapshot['refunds']
        self.state.root_hash = mysnapshot['state']
        self.gas_used = mysnapshot['gas']
        self.transactions = mysnapshot['txs']
        self.transaction_count = mysnapshot['txcount']
        self._get_transactions_cache = []
        self.ether_delta = mysnapshot['ether_delta']

    def initialize(self, parent):
        if self.number == self.config["METROPOLIS_FORK_BLKNUM"]:
            self.set_code(utils.normalize_address(self.config["METROPOLIS_STATEROOT_STORE"]), self.config["METROPOLIS_GETTER_CODE"])
            self.set_code(utils.normalize_address(self.config["METROPOLIS_BLOCKHASH_STORE"]), self.config["METROPOLIS_GETTER_CODE"])
        if self.number >= self.config["METROPOLIS_FORK_BLKNUM"]:
            self.set_storage_data(utils.normalize_address(self.config["METROPOLIS_STATEROOT_STORE"]),
                                  self.number % self.config["METROPOLIS_WRAPAROUND"],
                                  parent.state_root)
            self.set_storage_data(utils.normalize_address(self.config["METROPOLIS_BLOCKHASH_STORE"]),
                                  self.number % self.config["METROPOLIS_WRAPAROUND"],
                                  self.prevhash)
        if self.number == self.config['DAO_FORK_BLKNUM']:
            for acct in self.config['CHILD_DAO_LIST']:
                self.transfer_value(acct, self.config['DAO_WITHDRAWER'], self.get_balance(acct))

    def finalize(self):
        """Apply rewards and commit."""
        delta = int(self.config['BLOCK_REWARD'] + self.config['NEPHEW_REWARD'] * len(self.uncles))
        self.delta_balance(self.coinbase, delta)
        self.ether_delta += delta

        br = self.config['BLOCK_REWARD']
        udpf = self.config['UNCLE_DEPTH_PENALTY_FACTOR']

        for uncle in self.uncles:
            r = int(br * (udpf + uncle.number - self.number) // udpf)

            self.delta_balance(uncle.coinbase, r)
            self.ether_delta += r
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
        b = {"header": self.header.to_dict()}
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
                "medstate": encode_hex(receipt.state_root),
                "gas": to_string(receipt.gas_used),
                "logs": [Log.serialize(log) for log in receipt.logs],
                "bloom": utils.int256.serialize(receipt.bloom)
            })
        b["transactions"] = txlist
        if with_state:
            state_dump = {}
            for address, v in self.state.to_dict().items():
                state_dump[encode_hex(address)] = self.account_to_dict(address, with_storage_roots)
            b['state'] = state_dump
        if with_uncles:
            b['uncles'] = [self.__class__.deserialize_header(u)
                           for u in self.uncles]
        return b

    @property
    def mining_hash(self):
        return utils.sha3(rlp.encode(self.header,
                                     BlockHeader.exclude(['nonce', 'mixhash'])))

    def get_parent(self):
        """Get the parent of this block."""
        if self.number == 0:
            raise UnknownParentException('Genesis block has no parent')
        try:
            parent = get_block(self.env, self.prevhash)
        except KeyError:
            raise UnknownParentException(encode_hex(self.prevhash))
        # assert parent.state.db.db == self.state.db.db
        return parent

    def get_parent_header(self):
        """Get the parent of this block."""
        if self.number == 0:
            raise UnknownParentException('Genesis block has no parent')
        try:
            parent_header = get_block_header(self.db, self.prevhash)
        except KeyError:
            raise UnknownParentException(encode_hex(self.prevhash))
        # assert parent.state.db.db == self.state.db.db
        return parent_header

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
        elif b'difficulty:' + encode_hex(self.hash) in self.db:
            encoded = self.db.get(b'difficulty:' + encode_hex(self.hash))
            return utils.decode_int(encoded)
        else:
            o = self.difficulty + self.get_parent().chain_difficulty()
            # o += sum([uncle.difficulty for uncle in self.uncles])
            self.state.db.put_temporarily(
                b'difficulty:' + encode_hex(self.hash), utils.encode_int(o))
            return o

    def __eq__(self, other):
        """Two blocks are equal iff they have the same hash."""
        return isinstance(other, (Block, CachedBlock)) and self.hash == other.hash

    def __hash__(self):
        return big_endian_to_int(self.hash)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        return self.number > other.number

    def __lt__(self, other):
        return self.number < other.number

    def __repr__(self):
        return '<%s(#%d %s)>' % (self.__class__.__name__, self.number, encode_hex(self.hash)[:8])

    def __structlog__(self):
        return encode_hex(self.hash)


# Gas limit adjustment algo
def calc_gaslimit(parent):
    config = parent.config
    decay = parent.gas_limit // config['GASLIMIT_EMA_FACTOR']
    new_contribution = ((parent.gas_used * config['BLKLIM_FACTOR_NOM']) //
                        config['BLKLIM_FACTOR_DEN'] // config['GASLIMIT_EMA_FACTOR'])
    gl = max(parent.gas_limit - decay + new_contribution, config['MIN_GAS_LIMIT'])
    if gl < config['GENESIS_GAS_LIMIT']:
        gl2 = parent.gas_limit + decay
        gl = min(config['GENESIS_GAS_LIMIT'], gl2)
    assert check_gaslimit(parent, gl)
    return gl


def check_gaslimit(parent, gas_limit):
    config = parent.config
    #  block.gasLimit - parent.gasLimit <= parent.gasLimit // GasLimitBoundDivisor
    gl = parent.gas_limit // config['GASLIMIT_ADJMAX_FACTOR']
    a = bool(abs(gas_limit - parent.gas_limit) <= gl)
    b = bool(gas_limit >= config['MIN_GAS_LIMIT'])
    return a and b


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

    def __hash__(self):
        return big_endian_to_int(self.hash)

    @property
    def hash(self):
        if not self._hash_cached:
            self._hash_cached = super(CachedBlock, self).hash
        return self._hash_cached

    @classmethod
    def create_cached(cls, blk):
        blk.__class__ = CachedBlock
        log.debug('created cached block', blk=blk)
        return blk


def get_block_header(db, blockhash):
    assert isinstance(db, BaseDB)
    bh = BlockHeader.from_block_rlp(db.get(blockhash))
    if bh.hash != blockhash:
        log.warn('BlockHeader.hash is broken')
        assert bh.hash == blockhash

    return bh


@lru_cache(1024)
def get_block(env, blockhash):
    """
    Assumption: blocks loaded from the db are not manipulated
                -> can be cached including hash
    """
    assert isinstance(env, Env)
    blk = rlp.decode(env.db.get(blockhash), Block, env=env)
    return CachedBlock.create_cached(blk)


def genesis(env, **kwargs):
    """ Build the genesis block. """
    assert isinstance(env, Env)

    allowed_args = set([
        'start_alloc',
        'prevhash',
        'coinbase',
        'difficulty',
        'gas_limit',
        'timestamp',
        'extra_data',
        'mixhash',
        'nonce',
    ])

    assert set(kwargs.keys()).issubset(allowed_args)

    # https://ethereum.etherpad.mozilla.org/11
    start_alloc = kwargs.get('start_alloc', env.config['GENESIS_INITIAL_ALLOC'])
    header = BlockHeader(
        prevhash=kwargs.get('prevhash', env.config['GENESIS_PREVHASH']),
        uncles_hash=utils.sha3(rlp.encode([])),
        coinbase=kwargs.get('coinbase', env.config['GENESIS_COINBASE']),
        state_root=trie.BLANK_ROOT,
        tx_list_root=trie.BLANK_ROOT,
        receipts_root=trie.BLANK_ROOT,
        bloom=0,
        difficulty=kwargs.get('difficulty', env.config['GENESIS_DIFFICULTY']),
        number=0,
        gas_limit=kwargs.get('gas_limit', env.config['GENESIS_GAS_LIMIT']),
        gas_used=0,
        timestamp=kwargs.get('timestamp', 0),
        extra_data=kwargs.get('extra_data', env.config['GENESIS_EXTRA_DATA']),
        mixhash=kwargs.get('mixhash', env.config['GENESIS_MIXHASH']),
        nonce=kwargs.get('nonce', env.config['GENESIS_NONCE']),
    )
    block = Block(header, [], [], env=env)
    for addr, data in start_alloc.items():
        if len(addr) == 40:
            addr = decode_hex(addr)
        assert len(addr) == 20
        if 'wei' in data:
            block.set_balance(addr, utils.parse_int_or_hex(data['wei']))
        if 'balance' in data:
            block.set_balance(addr, utils.parse_int_or_hex(data['balance']))
        if 'code' in data:
            block.set_code(addr, utils.scanners['bin'](data['code']))
        if 'nonce' in data:
            block.set_nonce(addr, utils.parse_int_or_hex(data['nonce']))
        if 'storage' in data:
            for k, v in data['storage'].items():
                block.set_storage_data(addr, big_endian_to_int(decode_hex(k[2:])),
                                       big_endian_to_int(decode_hex(v[2:])))
    block.commit_state()
    block.state.db.commit()
    # genesis block has predefined state root (so no additional finalization
    # necessary)
    return block


def dump_genesis_block_tests_data(env):
    assert isinstance(env, Env)
    import json
    g = genesis(env)
    data = dict(
        genesis_state_root=encode_hex(g.state_root),
        genesis_hash=g.hex_hash(),
        genesis_rlp_hex=encode_hex(g.serialize()),
        initial_alloc=dict()
    )
    for addr, balance in env.config['GENESIS_INITIAL_ALLOC'].items():
        data['initial_alloc'][addr] = to_string(balance)

    print(json.dumps(data, indent=1))
