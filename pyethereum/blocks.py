import time
import rlp
from rlp.sedes import BigEndianInt, big_endian_int, Binary, binary, CountableList, raw
import trie
import utils
from utils import address, int64, trie_root, hash_
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
GENESIS_COINBASE = "0" * 40
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
    """The state of an account."""

    fields = [
        ('nonce', big_endian_int),
        ('balance', big_endian_int),
        ('storage', trie_root),
        ('code', hash_)
    ]

    @classmethod
    def blank_account(cls):
        return cls(0, 0, trie.BLANK_ROOT, utils.sha3(''))


class Receipt(rlp.Serializable):

    fields = [
        ('state_root', trie_root),
        ('gas_used', big_endian_int),
        ('bloom', Binary(64)),
        ('logs', CountableList(raw))  # TODO: replace raw
    ]

    def __init__(self, state_root, gas_used, logs, bloom=None):
        super(Receipt, self).__init__(state_root, gas_used, bloom, logs)
        if bloom is not None and bloom != self.bloom:
            raise ValueError("Invalid bloom filter")

    @property
    def bloom(self):
        bloomtables = [x.bloomtables() for x in logs]
        return bloom.bloom_from_list(bloomtables)

    @bloom.setter
    def bloom(self, value):
        # bloom information will always be calculated from logs, but we need
        # to provide this setter to allow initialization from RLP
        pass


class BlockHeader(rlp.Serializable):

    fields = [
        ('prevhash', binary),
        ('uncles_hash', binary),
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
        ('nonce', binary)
    ]

    @property
    def hash(self):
        return utils.sha3(rlp.encode(self))

    def check_pow(self):
        """Check if the proof-of-work of the block is valid.

        :returns: `True` or `False`
        """
        rlp_Hn = rlp.encode(self, BlockHeader.exclude(['nonce']))
        assert len(self.nonce) == 32
        h = utils.sha3(utils.sha3(rlp_Hn) + self.nonce)
        return utils.big_endian_to_int(h) < 2 ** 256 / self.difficulty


class TransientBlock(rlp.Serializable):
    """A read only, non persistent, not validated representation of a block."""

    fields = [
        ('header', BlockHeader),
        ('transaction_list', CountableList(Transaction)),
        ('uncles', CountableList(BlockHeader))
    ]

    def __init__(self, header, transactions, uncles):
        super(TransientBlock, self).__init__(header, transactions, uncles)
        # mirror fields on header: this makes block.prevhash equivalent to
        # block.header.prevhash, etc.
        def make_getter(field):
            return lambda self_: getattr(self, field)
        def make_setter(field):
            return lambda self_, value: setattr(self, field, value)
        for field, _ in BlockHeader.fields:
            setattr(self, field, getattr(header, field))
            setattr(header.__class__, field, property(
                make_getter(field),
                make_setter(field)))

    @property
    def hash(self):
        return utils.sha3(rlp.encode(self.header))

    def __repr__(self):
        return '<TransientBlock(#%d %s)>' % (self.number,
                                             self.hash.encode('hex')[:8])

    def __structlog__(self):
        return self.hash.encode('hex')


