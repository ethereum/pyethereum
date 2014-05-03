import time
import rlp
import trie
import db
import utils
import processblock
import transactions

# to add EMPTY_UNCLE_HASH / GENESIS_DEFAULTS ...

INITIAL_DIFFICULTY = 2 ** 22
BLOCK_REWARD = 10 ** 18
BLOCK_DIFF_FACTOR = 1024
GASLIMIT_EMA_FACTOR = 1024
BLKLIM_FACTOR_NOM = 6
BLKLIM_FACTOR_DEN = 5

block_structure = [
    ["prevhash", "bin", ""],
    ["uncles_hash", "bin", utils.sha3(rlp.encode([]))],
    ["coinbase", "addr", "0" * 40],
    ["state_root", "trie_root", ''],
    ["tx_list_root", "trie_root", ''],
    ["difficulty", "int", 2 ** 23],
    ["number", "int", 0],
    ["min_gas_price", "int", 10 ** 15],
    ["gas_limit", "int", 10 ** 6],
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
    ["code", "bin", ""],
    ["storage", "trie_root", ""],
]

acct_structure_rev = {}
for i, (name, typ, default) in enumerate(acct_structure):
    acct_structure_rev[name] = [i, typ, default]


def calc_difficulty(parent, timestamp):
    offset = parent.difficulty / BLOCK_DIFF_FACTOR
    sign = 1 if timestamp - parent.timestamp < 42 else -1
    return parent.difficulty + offset * sign


def calc_gaslimit(parent):
    prior_contribution = parent.gas_limit * (GASLIMIT_EMA_FACTOR - 1)
    new_contribution = parent.gas_used * BLKLIM_FACTOR_NOM / BLKLIM_FACTOR_DEN
    return (prior_contribution + new_contribution) / GASLIMIT_EMA_FACTOR


