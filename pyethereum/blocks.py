import time
import rlp
import trie
import db
import utils
import processblock
import transactions


INITIAL_DIFFICULTY = 2 ** 22
GENESIS_PREVHASH = '\00' * 32
GENESIS_COINBASE = "0" * 40
GENESIS_NONCE = utils.sha3(chr(42))
GENESIS_GAS_LIMIT = 10 ** 6
MIN_GAS_LIMIT = 10 ** 4
GASLIMIT_EMA_FACTOR = 1024
BLOCK_REWARD = 1500 * utils.denoms.finney
UNCLE_REWARD = 7 * BLOCK_REWARD / 8
BLOCK_DIFF_FACTOR = 1024
GENESIS_MIN_GAS_PRICE = 0
BLKLIM_FACTOR_NOM = 6
BLKLIM_FACTOR_DEN = 5

GENESIS_INITIAL_ALLOC = \
    {"8a40bfaa73256b60764c1bf40675a99083efb075": 2 ** 200,  # (G)
     "e6716f9544a56c530d868e4bfbacb172315bdead": 2 ** 200,  # (J)
     "1e12515ce3e0f817a4ddef9ca55788a1d66bd2df": 2 ** 200,  # (V)
     "1a26338f0d905e295fccb71fa9ea849ffa12aaf4": 2 ** 200,  # (A)
     "2ef47100e0787b915105fd5e3f4ff6752079d5cb": 2 ** 200,  # (M)
     "cd2a3d9f938e13cd947ec05abc7fe734df8dd826": 2 ** 200,  # (R)
     "6c386a4b26f73c802f34673f7248bb118f97424a": 2 ** 200,  # (HH)
     "e4157b34ea9615cfbde6b4fda419828124b70c78": 2 ** 200,  # (CH)
     }

