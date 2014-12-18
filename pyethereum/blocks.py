import time
import rlp
import trie
import utils
import processblock
import transactions
import bloom
import copy
import sys
from repoze.lru import lru_cache
from exceptions import *
from pyethereum.slogging import get_logger
log = get_logger('eth.block')
log_state = get_logger('eth.msg.state')


INITIAL_DIFFICULTY = 2 ** 17
GENESIS_PREVHASH = '\00' * 32
GENESIS_COINBASE = "0" * 40
GENESIS_NONCE = utils.sha3(chr(42))
GENESIS_GAS_LIMIT = 10 ** 6
MIN_GAS_LIMIT = 125000
GASLIMIT_EMA_FACTOR = 1024
BLOCK_REWARD = 1500 * utils.denoms.finney
UNCLE_REWARD = 15 * BLOCK_REWARD / 16
NEPHEW_REWARD = BLOCK_REWARD / 32
BLOCK_DIFF_FACTOR = 1024
GENESIS_MIN_GAS_PRICE = 0
BLKLIM_FACTOR_NOM = 6
BLKLIM_FACTOR_DEN = 5
DIFF_ADJUSTMENT_CUTOFF = 5

RECORDING = 1
NONE = 0
VERIFYING = -1

GENESIS_INITIAL_ALLOC = \
    {"51ba59315b3a95761d0863b05ccc7a7f54703d99": 2 ** 200,  # (G)
     "e6716f9544a56c530d868e4bfbacb172315bdead": 2 ** 200,  # (J)
     "b9c015918bdaba24b4ff057a92a3873d6eb201be": 2 ** 200,  # (V)
     "1a26338f0d905e295fccb71fa9ea849ffa12aaf4": 2 ** 200,  # (A)
     "2ef47100e0787b915105fd5e3f4ff6752079d5cb": 2 ** 200,  # (M)
     "cd2a3d9f938e13cd947ec05abc7fe734df8dd826": 2 ** 200,  # (R)
     "6c386a4b26f73c802f34673f7248bb118f97424a": 2 ** 200,  # (HH)
     "e4157b34ea9615cfbde6b4fda419828124b70c78": 2 ** 200,  # (CH)
     }

block_structure = [
    ["prevhash", "bin", "\00" * 32],
    ["uncles_hash", "bin", utils.sha3rlp([])],
    ["coinbase", "addr", GENESIS_COINBASE],
    ["state_root", "trie_root", trie.BLANK_ROOT],
    ["tx_list_root", "trie_root", trie.BLANK_ROOT],
    ["receipts_root", "trie_root", trie.BLANK_ROOT],
    ["bloom", "int64", 0],
    ["difficulty", "int", INITIAL_DIFFICULTY],
    ["number", "int", 0],
    ["gas_limit", "int", GENESIS_GAS_LIMIT],
    ["gas_used", "int", 0],
    ["timestamp", "int", 0],
    ["extra_data", "bin", ""],
    ["nonce", "bin", ""],
]

block_structure_rev = {}
for i, (name, typ, default) in enumerate(block_structure):
    block_structure_rev[name] = [i, typ, default]

acct_structure = [
    ["nonce", "int", 0],
    ["balance", "int", 0],
    ["storage", "trie_root", trie.BLANK_ROOT],
    ["code", "hash", ""],
]


acct_structure_rev = {}
for i, (name, typ, default) in enumerate(acct_structure):
    acct_structure_rev[name] = [i, typ, default]


def calc_difficulty(parent, timestamp):
    offset = parent.difficulty / BLOCK_DIFF_FACTOR
    sign = 1 if timestamp - parent.timestamp < DIFF_ADJUSTMENT_CUTOFF else -1
    return parent.difficulty + offset * sign


def calc_gaslimit(parent):
    prior_contribution = parent.gas_limit * (GASLIMIT_EMA_FACTOR - 1)
    new_contribution = parent.gas_used * BLKLIM_FACTOR_NOM / BLKLIM_FACTOR_DEN
    gl = (prior_contribution + new_contribution) / GASLIMIT_EMA_FACTOR
    return max(gl, MIN_GAS_LIMIT)


def must_equal(what, a, b):
    if a != b:
        raise VerificationFailed(what, a, '==', b)