class Block(object):

    def __init__(self,
                 prevhash='',
                 uncles_hash=block_structure_rev['uncles_hash'][2],
                 coinbase=block_structure_rev['coinbase'][2],
                 state_root='',
                 tx_list_root='',
                 difficulty=block_structure_rev['difficulty'][2],
                 number=0,
                 min_gas_price=block_structure_rev['min_gas_price'][2],
                 gas_limit=block_structure_rev['gas_limit'][2],
                 gas_used=0, timestamp=0, extra_data='', nonce='',
                 transaction_list=[],
                 uncles=[]):

        self.prevhash = prevhash
        self.uncles_hash = uncles_hash
        self.coinbase = coinbase
        self.difficulty = difficulty
        self.number = number
        self.min_gas_price = min_gas_price
        self.gas_limit = gas_limit
        self.gas_used = gas_used
        self.timestamp = timestamp
        self.extra_data = extra_data
        self.nonce = nonce
        self.uncles = uncles

        self.transactions = trie.Trie(utils.get_db_path())
        self.transaction_count = 0

        # replay changes to agree on state

        # if not self.is_genesis():
        #     self.state = trie.Trie(
        #         utils.get_db_path(), self.get_parent().state_root)
        #     self.finalize()
        # else:
        #     self.state = trie.Trie(utils.get_db_path(), state_root)

        self.state = trie.Trie(utils.get_db_path(), state_root)
        # Fill in nodes for transaction trie
        for tx_serialized, state_root, gas_used_encoded in transaction_list:
            self._add_transaction_to_list(
                tx_serialized, state_root, gas_used_encoded)
        # for tx in self.get_transactions():
        #     self.apply_transaction(tx)


        # make sure we are all on the same db
        assert self.state.db.db == self.transactions.db.db

        # Basic consistency verifications
        if len(self.state.root) == 32 and \
                not self.state.db.has_key(self.state.root):
            raise Exception(
                "State Merkle root not found in database! %r" % self)
        if tx_list_root != self.transactions.root:
            raise Exception("Transaction list root hash does not match!")
        if utils.sha3(rlp.encode(self.uncles)) != self.uncles_hash:
            raise Exception("Uncle root hash does not match!")
        if len(self.extra_data) > 1024:
            raise Exception("Extra data cannot exceed 1024 bytes")
        if self.coinbase == '':
            raise Exception("Coinbase cannot be empty address")

        if not self.is_genesis() and self.nonce and not self.check_proof_of_work(self.nonce):
            raise Exception("PoW check failed")

    def is_genesis(self):
        return self.prevhash == "\x00" * 32 and \
            self.nonce == utils.sha3(chr(42))  # safe assumption?

    def check_proof_of_work(self, nonce):
        prefix = self.serialize_header_without_nonce()
        h = utils.sha3(utils.sha3(prefix + nonce))
        l256 = utils.big_endian_to_int(h)
        return l256 < 2 ** 256 / self.difficulty

    @classmethod
    def deserialize(cls, rlpdata):
        header_args, transaction_list, uncles = rlp.decode(rlpdata)
        assert len(header_args) == len(block_structure)
        kargs = dict(transaction_list=transaction_list, uncles=uncles)
        # Deserialize all properties
        for i, (name, typ, default) in enumerate(block_structure):
            kargs[name] = utils.decoders[typ](header_args[i])
        return Block(**kargs)

    @classmethod
    def hex_deserialize(cls, hexrlpdata):
        return cls.deserialize(hexrlpdata.decode('hex'))

    # _get_acct_item(bin or hex, int) -> bin
    def _get_acct_item(self, address, param):
        ''' get account item
        :param address: account address, can be binary or hex string
        :param param: parameter to get
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        decoder = utils.decoders[acct_structure_rev[param][1]]
        return decoder(acct[acct_structure_rev[param][0]])

    # _set_acct_item(bin or hex, int, bin)
    def _set_acct_item(self, address, param, value):
        ''' set account item
        :param address: account address, can be binary or hex string
        :param param: parameter to set
        :param value: new value
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        encoder = utils.encoders[acct_structure_rev[param][1]]
        acct[acct_structure_rev[param][0]] = encoder(value)
        self.state.update(address, acct)

    # _delta_item(bin or hex, int, int) -> success/fail
    def _delta_item(self, address, param, value):
        ''' add value to account item
        :param address: account address, can be binary or hex string
        :param param: parameter to increase/decrease
        :param value: can be positive or negative
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        index = acct_structure_rev[param][0]
        if utils.decode_int(acct[index]) + value < 0:
            return False
        acct[index] = utils.encode_int(utils.decode_int(acct[index]) + value)
        self.state.update(address, acct)
        return True

    def _add_transaction_to_list(self, tx_serialized, state_root, gas_used_encoded):
        # adds encoded data # FIXME: the constructor should get objects
        data = [tx_serialized, state_root, gas_used_encoded]
        self.transactions.update(
            utils.encode_int(self.transaction_count), data)
        self.transaction_count += 1

    def add_transaction_to_list(self, tx):
        self._add_transaction_to_list(tx.serialize(),
                                      self.state_root,
                                      utils.encode_int(self.gas_used))

    def _list_transactions(self):
        # returns [[tx_serialized, state_root, gas_used_encoded],...]
        txlist = []
        for i in range(self.transaction_count):
            txlist.append(self.transactions.get(utils.encode_int(i)))
        return txlist

    def get_transactions(self):
        return [transactions.Transaction.deserialize(tx) for
                tx, s, g in self._list_transactions()]

    def apply_transaction(self, tx):
        return processblock.apply_tx(self, tx)

    def get_nonce(self, address):
        return self._get_acct_item(address, 'nonce')

    def increment_nonce(self, address):
        return self._delta_item(address, 'nonce', 1)

    def get_balance(self, address):
        return self._get_acct_item(address, 'balance')

    def set_balance(self, address, value):
        self._set_acct_item(address, 'balance', value)

    def delta_balance(self, address, value):
        return self._delta_item(address, 'balance', value)

    def get_code(self, address):
        codehash = self._get_acct_item(address, 'code')
        return self.state.db.get(codehash) if codehash else ''

    def set_code(self, address, value):
        self.state.db.put(utils.sha3(value), value)
        self.state.db.commit()
        self._set_acct_item(address, 'code', utils.sha3(value))

    def get_storage(self, address):
        storage_root = self._get_acct_item(address, 'storage')
        return trie.Trie(utils.get_db_path(), storage_root)

    def get_storage_data(self, address, index):
        t = self.get_storage(address)
        val = t.get(utils.coerce_to_bytes(index))
        return utils.decode_int(val) if val else 0

    def set_storage_data(self, address, index, val):
        t = self.get_storage(address)
        if val:
            t.update(utils.coerce_to_bytes(index), utils.encode_int(val))
        else:
            t.delete(utils.coerce_to_bytes(index))
        self._set_acct_item(address, 'storage', t.root)

    def _account_to_dict(self, acct):
        med_dict = {}
        for i, (name, typ, default) in enumerate(acct_structure):
            med_dict[name] = utils.decoders[typ](acct[i])
        chash = med_dict['code']
        strie = trie.Trie(utils.get_db_path(), med_dict['storage']).to_dict()
        med_dict['code'] = \
            self.state.db.get(chash).encode('hex') if chash else ''
        med_dict['storage'] = {
            utils.decode_int(k): utils.decode_int(strie[k]) for k in strie
        }
        return med_dict

    def account_to_dict(self, address):
        acct = self.state.get(address.decode('hex')) or ['', '', '', '']
        return self._account_to_dict(acct)

    # Revert computation
    def snapshot(self):
        return {
            'state': self.state.root,
            'gas': self.gas_used,
            'txs': self.transactions,
            'txcount': self.transaction_count,
        }

    def revert(self, mysnapshot):
        self.state.root = mysnapshot['state']
        self.gas_used = mysnapshot['gas']
        self.transactions = mysnapshot['txs']
        self.transaction_count = mysnapshot['txcount']

    def finalize(self):
        self.delta_balance(self.coinbase, BLOCK_REWARD)

    def serialize_header_without_nonce(self):
        return rlp.encode(self.list_header(exclude=['nonce']))

    @property
    def state_root(self):
        return self.state.root

    @property
    def tx_list_root(self):
        return self.transactions.root

    def list_header(self, exclude=[]):
        self.uncles_hash = utils.sha3(rlp.encode(self.uncles))
        header = []
        for name, typ, default in block_structure:
            # print name, typ, default , getattr(self, name)
            if not name in exclude:
                header.append(utils.encoders[typ](getattr(self, name)))
        return header

    def serialize(self):
        # Serialization method; should act as perfect inverse function of the
        # constructor assuming no verification failures
        return rlp.encode([self.list_header(), self._list_transactions(), self.uncles])

    def hex_serialize(self):
        return self.serialize().encode('hex')

    def to_dict(self):
        b = {}
        for name, typ, default in block_structure:
            b[name] = getattr(self, name)
        state = self.state.to_dict(True)
        b["state"] = {}
        for s in state:
            b["state"][s.encode('hex')] = self._account_to_dict(state[s])
        # txlist = []
        # for i in range(self.transaction_count):
        #     txlist.append(self.transactions.get(utils.encode_int(i)))
        # b["transactions"] = txlist
        return b

    @property
    def hash(self):
        return utils.sha3(self.serialize())

    def hex_hash(self):
        return self.hash.encode('hex')

    def get_parent(self):
        if self.number == 0:
            raise KeyError('Genesis block has no parent')
        parent =  get_block(self.prevhash)
        assert parent.state.db.db == self.state.db.db
        return parent

    def has_parent(self):
        try:
            self.get_parent()
            return True
        except KeyError:
            return False

    def chain_difficulty(self):
            # calculate the summarized_difficulty (on the fly for now)
        if self.is_genesis():
            return self.difficulty
        else:
            return self.difficulty + self.get_parent().chain_difficulty()

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.hash == other.hash

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        return self.number > other.number

    def __lt__(self, other):
        return self.number < other.number

    def __repr__(self):
        return '<Block(#%d %s %s)>' % (self.number, self.hex_hash()[:4], self.prevhash.encode('hex')[:4])

    @classmethod
    def init_from_parent(cls, parent, coinbase, extra_data='',
                         now=int(time.time())):
        return Block(
            prevhash=parent.hash,
            uncles_hash=utils.sha3(rlp.encode([])),
            coinbase=coinbase,
            state_root=parent.state.root,
            tx_list_root='',
            difficulty=calc_difficulty(parent, now),
            number=parent.number + 1,
            min_gas_price=0,
            gas_limit=calc_gaslimit(parent),
            gas_used=0,
            timestamp=now,
            extra_data=extra_data,
            nonce='',
            transaction_list=[],
            uncles=[])

# put the next two functions into this module to support Block.get_parent
# should be probably be in chainmanager otherwise


def get_block(blockhash):
    return Block.deserialize(db.DB(utils.get_db_path()).get(blockhash))


def has_block(blockhash):
    return db.DB(utils.get_db_path()).has_key(blockhash)


def genesis(initial_alloc={}):
    # https://ethereum.etherpad.mozilla.org/11
    block = Block(prevhash="\x00" * 32, coinbase="0" * 40,
                  difficulty=INITIAL_DIFFICULTY, nonce=utils.sha3(chr(42)),
                  gas_limit=10 ** 6)
    for addr in initial_alloc:
        block.set_balance(addr, initial_alloc[addr])
    return block

GENESIS_HASH = '58894fda9e380223879b664bed0bdfafa7a393bea5075ab68f5dcc66b42c7687'.decode(
    'hex')
# assert GENESIS_HASH == genesis().hash # do not leave uncomment
