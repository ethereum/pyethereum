import rlp
from ethereum.utils import normalize_address, hash32, trie_root, \
    big_endian_int, address, int256, encode_hex, decode_hex, encode_int, sha3
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from ethereum import utils
from ethereum import trie
from ethereum.trie import Trie
from ethereum.securetrie import SecureTrie
from ethereum.config import default_config
from ethereum.transactions import Transaction
from ethereum.db import BaseDB
import sys
if sys.version_info.major == 2:
    from repoze.lru import lru_cache
else:
    from functools import lru_cache


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
        ('nonce', binary)
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

    @property
    def hash(self):
        """The binary block hash"""
        return utils.sha3(rlp.encode(self))

    @property
    def hex_hash(self):
        return encode_hex(self.hash)

    @property
    def mining_hash(self):
        return utils.sha3(rlp.encode(
            self, BlockHeader.exclude(['mixhash', 'nonce'])))

    @property
    def signing_hash(self):
        return utils.sha3(rlp.encode(
            self, BlockHeader.exclude(['extra_data'])))

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
            d[field] = utils.to_string(getattr(self, field))
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
        return utils.big_endian_to_int(self.hash)

    def __ne__(self, other):
        return not self.__eq__(other)


class Block(rlp.Serializable):

    """A block.

    All attributes from the block header are accessible via properties
    (i.e. ``block.prevhash`` is equivalent to ``block.header.prevhash``). It
    is ensured that no discrepancies between header and block occur.

    :param header: the block header
    :param transactions: a list of transactions which are replayed if the
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
        ('transactions', CountableList(Transaction)),
        ('uncles', CountableList(BlockHeader))
    ]

    def __init__(self, header, transactions=None, uncles=None, db=None):
        # assert isinstance(db, BaseDB), "No database object given"
        # self.db = db

        self.header = header
        self.transactions = transactions or []
        self.uncles = uncles or []
        self.uncles = list(self.uncles)

    def __getattribute__(self, name):
        try:
            return rlp.Serializable.__getattribute__(self, name)
        except AttributeError:
            return getattr(self.header, name)

    @property
    def transaction_count(self):
        return len(self.transactions)


BLANK_UNCLES_HASH = sha3(rlp.encode([]))


class FakeHeader():

    def __init__(self, hash=b'\x00' * 32, number=0, timestamp=0, difficulty=1,
                 gas_limit=3141592, gas_used=0, uncles_hash=BLANK_UNCLES_HASH):
        self.hash = hash
        self.number = number
        self.timestamp = timestamp
        self.difficulty = difficulty
        self.gas_limit = gas_limit
        self.gas_used = gas_used
        self.uncles_hash = uncles_hash

    def to_block_header(self):
        return BlockHeader(
            difficulty=self.difficulty,
            number=self.number,
            timestamp=self.timestamp,
            gas_used=self.gas_used,
            gas_limit=self.gas_limit,
            uncles_hash=self.uncles_hash
        )