class Block(TransientBlock):
    """The primary block class."""

    def __init__(self, header, transaction_list=[], uncles=[], db=None,
                 parent=None):
        # TransientBlock's init sets tx, receipts and state trie roots which
        # requires an existing database object
        self.db = db
        super(Block, self).__init__(header, transaction_list, uncles)

        self.suicides = []
        self.logs = []
        self.refunds = 0
        self.reset_cache()
        self.journal = []

        if not db:
            raise TypeError("No database object given")

        # if parent is given, check that this makes sense
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
                raise ValueError("Block's gaslimit does not result from its "
                                 "parent's gaslimit")
            if self.difficulty != calc_difficulty(parent, self.timestamp):
                raise ValueError("Block's difficulty does not result from its "
                                 "parent's difficulty")

        if self.number > 0:
            self.ancestors = [self]
        else:
            self.ancestors = [self] + [None] * 256

        # TODO: rewrite (seems to write account states to db)
        self.encoders = {}
        self.decoders = {}
        def encode_hash(v):
            '''encodes a bytearray into hash'''
            k = utils.sha3(v)
            self.db.put(k, v)
            return k
        self.encoders['hash'] = lambda v: encode_hash(v)
        self.decoders['hash'] = lambda k: self.db.get(k)

        # replay transactions if state is not known
        if len(self.state_root) != 32 and self.state_root in db:
            pass  # state root already in db
        elif self.prevhash == GENESIS_PREVHASH:
            pass  # genesis block
        else:
            print self.prevhash, GENESIS_PREVHASH
            # get parent from db if it hasn't been passed as keyword argument
            if not parent:
                try:
                    parent = get_block(db, self.prevhash)
                except KeyError:
                    encoded_hash = self.prevhash.encode('hex')
                    raise UnknownParentException(encoded_hash)
            # replay
            self.state_root = parent.state_root
            for tx in self.transaction_list:
                success, output = processblock.apply_transaction(block, tx)
            self.finalize()

        # TODO: handle SPV case (probably in BlockHeader class)

        # write transactions to the database
        for i, obj in enumerate(transaction_list):
            self.transactions.update(rlp.encode(i), rlp.encode(obj))
        self.transaction_count = len(transaction_list)

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
        if not self.transactions.root_hash_valid():
            raise ValueError("Transactions root of block %r not found in "
                             "database" % self)
        if self.header.tx_list_root != self.transactions.root_hash:
            raise ValueError("Transaction list root hash does not match")
        if all((not self.is_genesis(), self.header.nonce,
                not self.header.check_pow())):
            raise ValueError("PoW check failed")

        # make sure we are all on the same db
        # TODO: can this fail at all?
        assert self.state.db.db == self.transactions.db.db == self.db.db


    @classmethod
    def init_from_header(cls, rlpdata):
        """Create a block without specifying transactions or uncles."""
        header = rlp.decode(rlpdata, BlockHeader)
        return cls(header, [], [])

    def check_fields(self):
        """Check that the values of all fields are well formed."""
        # serialize and deserialize and check that the values didn't change
        l = Block.serialize(self)
        return rlp.decode(rlp.encode(l)) == l

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
        ineligible.extend([b.list_header() for b in ancestor_chain])
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

        The result will also be cached in :attr:`ancestor_list`.
        
        :returns: a list [self, p(self), p(p(self)), ..., p^n(self)]
        """
        # TODO: why 256 Nones?
        if self.number == 0:
            self.ancestors = [self] + [None] * 256
        elif len(self.ancestors) <= n:
            first_unknown = self.ancestors[-1].getparent()
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
        rlpdata = self.state.get(address)
        if rlpdata != trie.BLANK_NODE:
            return rlp.decode(rlpdata, Account)
        else:
            return Account.blank_account()

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
        return Receipt(
                self.state_root,
                self.gas_used,
                tx.log_bloom64(),
                [x.serialize() for x in tx.logs]
        )

    def add_transaction_to_list(self, tx):
        """Add a transaction to the transaction trie."""
        k = rlp.encode(utils.encode_int(self.transaction_count))
        self.transactions.update(k, tx.serialize())
        r = self.mk_transaction_receipt(tx)
        self.receipts.update(k, r.serialize())
        self.bloom |= r.log_bloom()  # int
        self.transaction_count += 1

    def get_transaction(self, num):
        """Get the `num`th transaction in this block."""
        index = rlp.encode(utils.encode_int(num))
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
        CACHE_KEY = 'storage:'+address
        if CACHE_KEY in self.caches:
            if index in self.caches[CACHE_KEY]:
                return self.caches[CACHE_KEY][index]
        key = utils.zpad(utils.coerce_to_bytes(index), 32)
        val = rlp.decode(self.get_storage(address).get(key))
        return utils.big_endian_to_int(val) if val else 0

    def set_storage_data(self, address, index, value):
        """Set a specific item in the storage of an account.
        
        :param address: the address of the account (binary or hex string)
        :param index: the index of the item in the storage
        :param value: the new value of the item
        """
        CACHE_KEY = 'storage:'+address
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
            for field, _ in Account.fields:
                if field == 'storage':
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
                else:
                    if address in self.caches[field]:
                        v = self.caches[field].get(address, default)
                        setattr(acct, field, v)
            self.state.update(address.decode('hex'), rlp.encode(acct))
        log_state.trace('delta', changes=changes)
        self.reset_cache()

    def del_account(self, address):
        """Delete an account.
        
        :param address: the address of the account (binary or hex string)
        """
        self.commit_state()
        if len(address) == 40:
            address = address.decode('hex')
        self.state.delete(address)

    def account_to_dict(self, address, with_storage_root=False,
                        with_storage=True, for_vmtest=False):
        if with_storage_root:
            assert len(self.journal) == 0
        med_dict = {}
        for i, val in enumerate(self.get_acct(address)):
            name, typ, default = acct_structure[i]
            key = acct_structure[i][0]
            if name == 'storage':
                strie = trie.Trie(self.db, val)
                if with_storage_root:
                    med_dict['storage_root'] = strie.get_root_hash().encode('hex')
            else:
                med_dict[key] = utils.printers[typ](self.caches[key].get(address, val))
        if with_storage:
            med_dict['storage'] = {}
            d = strie.to_dict()
            subcache = self.caches.get('storage:' + address, {})
            subkeys = [utils.zpad(utils.coerce_to_bytes(kk), 32) for kk in subcache.keys()]
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
        """Reset the cache and the journal without commiting any changes."""
        self.caches = {
            'all': {},
            'balance': {},
            'nonce': {},
            'code': {},
        }
        self.journal = []

    # Revert computation
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
        """Apply rewards and commit.

        TODO: update comment
        We raise the block's coinbase account by Rb, the block reward, and the
        coinbase of each uncle by 7 of 8 that. Rb = 1500 finney
        """
        self.delta_balance(self.coinbase,
                           BLOCK_REWARD + NEPHEW_REWARD * len(self.uncles))
        for uncle in self.uncles:
            self.delta_balance(uncle.coinbase, UNCLE_REWARD)
        self.commit_state()

    def to_dict(self, with_state=False, full_transactions=False,
                with_storage_roots=False, with_uncles=False):
        """
        serializes the block
        with_state:             include state for all accounts
        full_transactions:      include serialized tx (hashes otherwise)
        with_uncles:            include uncle hashes
        """
        b = {}
        for name, typ, default in block_structure:
            b[name] = utils.printers[typ](getattr(self, name))
        txlist = []
        for i in range(self.transaction_count):
            tx_rlp = self.transactions.get(rlp.encode(utils.encode_int(i)))
            tx = rlp.decode(tx_rlp)
            receipt_rlp = self.receipts.get(rlp.encode(utils.encode_int(i)))
            msr, gas, mybloom, mylogs = rlp.decode(receipt_rlp)
            if full_transactions:
                txjson = transactions.Transaction.create(tx).to_dict()
            else:
                # tx hash
                txjson = utils.sha3(rlp.descend(tx_rlp, 0)).encode('hex')
            txlist.append({
                "tx": txjson,
                "medstate": msr.encode('hex'),
                "gas": str(utils.decode_int(gas)),
                "logs": mylogs,
                "bloom": mybloom.encode('hex')
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
        elif 'difficulty:' + self.hex_hash() in self.state.db:
            encoded = self.state.db.get('difficulty:' + self.hex_hash())
            return utils.decode_int(encoded)
        else:
            o = self.difficulty + self.get_parent().chain_difficulty()
            o += sum([uncle.difficulty for uncle in uncles])
            self.state.db.put('difficulty:' + self.hex_hash(),
                              utils.encode_int(o))
            return o

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
            self._hash_cached = Block._hash(self)
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
    blk = Block.deserialize(db, db.get(blockhash))
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
    block = Block(header, db=db)
    for addr, balance in start_alloc.iteritems():
        block.set_balance(addr, balance)
    block.state.db.commit()
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
