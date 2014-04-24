import rlp
import re
from transactions import Transaction
from trie import Trie
from utils import big_endian_to_int as decode_int
from utils import int_to_big_endian as encode_int
from utils import sha3, get_db_path
from utils import STATEDB_DIR
import utils
import os
import sys

'''
An account consists of [nonce, balance, code, storage]
'''
ACCT_RLP_LENGTH = 4
NONCE_INDEX = 0
BALANCE_INDEX = 1
CODE_INDEX = 2
STORAGE_INDEX = 3


class Block(object):

    def __init__(self, data=None):

        self.reward = 10 ** 18
        self.gas_consumed = 0
        self.gaslimit = 1000000  # for now

        if not data:
            self.number = 0
            self.prevhash = ''
            self.uncles_root = ''
            self.coinbase = '0' * 40
            self.state = Trie(get_db_path())
            self.transactions_root = ''
            self.transactions = []
            self.uncles = []
            self.difficulty = 2 ** 23
            self.timestamp = 0
            self.extradata = ''
            self.nonce = 0
            return

        if re.match('^[0-9a-fA-F]*$', data):
            data = data.decode('hex')

        header,  transaction_list, self.uncles = rlp.decode(data)
        self.number = decode_int(header[0])
        self.prevhash = header[1]
        self.uncles_root = header[2]
        self.coinbase = header[3].encode('hex')
        self.state = Trie(STATEDB_DIR, header[4])
        self.transactions_root = header[5]
        self.difficulty = decode_int(header[6])
        self.timestamp = decode_int(header[7])
        self.extradata = header[8]
        self.nonce = decode_int(header[9])
        self.transactions = [Transaction(x) for x in transaction_list]

        # Verifications
        if self.state.root != '' and self.state.db.get(self.state.root) == '':
            raise Exception("State Merkle root not found in database!")
        if sha3(rlp.encode(transaction_list)) != self.transactions_root:
            raise Exception("Transaction list root hash does not match!")
        if sha3(rlp.encode(self.uncles)) != self.uncles_root:
            raise Exception("Uncle root hash does not match!")
        # TODO: check POW

    # _get_acct_item(bin or hex, int) -> bin
    def _get_acct_item(self, address, index):
        ''' get account item
        :param address: account address, can be binary or hex string
        :param index: item index
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        return acct[index]

    # _set_acct_item(bin or hex, int, bin)
    def _set_acct_item(self, address, index, value):
        ''' set account item
        :param address: account address, can be binary or hex string
        :param index: item index
        :param value: new value
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        acct[index] = value
        self.state.update(address, acct)

    # _delta_item(bin or hex, int, int) -> success/fail
    def _delta_item(self, address, index, value):
        ''' add value to account item
        :param address: account address, can be binary or hex string
        :param index: item index
        :param value: can be positive or negative
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        if decode_int(acct[index]) + value < 0:
            return False
        acct[index] = encode_int(decode_int(acct[index]) + value)
        self.state.update(address, acct)
        return True

    def get_nonce(self, address):
        return decode_int(self._get_acct_item(address, NONCE_INDEX))

    def increment_nonce(self, address):
        return self._delta_item(address, NONCE_INDEX, 1)

    def get_balance(self, address):
        return decode_int(self._get_acct_item(address, BALANCE_INDEX))

    def set_balance(self, address, value):
        self._set_acct_item(address, BALANCE_INDEX, encode_int(value))

    def delta_balance(self, address, value):
        return self._delta_item(address, BALANCE_INDEX, value)

    def get_code(self, address):
        codehash = self._get_acct_item(address, CODE_INDEX)
        return self.state.db.get(codehash) if codehash else ''

    def set_code(self, address, value):
        self.state.db.put(sha3(value), value)
        self.state.db.commit()
        self._set_acct_item(address, CODE_INDEX, sha3(value))

    def get_storage(self, address):
        return Trie(STATEDB_DIR, self._get_acct_item(address, STORAGE_INDEX))

    def get_storage_data(self, address, index):
        t = self.get_storage(address)
        return decode_int(t.get(utils.coerce_to_bytes(index)))

    def set_storage_data(self, address, index, val):
        t = self.get_storage(address)
        if val:
            t.update(utils.coerce_to_bytes(index), encode_int(val))
        else:
            t.delete(utils.coerce_to_bytes(index))
        self._set_acct_item(address, STORAGE_INDEX, t.root)

    def account_to_dict(self, address):
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        chash = acct[CODE_INDEX]
        stdict = Trie(STATEDB_DIR, acct[STORAGE_INDEX]).to_dict(True)
        return {
            'nonce': decode_int(acct[NONCE_INDEX]),
            'balance': decode_int(acct[BALANCE_INDEX]),
            'code': self.state.db.get(chash).encode('hex') if chash else '',
            'storage': {decode_int(k): decode_int(stdict[k]) for k in stdict}
        }

    # Revert computation
    def snapshot(self):
        return {'state': self.state.root, 'gas': self.gas_consumed}

    def revert(self, mysnapshot):
        self.state.root = mysnapshot['state']
        self.gas_consumed = mysnapshot['gas']

    # Serialization method; should act as perfect inverse function of the
    # constructor assuming no verification failures
    def serialize(self):
        txlist = [x.serialize() for x in self.transactions]
        header = [encode_int(self.number),
                  self.prevhash,
                  sha3(rlp.encode(self.uncles)),
                  self.coinbase.decode('hex'),
                  self.state.root,
                  sha3(rlp.encode(txlist)),
                  encode_int(self.difficulty),
                  encode_int(self.timestamp),
                  self.extradata,
                  encode_int(self.nonce)]
        return rlp.encode([header, txlist, self.uncles])

    def to_dict(self):
        state = self.state.to_dict(True)
        nstate = {}
        for s in state:
            t = Trie(STATEDB_DIR, state[s][STORAGE_INDEX])
            o = [0] * ACCT_RLP_LENGTH
            o[NONCE_INDEX] = decode_int(state[s][NONCE_INDEX])
            o[BALANCE_INDEX] = decode_int(state[s][BALANCE_INDEX])
            o[CODE_INDEX] = state[s][CODE_INDEX]
            td = t.to_dict(True)
            o[STORAGE_INDEX] = {decode_int(k): decode_int(td[k]) for k in td}
            nstate[s.encode('hex')] = o

        return {
            "number": self.number,
            "prevhash": self.prevhash,
            "uncles_root": self.uncles_root,
            "coinbase": self.coinbase,
            "state": nstate,
            "transactions_root": self.transactions_root,
            "difficulty": self.difficulty,
            "timestamp": self.timestamp,
            "extradata": self.extradata,
            "nonce": self.nonce
        }

    def hash(self):
        return sha3(self.serialize())

    @classmethod
    def genesis(cls, initial_alloc):
        sys.stderr.write("Deprecated method. Use pyethereum.blocks.genesis" +
                         "instead of pyethereum.blocks.Block.genesis\n")
        return genesis(initial_alloc)


def genesis(initial_alloc):
    block = Block()
    for addr in initial_alloc:
        block.set_balance(addr, initial_alloc[addr])
    return block
