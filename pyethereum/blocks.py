import rlp
import re
from transactions import Transaction
from trie import Trie, DB
from utils import big_endian_to_int as decode_int
from utils import int_to_big_endian as encode_int
from utils import sha3

ACCT_RLP_LENGTH = 4
NONCE_INDEX = 0
BALANCE_INDEX = 1
CODE_INDEX = 2
STORAGE_INDEX = 3

class Block(object):
    def __init__(self, data=None):

        self.reward = 10**18
        self.gas_consumed = 0
        self.gaslimit = 1000000 # for now

        if not data:
            self.number = 0
            self.prevhash = ''
            self.uncles_root = ''
            self.coinbase = '0'*40
            self.state = Trie('statedb')
            self.transactions_root = ''
            self.transactions = []
            self.difficulty = 2**23
            self.timestamp = 0
            self.extradata = ''
            self.nonce = 0
            return

        if re.match('^[0-9a-fA-F]*$', data):
            data = data.decode('hex')

        header,  transaction_list, self.uncles = rlp.decode(data)
        [self.number,
         self.prevhash,
         self.uncles_root,
         self.coinbase,
         state_root,
         self.transactions_root,
         self.difficulty,
         self.timestamp,
         self.extradata,
         self.nonce] = header
        self.transactions = [Transaction(x) for x in transaction_list]
        self.state = Trie('statedb', state_root)


        # Verifications
        if self.state.root != '' and self.state.db.get(self.state.root) == '':
            raise Exception("State Merkle root not found in database!")
        if bin_sha256(rlp.encode(transaction_list)) != self.transactions_root:
            raise Exception("Transaction list root hash does not match!")
        if bin_sha256(rlp.encode(self.uncles)) != self.uncles_root:
            raise Exception("Uncle root hash does not match!")
        # TODO: check POW

    # get_index(bin or hex, int) -> bin
    def get_index(self,address,index):
        if len(address) == 40: address = address.decode('hex')
        acct = self.state.get(address) or ['','','','']
        return acct[index]

    # set_index(bin or hex, int, bin)
    def set_index(self,address,index,value):
        if len(address) == 40: address = address.decode('hex')
        acct = self.state.get(address) or ['','','','']
        acct[index] = value
        self.state.update(address,acct)

    # delta_index(bin or hex, int, int) -> success/fail
    def delta_index(self,address,index,value):
        if len(address) == 40: address = address.decode('hex')
        acct = self.state.get(address) or ['','','','']
        if decode_int(acct[index]) + value < 0:
            return False
        acct[index] = encode_int(decode_int(acct[index])+value)
        self.state.update(address,acct)
        return True

    def coerce_to_enc(self,n):
        return encode_int(n) if isinstance(n,(int,long)) else n
    def get_nonce(self,address):
        return decode_int(self.get_index(address,NONCE_INDEX))
    def increment_nonce(self,address):
        return self.delta_index(address,NONCE_INDEX,1)
    def get_balance(self,address):
        return decode_int(self.get_index(address,BALANCE_INDEX))
    def set_balance(self,address,value):
        self.set_index(address,BALANCE_INDEX,encode_int(value))
    def delta_balance(self,address,value):
        return self.delta_index(address,BALANCE_INDEX,value)
    def get_code(self,address):
        codehash = self.get_index(address,CODE_INDEX)
        return DB('statedb').get(codehash) if codehash else ''
    def set_code(self,address,value):
        DB('statedb').put(sha3(value),value)
        self.set_index(address,CODE_INDEX,sha3(value))
    def get_storage(self,address):
        return Trie('statedb',self.get_index(address,STORAGE_INDEX))
    def get_storage_data(self,address,index):
        return decode_int(self.get_storage(address).get(self.coerce_to_enc(index)))
    def set_storage_data(self,address,index,val):
        t = Trie('statedb',self.get_index(address,STORAGE_INDEX))
        t.update(self.coerce_to_enc(index),encode_int(val))
        self.set_index(address,STORAGE_INDEX,t.root)
    
    # Revert computation
    def snapshot(self):
        return { 'state': self.state.root, 'gas': self.gas_consumed }

    def revert(self,mysnapshot):
        self.state.root = mysnapshot['state']
        self.gas_consumed = mysnapshot['gas']

    # Serialization method; should act as perfect inverse function of the
    # constructor assuming no verification failures
    def serialize(self):
        txlist = [x.serialize() for x in self.transactions]
        header = [self.number,
                  self.prevhash,
                  bin_sha256(rlp.encode(self.uncles)),
                  self.coinbase,
                  self.state.root,
                  bin_sha256(rlp.encode(txlist)),
                  self.difficulty,
                  self.timestamp,
                  self.extradata,
                  self.nonce]
        return rlp.encode([header, txlist, self.uncles])

    def to_dict(self):
        state = self.state.to_dict(True)
        nstate = {}
        for s in state:
            t = Trie('statedb',state[s][STORAGE_INDEX])
            o = [0] * ACCT_RLP_LENGTH
            o[NONCE_INDEX] = decode_int(state[s][NONCE_INDEX])
            o[BALANCE_INDEX] = decode_int(state[s][BALANCE_INDEX])
            o[CODE_INDEX] = state[s][CODE_INDEX]
            td = t.to_dict(True)
            o[STORAGE_INDEX] = {k:decode_int(td[k]) for k in td}
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

    @classmethod
    def genesis(cls,initial_alloc):
        block = cls()
        for addr in initial_alloc:
            block.set_balance(addr,initial_alloc[addr])
        return block

    def hash(self):
        return bin_sha256(self.serialize())