block_structure = [
    ["prevhash", "bin", "\00" * 32],
    ["uncles_hash", "bin", utils.sha3(rlp.encode([]))],
    ["coinbase", "addr", GENESIS_COINBASE],
    ["state_root", "trie_root", trie.BLANK_ROOT],
    ["tx_list_root", "trie_root", trie.BLANK_ROOT],
    ["difficulty", "int", INITIAL_DIFFICULTY],
    ["number", "int", 0],
    ["min_gas_price", "int", GENESIS_MIN_GAS_PRICE],
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
    ["balance", "int", 0],
    ["nonce", "int", 0],
    ["storage", "trie_root", trie.BLANK_ROOT],
    ["code", "hash", ""],
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
    gl = (prior_contribution + new_contribution) / GASLIMIT_EMA_FACTOR
    return max(gl, MIN_GAS_LIMIT)


class UnknownParentException(Exception):
    pass


class TransientBlock(object):

    """
    Read only, non persisted, not validated representation of a block
    """

    def __init__(self, rlpdata):
        self.rlpdata = rlpdata
        self.hash = utils.sha3(rlpdata)
        header_args, transaction_list, uncles = rlp.decode(rlpdata)
        self.transaction_list = transaction_list  # rlp encoded transactions
        self.uncles = uncles
        for i, (name, typ, default) in enumerate(block_structure):
            setattr(self, name, utils.decoders[typ](header_args[i]))

    def __repr__(self):
        return '<TransientBlock(#%d %s %s)>' %\
            (self.number, self.hash.encode('hex')[
             :4], self.prevhash.encode('hex')[:4])


class Block(object):

    def __init__(self,
                 prevhash='\00' * 32,
                 uncles_hash=block_structure_rev['uncles_hash'][2],
                 coinbase=block_structure_rev['coinbase'][2],
                 state_root=trie.BLANK_ROOT,
                 tx_list_root=trie.BLANK_ROOT,
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

        self.transactions = trie.Trie(utils.get_db_path(), tx_list_root)
        self.transaction_count = 0

        self.state = trie.Trie(utils.get_db_path(), state_root)

        if transaction_list:
            # support init with transactions only if state is known
            assert self.state.root_hash_valid()
            for tx_serialized, state_root, gas_used_encoded \
                    in transaction_list:
                self._add_transaction_to_list(
                    tx_serialized, state_root, gas_used_encoded)

        # make sure we are all on the same db
        assert self.state.db.db == self.transactions.db.db

        # Basic consistency verifications
        if not self.state.root_hash_valid():
            raise Exception(
                "State Merkle root not found in database! %r" % self)
        if tx_list_root != self.transactions.root_hash:
            raise Exception("Transaction list root hash does not match!")
        if not self.transactions.root_hash_valid():
            raise Exception(
                "Transactions root not found in database! %r" % self)
        if utils.sha3(rlp.encode(self.uncles)) != self.uncles_hash:
            raise Exception("Uncle root hash does not match!")
        if len(self.uncles) != len(set(self.uncles)):
            raise Exception("Uncle hash not uniqe in uncles list")
        if len(self.extra_data) > 1024:
            raise Exception("Extra data cannot exceed 1024 bytes")
        if self.coinbase == '':
            raise Exception("Coinbase cannot be empty address")
        if not self.is_genesis() and self.nonce and\
                not self.check_proof_of_work(self.nonce):
            raise Exception("PoW check failed")

    def is_genesis(self):
        return self.prevhash == GENESIS_PREVHASH and \
            self.nonce == GENESIS_NONCE

    def check_proof_of_work(self, nonce):
        assert len(nonce) == 32
        rlp_Hn = self.serialize_header_without_nonce()
        # BE(SHA3(SHA3(RLP(Hn)) o n))
        h = utils.sha3(utils.sha3(rlp_Hn) + nonce)
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

        # if we don't have the state we need to replay transactions
        _db = db.DB(utils.get_db_path())
        if len(kargs['state_root']) == 32 and kargs['state_root'] in _db:
            return Block(**kargs)
        elif kargs['prevhash'] == GENESIS_PREVHASH:
            return Block(**kargs)
        else:  # no state, need to replay
            try:
                parent = get_block(kargs['prevhash'])
            except KeyError:
                raise UnknownParentException(kargs['prevhash'].encode('hex'))
            return parent.deserialize_child(rlpdata)

    def deserialize_child(self, rlpdata):
        """
        deserialization w/ replaying transactions
        """
        header_args, transaction_list, uncles = rlp.decode(rlpdata)
        assert len(header_args) == len(block_structure)
        kargs = dict(transaction_list=transaction_list, uncles=uncles)
        # Deserialize all properties
        for i, (name, typ, default) in enumerate(block_structure):
            kargs[name] = utils.decoders[typ](header_args[i])

        block = Block.init_from_parent(self, kargs['coinbase'],
                                       extra_data=kargs['extra_data'],
                                       timestamp=kargs['timestamp'])
        block.finalize()  # this is the first potential state change
        # replay transactions
        for tx_serialized, _state_root, _gas_used_encoded in transaction_list:
            tx = transactions.Transaction.deserialize(tx_serialized)
            processblock.apply_tx(block, tx)
            assert _state_root == block.state.root_hash
            assert utils.decode_int(_gas_used_encoded) == block.gas_used

        # checks
        assert block.prevhash == self.hash
        assert block.tx_list_root == kargs['tx_list_root']
        assert block.gas_used == kargs['gas_used']
        assert block.gas_limit == kargs['gas_limit']
        assert block.timestamp == kargs['timestamp']
        assert block.difficulty == kargs['difficulty']
        assert block.number == kargs['number']
        assert block.extra_data == kargs['extra_data']
        assert utils.sha3(rlp.encode(block.uncles)) == kargs['uncles_hash']
        assert block.state.root_hash == kargs['state_root']

        block.uncles_hash = kargs['uncles_hash']
        block.nonce = kargs['nonce']
        block.min_gas_price = kargs['min_gas_price']

        return block

    @classmethod
    def hex_deserialize(cls, hexrlpdata):
        return cls.deserialize(hexrlpdata.decode('hex'))

    def mk_blank_acct(self):
        if not hasattr(self, '_blank_acct'):
            codehash = utils.sha3('')
            self.state.db.put(codehash, '')
            self._blank_acct = [utils.encode_int(0),
                                utils.encode_int(0),
                                trie.BLANK_ROOT,
                                codehash]
        return self._blank_acct[:]

    def get_acct(self, address):
        if len(address) == 40:
            address = address.decode('hex')
        acct = rlp.decode(self.state.get(address)) or self.mk_blank_acct()
        return tuple(utils.decoders[t](acct[i])
                     for i, (n, t, d) in enumerate(acct_structure))

    # _get_acct_item(bin or hex, int) -> bin
    def _get_acct_item(self, address, param):
        ''' get account item
        :param address: account address, can be binary or hex string
        :param param: parameter to get
        '''
        return self.get_acct(address)[acct_structure_rev[param][0]]

    # _set_acct_item(bin or hex, int, bin)
    def _set_acct_item(self, address, param, value):
        ''' set account item
        :param address: account address, can be binary or hex string
        :param param: parameter to set
        :param value: new value
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = rlp.decode(self.state.get(address)) or self.mk_blank_acct()
        encoder = utils.encoders[acct_structure_rev[param][1]]
        acct[acct_structure_rev[param][0]] = encoder(value)
        self.state.update(address, rlp.encode(acct))

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

    def _add_transaction_to_list(self, tx_serialized,
                                 state_root, gas_used_encoded):
        # adds encoded data # FIXME: the constructor should get objects
        data = [tx_serialized, state_root, gas_used_encoded]
        self.transactions.update(
            utils.encode_int(self.transaction_count), rlp.encode(data))
        self.transaction_count += 1

    def add_transaction_to_list(self, tx):
        # used by processblocks apply_tx only. not atomic!
        self._add_transaction_to_list(tx.serialize(),
                                      self.state_root,
                                      utils.encode_int(self.gas_used))

    def _list_transactions(self):
        # returns [[tx_serialized, state_root, gas_used_encoded],...]
        txlist = []
        for i in range(self.transaction_count):
            txlist.append(rlp.decode(
                self.transactions.get(utils.encode_int(i))))
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
        return self._get_acct_item(address, 'code')

    def set_code(self, address, value):
        self._set_acct_item(address, 'code', value)

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
        self._set_acct_item(address, 'storage', t.root_hash)

    def account_to_dict(self, address):
        med_dict = {}
        for i, val in enumerate(self.get_acct(address)):
            med_dict[acct_structure[i][0]] = val
        strie = trie.Trie(utils.get_db_path(), med_dict['storage']).to_dict()
        med_dict['storage'] = {utils.decode_int(k): utils.decode_int(v)
                               for k, v in strie.iteritems()}
        return med_dict

    # Revert computation
    def snapshot(self):
        return {
            'state': self.state.root_hash,
            'gas': self.gas_used,
            'txs': self.transactions,
            'txcount': self.transaction_count,
        }

    def revert(self, mysnapshot):
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
        self.delta_balance(self.coinbase, BLOCK_REWARD)
        for uncle_hash in self.uncles:
            uncle = get_block(uncle_hash)
            self.delta_balance(uncle.coinbase, UNCLE_REWARD)

    def serialize_header_without_nonce(self):
        return rlp.encode(self.list_header(exclude=['nonce']))

    @property
    def state_root(self):
        return self.state.root_hash

    @property
    def tx_list_root(self):
        return self.transactions.root_hash

    def list_header(self, exclude=[]):
        self.uncles_hash = utils.sha3(rlp.encode(self.uncles))
        header = []
        for name, typ, default in block_structure:
            # print name, typ, default , getattr(self, name)
            if name not in exclude:
                header.append(utils.encoders[typ](getattr(self, name)))
        return header

    def serialize(self):
        # Serialization method; should act as perfect inverse function of the
        # constructor assuming no verification failures
        return rlp.encode([self.list_header(),
                           self._list_transactions(),
                           self.uncles])

    def hex_serialize(self):
        return self.serialize().encode('hex')

    def to_dict(self):
        b = {}
        for name, typ, default in block_structure:
            b[name] = getattr(self, name)
        b["state"] = {}
        for address, v in self.state.to_dict().iteritems():
            b["state"][address.encode('hex')] = self.account_to_dict(address)
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
            raise UnknownParentException('Genesis block has no parent')
        try:
            parent = get_block(self.prevhash)
        except KeyError:
            raise UnknownParentException(self.prevhash.encode('hex'))
        assert parent.state.db.db == self.state.db.db
        return parent

    def has_parent(self):
        try:
            self.get_parent()
            return True
        except UnknownParentException:
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
        return '<Block(#%d %s %s)>' % (self.number,
                                       self.hex_hash()[:4],
                                       self.prevhash.encode('hex')[:4])

    @classmethod
    def init_from_parent(cls, parent, coinbase, extra_data='',
                         timestamp=int(time.time())):
        return Block(
            prevhash=parent.hash,
            uncles_hash=utils.sha3(rlp.encode([])),
            coinbase=coinbase,
            state_root=parent.state.root_hash,
            tx_list_root=trie.BLANK_ROOT,
            difficulty=calc_difficulty(parent, timestamp),
            number=parent.number + 1,
            min_gas_price=0,
            gas_limit=calc_gaslimit(parent),
            gas_used=0,
            timestamp=timestamp,
            extra_data=extra_data,
            nonce='',
            transaction_list=[],
            uncles=[])

# put the next two functions into this module to support Block.get_parent
# should be probably be in chainmanager otherwise


def get_block(blockhash):
    return Block.deserialize(db.DB(utils.get_db_path()).get(blockhash))


def has_block(blockhash):
    return blockhash in db.DB(utils.get_db_path())


def genesis(initial_alloc=GENESIS_INITIAL_ALLOC, difficulty=INITIAL_DIFFICULTY):
    # https://ethereum.etherpad.mozilla.org/11
    block = Block(prevhash=GENESIS_PREVHASH, coinbase=GENESIS_COINBASE,
                  tx_list_root=trie.BLANK_ROOT,
                  difficulty=difficulty, nonce=GENESIS_NONCE,
                  gas_limit=GENESIS_GAS_LIMIT)
    for addr, balance in initial_alloc.iteritems():
        block.set_balance(addr, balance)
    block.state.db.commit()
    return block


def dump_genesis_block_tests_data():
    import json
    g = genesis()
    data = dict(
        genesis_state_root=g.state_root.encode('hex'),
        genesis_hash=g.hex_hash(),
        genesis_rlp_hex=g.serialize().encode('hex'),
        initial_alloc=dict()
    )
    for addr, balance in GENESIS_INITIAL_ALLOC.iteritems():
        data['initial_alloc'][addr] = str(balance)

    print json.dumps(data, indent=1)