class TransientBlock(object):

    """
    Read only, non persisted, not validated representation of a block
    """

    def __init__(self, rlpdata):
        self.rlpdata = rlpdata
        self.header_args, transaction_list, uncles = rlp.decode(rlpdata)
        self.hash = utils.sha3(rlp.encode(self.header_args))
        self.transaction_list = transaction_list  # rlp encoded transactions
        self.uncles = uncles
        for i, (name, typ, default) in enumerate(block_structure):
            setattr(self, name, utils.decoders[typ](self.header_args[i]))

    def __repr__(self):
        return '<TransientBlock(#%d %s)>' % (self.number, self.hash.encode('hex')[:8])


def check_header_pow(header):
    rlp_Hn = rlp.encode(header[:-1])
    nonce = header[-1]
    assert len(nonce) == 32
    diff = utils.decoders['int'](header[block_structure_rev['difficulty'][0]])
    h = utils.sha3(utils.sha3(rlp_Hn) + nonce)
    return utils.big_endian_to_int(h) < 2 ** 256 / diff


class Block(object):

    def __init__(self,
                 db,
                 prevhash='\00' * 32,
                 uncles_hash=block_structure_rev['uncles_hash'][2],
                 coinbase=block_structure_rev['coinbase'][2],
                 state_root=trie.BLANK_ROOT,
                 tx_list_root=trie.BLANK_ROOT,
                 receipts_root=trie.BLANK_ROOT,
                 bloom=0,
                 difficulty=block_structure_rev['difficulty'][2],
                 number=0,
                 gas_limit=block_structure_rev['gas_limit'][2],
                 gas_used=0, timestamp=0, extra_data='', nonce='',
                 transaction_list=[],
                 uncles=[],
                 header=None):

        self.db = db
        self.prevhash = prevhash
        self.uncles_hash = uncles_hash
        self.coinbase = coinbase
        self.difficulty = difficulty
        self.number = number
        self.gas_limit = gas_limit
        self.gas_used = gas_used
        self.timestamp = timestamp
        self.extra_data = extra_data
        self.nonce = nonce
        self.uncles = uncles
        self.suicides = []
        self.logs = []
        self.refunds = 0
        self.caches = {
            'balance': {},
            'nonce': {},
            'code': {},
            'all': {}
        }
        self.journal = []

        self.transactions = trie.Trie(self.db, tx_list_root)
        self.receipts = trie.Trie(self.db, receipts_root)
        self.transaction_count = 0

        self.state = trie.Trie(self.db, state_root)
        self.bloom = bloom  # int

        # setup de/encoders
        self.encoders = dict(utils.encoders)
        self.decoders = dict(utils.decoders)
        def encode_hash(v):
            '''encodes a bytearray into hash'''
            k = utils.sha3(v)
            self.db.put(k, v)
            return k
        self.encoders['hash'] = lambda v: encode_hash(v)
        self.decoders['hash'] = lambda k: self.db.get(k)



        # If transaction_list is None, then it's a block header imported for
        # SPV purposes
        if transaction_list is not None:
            # support init with transactions only if state is known
            assert self.state.root_hash_valid()
            for i, obj in enumerate(transaction_list):
                self.transactions.update(rlp.encode(utils.encode_int(i)),
                                         rlp.encode(obj))
                self.transaction_count = len(transaction_list)
            if tx_list_root != self.transactions.root_hash:
                raise Exception("Transaction list root hash does not match!")
            if not self.is_genesis() and self.nonce and\
                    not check_header_pow(header or self.list_header()):
                raise Exception("PoW check failed")

        # make sure we are all on the same db
        assert self.state.db.db == self.transactions.db.db == self.db.db

        # use de/encoders to check type and validity
        for name, typ, d in block_structure:
            v = getattr(self, name)
            assert self.decoders[typ](self.encoders[typ](v)) == v

        # Basic consistency verifications
        if not self.state.root_hash_valid():
            raise Exception(
                "State Merkle root not found in database! %r" % self)
        if not self.transactions.root_hash_valid():
            raise Exception(
                "Transactions root not found in database! %r" % self)
        if len(self.extra_data) > 1024:
            raise Exception("Extra data cannot exceed 1024 bytes")
        if self.coinbase == '':
            raise Exception("Coinbase cannot be empty address")

    def validate_uncles(self):
        if utils.sha3rlp(self.uncles) != self.uncles_hash:
            return False
        # Check uncle validity
        ancestor_chain = [self]
        # Uncle can have a block from 2-7 blocks ago as its parent
        for i in [1, 2, 3, 4, 5, 6, 7]:
            if ancestor_chain[-1].number > 0:
                ancestor_chain.append(ancestor_chain[-1].get_parent())
        ineligible = []
        # Uncles of this block cannot be direct ancestors and cannot also
        # be uncles included 1-6 blocks ago
        for ancestor in ancestor_chain[1:]:
            ineligible.extend(ancestor.uncles)
        ineligible.extend([b.list_header() for b in ancestor_chain])
        eligible_ancestor_hashes = [x.hash for x in ancestor_chain[2:]]
        for uncle in self.uncles:
            if not check_header_pow(uncle):
                return False
            prevhash = uncle[block_structure_rev['prevhash'][0]]
            if prevhash not in eligible_ancestor_hashes:
                log.error("Uncle does not have a valid ancestor", block=self)
                return False
            if uncle in ineligible:
                log.error("Duplicate uncle", block=self, uncle=utils.sha3(
                    rlp.encode(uncle)).encode('hex'))
                return False
            ineligible.append(uncle)
        return True

    def is_genesis(self):
        return self.prevhash == GENESIS_PREVHASH and \
            self.nonce == GENESIS_NONCE

    def check_proof_of_work(self, nonce):
        H = self.list_header()
        H[-1] = nonce
        return check_header_pow(H)

    @classmethod
    def deserialize_header(cls, header_data):
        if isinstance(header_data, (str, unicode)):
            header_data = rlp.decode(header_data)
        assert len(header_data) == len(block_structure)
        kargs = {}
        # Deserialize all properties
        for i, (name, typ, default) in enumerate(block_structure):
            kargs[name] = utils.decoders[typ](header_data[i])
        return kargs

    @classmethod
    def deserialize(cls, db, rlpdata):
        header_args, transaction_list, uncles = rlp.decode(rlpdata)
        kargs = cls.deserialize_header(header_args)
        kargs['header'] = header_args
        kargs['transaction_list'] = transaction_list
        kargs['uncles'] = uncles

        # if we don't have the state we need to replay transactions
        if len(kargs['state_root']) == 32 and kargs['state_root'] in db:
            return Block(db=db, **kargs)
        elif kargs['prevhash'] == GENESIS_PREVHASH:
            return Block(db=db, **kargs)
        else:  # no state, need to replay
            try:
                parent = get_block(db, kargs['prevhash'])
            except KeyError:
                raise UnknownParentException(kargs['prevhash'].encode('hex'))
            return parent.deserialize_child(rlpdata)

    @classmethod
    def init_from_header(cls, db, rlpdata):
        kargs = cls.deserialize_header(rlpdata)
        kargs['transaction_list'] = None
        kargs['uncles'] = None
        return Block(db=db, **kargs)

    def deserialize_child(self, rlpdata):
        """
        deserialization w/ replaying transactions
        """
        header_args, transaction_list, uncles = rlp.decode(rlpdata)
        assert len(header_args) == len(block_structure)
        kargs = dict(transaction_list=transaction_list, uncles=uncles)
        # Deserialize all properties
        for i, (name, typ, default) in enumerate(block_structure):
            kargs[name] = self.decoders[typ](header_args[i])

        block = Block.init_from_parent(self, kargs['coinbase'],
                                       extra_data=kargs['extra_data'],
                                       timestamp=kargs['timestamp'],
                                       uncles=uncles)

        # bloom_bits_expected = bloom.bits_in_number(kargs['bloom'])
        # replay transactions
        for tx_lst_serialized in transaction_list:
            tx = transactions.Transaction.create(tx_lst_serialized)
            success, output = processblock.apply_transaction(block, tx)

        block.finalize()

        block.uncles_hash = kargs['uncles_hash']
        block.nonce = kargs['nonce']

        # checks
        must_equal('prev_hash', block.prevhash, self.hash)
        must_equal('gas_used', block.gas_used, kargs['gas_used'])
        must_equal('gas_limit', block.gas_limit,  kargs['gas_limit'])
        must_equal('timestamp', block.timestamp, kargs['timestamp'])
        must_equal('difficulty', block.difficulty, kargs['difficulty'])
        must_equal('number', block.number, kargs['number'])
        must_equal('extra_data', block.extra_data, kargs['extra_data'])
        must_equal('uncles', utils.sha3rlp(block.uncles), kargs['uncles_hash'])
        must_equal('state_root', block.state.root_hash, kargs['state_root'])
        must_equal('tx_list_root', block.tx_list_root, kargs['tx_list_root'])
        # bloom_bits = bloom.bits_in_number(block.bloom)
        # bloom_bits_expected = bloom.bits_in_number(kargs['bloom'])
        # print 'computed', bloom_bits
        # print 'expected', bloom_bits_expected
        # print 'missing', sorted(set(bloom_bits_expected) - set(bloom_bits))
        # print 'wrong', sorted(set(bloom_bits) - set(bloom_bits_expected))
        must_equal('bloom', block.bloom, kargs['bloom'])
        must_equal('receipts_root', block.receipts.root_hash, kargs['receipts_root'])
        if not check_header_pow(block.list_header()):
            raise VerificationFailed('invalid nonce')

        return block

    @classmethod
    def hex_deserialize(cls, db,  hexrlpdata):
        return cls.deserialize(db, hexrlpdata.decode('hex'))

    def mk_blank_acct(self):
        if not hasattr(self, '_blank_acct'):
            codehash = utils.sha3('')
            self.state.db.put(utils.sha3(''), '')
            self._blank_acct = [utils.encode_int(0),
                                utils.encode_int(0),
                                trie.BLANK_ROOT,
                                codehash]
        return self._blank_acct[:]

    def get_acct(self, address):
        if len(address) == 40:
            address = address.decode('hex')
        acct = rlp.decode(self.state.get(address)) or self.mk_blank_acct()
        return tuple(self.decoders[t](acct[i])
                     for i, (n, t, d) in enumerate(acct_structure))

    # _get_acct_item(bin or hex, int) -> bin
    def _get_acct_item(self, address, param):
        ''' get account item
        :param address: account address, can be binary or hex string
        :param param: parameter to get
        '''
        if param != 'storage':
            if address in self.caches[param]:
                return self.caches[param][address]
            else:
                o = self.get_acct(address)[acct_structure_rev[param][0]]
                self.caches[param][address] = o
                return o
        return self.get_acct(address)[acct_structure_rev[param][0]]

    # _set_acct_item(bin or hex, int, bin)
    def _set_acct_item(self, address, param, value):
        ''' set account item
        :param address: account address, can be binary or hex string
        :param param: parameter to set
        :param value: new value
        '''
        self.set_and_journal(param, address, value)
        self.set_and_journal('all', address, True)

    def set_and_journal(self, cache, index, value):
        prev = self.caches[cache].get(index, None)
        if prev != value:
            self.journal.append([cache, index, prev, value])
            self.caches[cache][index] = value

    # _delta_item(bin or hex, int, int) -> success/fail
    def _delta_item(self, address, param, value):
        ''' add value to account item
        :param address: account address, can be binary or hex string
        :param param: parameter to increase/decrease
        :param value: can be positive or negative
        '''
        value = self._get_acct_item(address, param) + value
        if value < 0:
            return False
        self._set_acct_item(address, param, value)
        return True

    def mk_transaction_receipt(self, tx):
        o = [
            self.state_root,
            utils.encode_int(self.gas_used),
            tx.log_bloom_b64(),
            [x.serialize() for x in tx.logs]
        ]
        return rlp.encode(o)

    def add_transaction_to_list(self, tx):
        k = rlp.encode(utils.encode_int(self.transaction_count))
        self.transactions.update(k, tx.serialize())
        self.receipts.update(k, self.mk_transaction_receipt(tx))
        self.bloom |= tx.log_bloom()  # int
        # print "newbits", bloom.bits_in_number(tx.log_bloom())
        # for log in tx.logs:q
        #     print 'log', log.address, log.topics
        #     print [bloom.bits_in_number(bloom.bloom(x)) for x in log.bloomables()]
        self.transaction_count += 1

    def _list_transactions(self):
        txlist = []
        for i in range(self.transaction_count):
            txlist.append(self.get_transaction(i))
        return txlist

    def get_transaction(self, num):
        return rlp.decode(self.transactions.get(rlp.encode(utils.encode_int(num))))

    def get_transactions(self):
        return [transactions.Transaction.create(tx) for
                tx in self._list_transactions()]

    def get_receipt(self, num):
        # returns [tx_lst_serialized, state_root, gas_used_encoded]
        return rlp.decode(self.receipts.get(rlp.encode(utils.encode_int(num))))

    def get_nonce(self, address):
        return self._get_acct_item(address, 'nonce')

    def set_nonce(self, address, value):
        return self._set_acct_item(address, 'nonce', value)

    def increment_nonce(self, address):
        return self._delta_item(address, 'nonce', 1)

    def decrement_nonce(self, address):
        return self._delta_item(address, 'nonce', -1)

    def get_balance(self, address):
        return self._get_acct_item(address, 'balance')

    def set_balance(self, address, value):
        self._set_acct_item(address, 'balance', value)

    def delta_balance(self, address, value):
        return self._delta_item(address, 'balance', value)

    def transfer_value(self, from_addr, to_addr, value):
        assert value >= 0
        if self.delta_balance(from_addr, -value):
            return self.delta_balance(to_addr, value)
        return False

    def get_code(self, address):
        return self._get_acct_item(address, 'code')

    def set_code(self, address, value):
        self._set_acct_item(address, 'code', value)

    def get_storage(self, address):
        storage_root = self._get_acct_item(address, 'storage')
        return trie.Trie(self.db, storage_root)

    def get_storage_data(self, address, index):
        CACHE_KEY = 'storage:'+address
        if CACHE_KEY in self.caches:
            if index in self.caches[CACHE_KEY]:
                return self.caches[CACHE_KEY][index]
        key = utils.zpad(utils.coerce_to_bytes(index), 32)
        val = rlp.decode(self.get_storage(address).get(key))
        return utils.big_endian_to_int(val) if val else 0

    def set_storage_data(self, address, index, val):
        CACHE_KEY = 'storage:'+address
        if CACHE_KEY not in self.caches:
            self.caches[CACHE_KEY] = {}
            self.set_and_journal('all', address, True)
        self.set_and_journal(CACHE_KEY, index, val)

    def commit_state(self):
        changes = []
        if not len(self.journal):
            log_state.trace('delta', changes=[])
            return
        for address in self.caches['all']:
            acct = rlp.decode(self.state.get(address.decode('hex'))) \
                or self.mk_blank_acct()
            for i, (key, typ, default) in enumerate(acct_structure):
                if key == 'storage':
                    t = trie.Trie(self.db, acct[i])
                    for k, v in self.caches.get('storage:' + address, {}).iteritems():
                        enckey = utils.zpad(utils.coerce_to_bytes(k), 32)
                        val = rlp.encode(utils.int_to_big_endian(v))
                        changes.append(['storage', address, k, v])
                        if v:
                            t.update(enckey, val)
                        else:
                            t.delete(enckey)
                    acct[i] = t.root_hash
                else:
                    if address in self.caches[key]:
                        v = self.caches[key].get(address, default)
                        changes.append([key, address, v])
                        acct[i] = self.encoders[acct_structure[i][1]](v)
            self.state.update(address.decode('hex'), rlp.encode(acct))
        log_state.trace('delta', changes=changes)
        self.reset_cache()

    def del_account(self, address):
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
        self.caches = {
            'all': {},
            'balance': {},
            'nonce': {},
            'code': {},
        }
        self.journal = []

    # Revert computation
    def snapshot(self):
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
        while len(self.suicides) > mysnapshot['logs_size']:
            self.logs.pop()
        self.refunds = mysnapshot['refunds']
        self.state.root_hash = mysnapshot['state']
        self.gas_used = mysnapshot['gas']
        self.transactions = mysnapshot['txs']
        self.transaction_count = mysnapshot['txcount']

    def finalize(self):
        """
        Apply rewards
        We raise the block's coinbase account by Rb, the block reward,
        and the coinbase of each uncle by 7 of 8 that.
        Rb = 1500 finney
        """
        self.delta_balance(self.coinbase,
                           BLOCK_REWARD + NEPHEW_REWARD * len(self.uncles))
        for uncle_rlp in self.uncles:
            uncle_data = Block.deserialize_header(uncle_rlp)
            self.delta_balance(uncle_data['coinbase'], UNCLE_REWARD)
        self.commit_state()

    def serialize_header_without_nonce(self):
        return rlp.encode(self.list_header(exclude=['nonce']))

    def get_state_root(self):
        self.commit_state()
        return self.state.root_hash

    def set_state_root(self, state_root_hash):
        self.state = trie.Trie(self.db, state_root_hash)
        self.reset_cache()

    state_root = property(get_state_root, set_state_root)

    def get_tx_list_root(self):
        return self.transactions.root_hash

    tx_list_root = property(get_tx_list_root)

    def get_receipts_root(self):
        return self.receipts.root_hash

    receipts_root = property(get_receipts_root)

    def list_header(self, exclude=[]):
        header = []
        for name, typ, default in block_structure:
            # print name, typ, default , getattr(self, name)
            if name not in exclude:
                header.append(self.encoders[typ](getattr(self, name)))
        return header

    def serialize(self):
        # Serialization method; should act as perfect inverse function of the
        # constructor assuming no verification failures
        return rlp.encode([self.list_header(),
                           self._list_transactions(),
                           self.uncles])

    def hex_serialize(self):
        return self.serialize().encode('hex')

    def serialize_header(self):
        return rlp.encode(self.list_header())

    def hex_serialize_header(self):
        return rlp.encode(self.list_header()).encode('hex')

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

    def _hash(self):
        return utils.sha3(self.serialize_header())

    @property
    def hash(self):
        return self._hash()

    def hex_hash(self):
        return self.hash.encode('hex')

    def get_parent(self):
        if self.number == 0:
            raise UnknownParentException('Genesis block has no parent')
        try:
            parent = get_block(self.db, self.prevhash)
        except KeyError:
            raise UnknownParentException(self.prevhash.encode('hex'))
        # assert parent.state.db.db == self.state.db.db
        return parent

    def has_parent(self):
        try:
            self.get_parent()
            return True
        except UnknownParentException:
            return False

    def chain_difficulty(self):
        # calculate the summarized_difficulty
        if self.is_genesis():
            return self.difficulty
        elif 'difficulty:' + self.hex_hash() in self.state.db:
            return utils.decode_int(
                self.state.db.get('difficulty:' + self.hex_hash()))
        else:
            _idx, _typ, _ = block_structure_rev['difficulty']
            o = self.difficulty + self.get_parent().chain_difficulty()
            o += sum([self.decoders[_typ](u[_idx]) for u in self.uncles])
            self.state.db.put('difficulty:' + self.hex_hash(), utils.encode_int(o))
            return o

    def __eq__(self, other):
        return isinstance(other, (Block, CachedBlock)) and self.hash == other.hash

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        return self.number > other.number

    def __lt__(self, other):
        return self.number < other.number

    def __repr__(self):
        return '<Block(#%d %s)>' % (self.number, self.hex_hash()[:8])

    @classmethod
    def init_from_parent(cls, parent, coinbase, extra_data='',
                         timestamp=int(time.time()), uncles=[]):
        return Block(
            db = parent.db,
            prevhash=parent.hash,
            uncles_hash=utils.sha3rlp(uncles),
            coinbase=coinbase,
            state_root=parent.state.root_hash,
            tx_list_root=trie.BLANK_ROOT,
            receipts_root=trie.BLANK_ROOT,
            bloom=0,
            difficulty=calc_difficulty(parent, timestamp),
            number=parent.number + 1,
            gas_limit=calc_gaslimit(parent),
            gas_used=0,
            timestamp=timestamp,
            extra_data=extra_data,
            nonce='',
            transaction_list=[],
            uncles=uncles)


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

    def _hash(self):
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


def genesis(db, start_alloc=GENESIS_INITIAL_ALLOC, difficulty=INITIAL_DIFFICULTY):
    # https://ethereum.etherpad.mozilla.org/11
    block = Block(db=db, prevhash=GENESIS_PREVHASH, coinbase=GENESIS_COINBASE,
                  tx_list_root=trie.BLANK_ROOT,
                  difficulty=difficulty, nonce=GENESIS_NONCE,
                  gas_limit=GENESIS_GAS_LIMIT)
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
