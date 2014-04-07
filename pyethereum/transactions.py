import re
import rlp
from bitcoin import encode_pubkey
from bitcoin import ecdsa_raw_sign, ecdsa_raw_recover
from opcodes import reverse_opcodes
from utils import big_endian_to_int as decode_int
from utils import int_to_big_endian as encode_int
from utils import sha3, privtoaddr

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

    def __init__(*args):
        self = args[0]
        if len(args) == 2:
            self.parse(args[1])
        else:
            self.nonce = args[1]
            self.value = args[2]
            self.gasprice = args[3]
            self.startgas = args[4]
            self.to = args[5]
            self.data = args[6]
            if len(args) > 7:
                self.v, self.r, self.s = args[7:10]
            else:
                self.v, self.r, self.s = 0,0,0

    @classmethod
    def contract(*args):
        cls = args[0]
        def numberize(arg):
            if isinstance(arg,(int,long)): return arg
            elif arg in reverse_opcodes: return reverse_opcodes[arg]
            elif arg[:4] == 'PUSH': return 95 + int(arg[4:])
            elif re.match('^[0-9]*$',arg): return int(arg)
            else: raise Exception("Cannot serialize: "+str(arg))
        codons = args[5] if isinstance(args[5],list) else args[5].split(' ')
        code = ''.join(map(chr,map(numberize,codons)))
        tx = cls(args[1],args[2],args[3],args[4],'',code)
        if len(args) > 6:
            tx.v, tx.r, tx.s = args[6:9]
        else:
            tx.v, tx.r, tx.s = 0,0,0
        return tx

    @classmethod
    def parse(cls, data):
        if re.match('^[0-9a-fA-F]*$', data):
            data = data.decode('hex')
        o = rlp.decode(data)
        tx = cls(decode_int(o[0]),
                 decode_int(o[1]),
                 decode_int(o[2]),
                 decode_int(o[3]),
                 o[4].encode('hex'),
                 o[5],
                 decode_int(o[6]),
                 decode_int(o[7]),
                 decode_int(o[8]))
        rawhash = sha3(rlp.encode(tx.serialize(False)))
        pub = encode_pubkey(
            ecdsa_raw_recover(rawhash, (tx.v, tx.r, tx.s)), 'bin')
        tx.sender = sha3(pub[1:])[-20:].encode('hex')
        return tx

    def sign(self, key):
        rawhash = sha3(rlp.encode(self.serialize(False)))
        self.v, self.r, self.s = ecdsa_raw_sign(rawhash, key)
        self.sender = privtoaddr(key)
        return self

    def serialize(self,signed=True):
        return rlp.encode([encode_int(self.nonce),
                           encode_int(self.value),
                           encode_int(self.gasprice),
                           encode_int(self.startgas),
                           self.to.decode('hex'),
                           self.data,
                           encode_int(self.v),
                           encode_int(self.r),
                           encode_int(self.s)][:9 if signed else 6])

    def hex_serialize(self):
        return self.serialize().encode('hex')

    def hash(self):
        return sha3(self.serialize())
