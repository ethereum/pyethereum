import rlp
import re
from transactions import Transaction
from trie import Trie
from utils import big_endian_to_int as decode_int
from utils import int_to_big_endian as encode_int


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

    # Serialization method; should act as perfect inverse function of the constructor
    # assuming no verification failures
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
            t = Trie('statedb',state[s][3])
            nstate[s.encode('hex')] = [ decode_int(state[s][0]),
                                        decode_int(state[s][1]),
                                        state[s][2],
                                        t.to_dict(True) ]
            
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
            addr2 = addr.decode('hex') if len(addr) == 40 else addr
            block.state.update(addr2,['',encode_int(initial_alloc[addr]),'',''])
        return block

    def hash(self):
        return bin_sha256(self.serialize())
