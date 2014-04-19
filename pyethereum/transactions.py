import re
import rlp
from bitcoin import encode_pubkey
from bitcoin import ecdsa_raw_sign, ecdsa_raw_recover
from opcodes import reverse_opcodes
from utils import big_endian_to_int as decode_int
from utils import int_to_big_endian as encode_int
from utils import sha3, privtoaddr
import utils
import sys

class Transaction(object):

    """
    A transaction is stored as:
    [ nonce, value, gasprice, startgas, to, data, v, r, s]
    nonce is the number of transactions already sent by that account,
    encoded in binary form (eg. 0 -> '', 7 -> '\x07', 1000 -> '\x03\xd8').
    (v,r,s) is the raw Electrum-style signature of the transaction without the signature
    made with the private key corresponding to the sending account, with 0 <= v <= 3.
    From an Electrum-style signature (65 bytes) it is possible to extract the public key,
    and thereby the address, directly. A valid transaction is one where
    (i) the signature is well-formed (ie. 0 <= v <= 3, 0 <= r < P, 0 <= s < N, 0 <= r < P - N if v >= 2), and
    (ii) the sending account has enough funds to pay the fee and the value.
    """

    # nonce,value,gasprice,startgas,to,data
    def __init__(*args):
        self = args[0]
        if len(args) == 2:
            self.parse(args[1])
        else:
            self.nonce = args[1]
            self.value = args[2]
            self.gasprice = args[3]
            self.startgas = args[4]
            self.to = utils.coerce_addr_to_bin(args[5])
            self.data = args[6]
            # includes signature
            if len(args) > 7:
                self.v, self.r, self.s = args[7:10]
                if self.r > 0 and self.s > 0:
                    rawhash = sha3(rlp.encode(self.serialize(False)))
                    pub = encode_pubkey(
                        ecdsa_raw_recover(rawhash, (self.v, self.r, self.s)), 'bin')
                    self.sender = sha3(pub[1:])[-20:].encode('hex')
            # does not include signature
            else:
                self.v, self.r, self.s = 0,0,0
                self.sender = 0

    # nonce,value,gasprice,startgas,code
    @classmethod
    def contract(*args):
        sys.stderr.write("Deprecated method. Use pyethereum.transactions.contract "+
                         "instead of pyethereum.transactions.Transaction.contract\n")
        return contract(*args[1:])

    @classmethod
    def parse(cls, data):
        if re.match('^[0-9a-fA-F]*$', data):
            data = data.decode('hex')
        o = rlp.decode(data) + ['','','']
        tx = cls(decode_int(o[0]),
                 decode_int(o[1]),
                 decode_int(o[2]),
                 decode_int(o[3]),
                 o[4].encode('hex'),
                 o[5],
                 decode_int(o[6]),
                 decode_int(o[7]),
                 decode_int(o[8]))
        return tx

    def sign(self, key):
        rawhash = sha3(rlp.encode(self.serialize(False)))
        self.v, self.r, self.s = ecdsa_raw_sign(rawhash, key)
        self.sender = privtoaddr(key)
        return self

    def coerce_to_hex(self, n):
        return n.encode('hex') if len(n) == 20 else n


    def serialize(self, signed=True):
        return rlp.encode([encode_int(self.nonce),
                           encode_int(self.value),
                           encode_int(self.gasprice),
                           encode_int(self.startgas),
                           utils.coerce_addr_to_bin(self.to),
                           self.data,
                           encode_int(self.v),
                           encode_int(self.r),
                           encode_int(self.s)][:9 if signed else 6])

    def hex_serialize(self):
        return self.serialize().encode('hex')

    def hash(self):
        return sha3(self.serialize())

def contract(nonce, endowment, gasprice, startgas, code, v=0,r=0, s=0):
    tx = Transaction(nonce, endowment, gasprice, startgas, '', code)
    tx.v, tx.r, tx.s = v,r,s
    return tx
