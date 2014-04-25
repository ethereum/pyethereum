import re
import rlp
from bitcoin import encode_pubkey
from bitcoin import ecdsa_raw_sign, ecdsa_raw_recover
from utils import sha3, privtoaddr
import utils

tx_structure = [
    ["nonce", "int", 0],
    ["gasprice", "int", 0],
    ["startgas", "int", 0],
    ["to", "addr", ''],
    ["value", "int", 0],
    ["data", "bin", ''],
    ["v", "int", 0],
    ["r", "int", 0],
    ["s", "int", 0],
]


class Transaction(object):

    """
    A transaction is stored as:
    [ nonce, gasprice, startgas, to, value, data, v, r, s]

    nonce is the number of transactions already sent by that account, encoded
    in binary form (eg.  0 -> '', 7 -> '\x07', 1000 -> '\x03\xd8').

    (v,r,s) is the raw Electrum-style signature of the transaction without the
    signature made with the private key corresponding to the sending account,
    with 0 <= v <= 3. From an Electrum-style signature (65 bytes) it is
    possible to extract the public key, and thereby the address, directly.

    A valid transaction is one where:
    (i) the signature is well-formed (ie. 0 <= v <= 3, 0 <= r < P, 0 <= s < N,
        0 <= r < P - N if v >= 2), and
    (ii) the sending account has enough funds to pay the fee and the value.
    """

    # nonce,gasprice,startgas,to,value,data,v,r,s
    def __init__(self, *args):
        # From serialization
        if len(args) == 1:
            if re.match('^[0-9a-fA-F]*$', args[0]):
                args = rlp.decode(args[0].decode('hex'))
            else:
                args = rlp.decode(args[0])
            # Deserialize all properties
            for i, (name, typ, default) in enumerate(tx_structure):
                if i < len(args):
                    setattr(self, name, utils.decoders[typ](args[i]))
                else:
                    setattr(self, name, default)
        else:
            # Directly use arguments
            for i, (name, typ, default) in enumerate(tx_structure):
                setattr(self, name, args[i] if i < len(args) else default)
        # Determine sender
        if self.r and self.s:
            rawhash = sha3(rlp.encode(self.serialize(False)))
            pub = encode_pubkey(
                ecdsa_raw_recover(rawhash, (self.v, self.r, self.s)),
                'bin')
            self.sender = sha3(pub[1:])[-20:].encode('hex')
        # does not include signature
        else:
            self.sender = 0

    def sign(self, key):
        rawhash = sha3(rlp.encode(self.serialize(False)))
        self.v, self.r, self.s = ecdsa_raw_sign(rawhash, key)
        self.sender = privtoaddr(key)
        return self

    def serialize(self, signed=True):
        o = []
        for i, (name, typ, default) in enumerate(tx_structure):
            o.append(utils.encoders[typ](getattr(self, name)))
        return rlp.encode(o if signed else o[:-3])

    def hex_serialize(self):
        return self.serialize().encode('hex')

    def hash(self):
        return sha3(self.serialize())


def contract(nonce, gasprice, startgas, endowment, code, v=0, r=0, s=0):
    tx = Transaction(nonce, gasprice, startgas, '', endowment, code)
    tx.v, tx.r, tx.s = v, r, s
    return tx
