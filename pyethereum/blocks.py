import time
import rlp
import trie
import db
import utils
import processblock
import transactions
import logging
# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

INITIAL_DIFFICULTY = 2 ** 22
GENESIS_PREVHASH = '\00' * 32
GENESIS_COINBASE = "0" * 40
GENESIS_NONCE = utils.sha3(chr(42))
GENESIS_GAS_LIMIT = 10 ** 6
MIN_GAS_LIMIT = 125000
GASLIMIT_EMA_FACTOR = 1024
BLOCK_REWARD = 1500 * utils.denoms.finney
UNCLE_REWARD = 3 * BLOCK_REWARD / 4
NEPHEW_REWARD = BLOCK_REWARD / 8
BLOCK_DIFF_FACTOR = 1024
GENESIS_MIN_GAS_PRICE = 0
BLKLIM_FACTOR_NOM = 6
BLKLIM_FACTOR_DEN = 5

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
        self.suicides = []
        self.caches = {
            'balance': {},
            'nonce': {},
            'code': {},
            'storage': {},
            'all': {}
        }

        self.transactions = trie.Trie(utils.get_db_path(), tx_list_root)
        self.transaction_count = 0

        self.state = trie.Trie(utils.get_db_path(), state_root)

        if transaction_list:
            # support init with transactions only if state is known
            assert self.state.root_hash_valid()
            for tx_lst_serialized, state_root, gas_used_encoded \
                    in transaction_list:
                self._add_transaction_to_list(
                    tx_lst_serialized, state_root, gas_used_encoded)

        # make sure we are all on the same db
        assert self.state.db.db == self.transactions.db.db

        # use de/encoders to check type and validity
        for name, typ, d in block_structure:
            v = getattr(self, name)
            assert utils.decoders[typ](utils.encoders[typ](v)) == v

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
        if len(self.uncles) != len(set(map(str, self.uncles))):
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
    def deserialize(cls, rlpdata):
        header_args, transaction_list, uncles = rlp.decode(rlpdata)
        kargs = cls.deserialize_header(header_args)
        kargs['transaction_list'] = transaction_list
        kargs['uncles'] = uncles

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
                                       timestamp=kargs['timestamp'],
                                       uncles=uncles)

        # replay transactions
        for tx_lst_serialized, _state_root, _gas_used_encoded in \
                transaction_list:
            tx = transactions.Transaction.create(tx_lst_serialized)
#            logger.debug('state:\n%s', utils.dump_state(block.state))
#            logger.debug('applying %r', tx)
            success, output = processblock.apply_transaction(block, tx)
            #block.add_transaction_to_list(tx) # < this is done by processblock
#            logger.debug('state:\n%s', utils.dump_state(block.state))
            logger.debug('d %s %s', _gas_used_encoded, block.gas_used)
            assert utils.decode_int(_gas_used_encoded) == block.gas_used
            assert _state_root == block.state.root_hash

        block.finalize()

        block.uncles_hash = kargs['uncles_hash']
        block.nonce = kargs['nonce']
        block.min_gas_price = kargs['min_gas_price']

        # checks
        assert block.prevhash == self.hash

        assert block.gas_used == kargs['gas_used']
        assert block.gas_limit == kargs['gas_limit']
        assert block.timestamp == kargs['timestamp']
        assert block.difficulty == kargs['difficulty']
        assert block.number == kargs['number']
        assert block.extra_data == kargs['extra_data']
        assert utils.sha3(rlp.encode(block.uncles)) == kargs['uncles_hash']

        assert block.tx_list_root == kargs['tx_list_root']
        assert block.state.root_hash == kargs['state_root']

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
        if address in self.caches[param] and param != 'storage':
            return self.caches[param][address]
        return self.get_acct(address)[acct_structure_rev[param][0]]

    # _set_acct_item(bin or hex, int, bin)
    def _set_acct_item(self, address, param, value):
        ''' set account item
        :param address: account address, can be binary or hex string
        :param param: parameter to set
        :param value: new value
        '''
#        logger.debug('set acct %r %r %d', address, param, value)
        self.caches[param][address] = value
        self.caches['all'][address] = True

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

    def _add_transaction_to_list(self, tx_lst_serialized,
                                 state_root, gas_used_encoded):
        # adds encoded data # FIXME: the constructor should get objects
        assert isinstance(tx_lst_serialized, list)
        data = [tx_lst_serialized, state_root, gas_used_encoded]
        self.transactions.update(
            rlp.encode(utils.encode_int(self.transaction_count)),
            rlp.encode(data))
        self.transaction_count += 1

    def add_transaction_to_list(self, tx):
        tx_lst_serialized = rlp.decode(tx.serialize())
        self._add_transaction_to_list(tx_lst_serialized,
                                      self.state_root,
                                      utils.encode_int(self.gas_used))

    def _list_transactions(self):
        # returns [[tx_lst_serialized, state_root, gas_used_encoded],...]
        txlist = []
        for i in range(self.transaction_count):
            txlist.append(rlp.decode(
                self.transactions.get(rlp.encode(utils.encode_int(i)))))
        return txlist

    def get_transactions(self):
        return [transactions.Transaction.create(tx) for
                tx, s, g in self._list_transactions()]

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
        return trie.Trie(utils.get_db_path(), storage_root)

    def get_storage_data(self, address, index):
        if address in self.caches['storage']:
            if index in self.caches['storage'][address]:
                return self.caches['storage'][address][index]
        t = self.get_storage(address)
        key = utils.zpad(utils.coerce_to_bytes(index), 32)
        val = rlp.decode(t.get(key))
        return utils.big_endian_to_int(val) if val else 0

    def set_storage_data(self, address, index, val):
        if address not in self.caches['storage']:
            self.caches['storage'][address] = {}
            self.caches['all'][address] = True
        self.caches['storage'][address][index] = val

    def commit_state(self):
        for address in self.caches['all']:
            acct = rlp.decode(self.state.get(address.decode('hex'))) \
                or self.mk_blank_acct()
            for i, (key, typ, default) in enumerate(acct_structure):
                if key == 'storage':
                    t = trie.Trie(utils.get_db_path(), acct[i])
                    for k, v in self.caches[key].get(address, {}).iteritems():
                        enckey = utils.zpad(utils.coerce_to_bytes(k), 32)
                        val = rlp.encode(utils.int_to_big_endian(v))
                        if v:
                            t.update(enckey, val)
                        else:
                            t.delete(enckey)
                    acct[i] = t.root_hash
                else:
                    if address in self.caches[key]:
                        v = self.caches[key].get(address, default)
                        acct[i] = utils.encoders[acct_structure[i][1]](v)
            self.state.update(address.decode('hex'), rlp.encode(acct))
        self.reset_cache()

    def del_account(self, address):
        self.commit_state()
        if len(address) == 40:
            address = address.decode('hex')
        self.state.delete(address)

    def account_to_dict(self, address):
        self.commit_state()
        med_dict = {}
        for i, val in enumerate(self.get_acct(address)):
            name, typ, default = acct_structure[i]
            med_dict[acct_structure[i][0]] = utils.printers[typ](val)
            if name == 'storage':
                strie = trie.Trie(utils.get_db_path(), val)
                med_dict['storage_root'] = strie.get_root_hash().encode('hex')
        med_dict['storage'] = {'0x'+k.encode('hex'):
                               '0x'+rlp.decode(v).encode('hex')
                               for k, v in strie.to_dict().iteritems()}
        return med_dict

    def reset_cache(self):
        self.caches = {
            'all': {},
            'balance': {},
            'nonce': {},
            'code': {},
            'storage': {}
        }

    # Revert computation
    def snapshot(self):
        self.commit_state()
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
        self.reset_cache()

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
        self.state = trie.Trie(utils.get_db_path(), state_root_hash)
        self.reset_cache()

    state_root = property(get_state_root, set_state_root)

    def get_tx_list_root(self):
        return self.transactions.root_hash

    tx_list_root = property(get_tx_list_root)

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
        self.commit_state()
        b = {}
        for name, typ, default in block_structure:
            b[name] = utils.printers[typ](getattr(self, name))
        b["state"] = {}
        for address, v in self.state.to_dict().iteritems():
            b["state"][address.encode('hex')] = self.account_to_dict(address)
        txlist = []
        for i in range(self.transaction_count):
            td = self.transactions.get(rlp.encode(utils.encode_int(i)))
            tx = rlp.descend(td, 0)
            msr = rlp.descend_to_val(td, 1)
            gas = rlp.descend_to_val(td, 2)
            txjson = transactions.Transaction.deserialize(tx).to_dict()
            txlist.append({
                "tx": txjson,
                "medstate": msr.encode('hex'),
                "gas": str(utils.decode_int(gas))
            })
        b["transactions"] = txlist
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
        elif 'difficulty:'+self.hex_hash() in self.state.db:
            return utils.decode_int(
                self.state.db.get('difficulty:'+self.hex_hash()))
        else:
            o = self.difficulty + self.get_parent().chain_difficulty()
            self.state.db.put('difficulty:'+self.hex_hash(),
                              utils.encode_int(o))
            return o

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
                         timestamp=int(time.time()), uncles=[]):
        return Block(
            prevhash=parent.hash,
            uncles_hash=utils.sha3(rlp.encode(uncles)),
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
            uncles=uncles)

# put the next two functions into this module to support Block.get_parent
# should be probably be in chainmanager otherwise


def get_block(blockhash):
    return Block.deserialize(db.DB(utils.get_db_path()).get(blockhash))


def has_block(blockhash):
    return blockhash in db.DB(utils.get_db_path())


def genesis(start_alloc=GENESIS_INITIAL_ALLOC, difficulty=INITIAL_DIFFICULTY):
    # https://ethereum.etherpad.mozilla.org/11
    block = Block(prevhash=GENESIS_PREVHASH, coinbase=GENESIS_COINBASE,
                  tx_list_root=trie.BLANK_ROOT,
                  difficulty=difficulty, nonce=GENESIS_NONCE,
                  gas_limit=GENESIS_GAS_LIMIT)
    for addr, balance in start_alloc.iteritems():
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
