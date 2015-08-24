from bitcoin import encode_pubkey, N, P
try:
    from ecdsa_recover import ecdsa_raw_sign, ecdsa_raw_recover
except ImportError:
    from bitcoin import ecdsa_raw_sign, ecdsa_raw_recover
import rlp
from rlp.sedes import big_endian_int, binary
from rlp.utils import decode_hex, encode_hex
from ethereum.processblock import mk_contract_address
from ethereum import bloom
from ethereum import utils
from ethereum.utils import TT256
from ethereum.exceptions import InvalidTransaction
from ethereum.slogging import get_logger
log = get_logger('eth.chain.tx')

class Transaction(rlp.Serializable):

    """
    A transaction is stored as:
    [nonce, gasprice, startgas, to, value, data, v, r, s]

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

    fields = [
        ('nonce', big_endian_int),
        ('gasprice', big_endian_int),
        ('startgas', big_endian_int),
        ('to', utils.address),
        ('value', big_endian_int),
        ('data', binary),
        ('v', big_endian_int),
        ('r', big_endian_int),
        ('s', big_endian_int),
    ]

    _sender = None

    def __init__(self, nonce, gasprice, startgas, to, value, data, v=0, r=0, s=0):
        if len(to) in (40, 48):
            to = decode_hex(to)
        if len(to) == 24:
            to = utils.check_and_strip_checksum(to)
        assert len(to) == 20 or len(to) == 0
        super(Transaction, self).__init__(nonce, gasprice, startgas, to, value, data, v, r, s)
        self.logs = []

        if self.gasprice >= TT256 or self.startgas >= TT256 or \
                self.value >= TT256 or self.nonce >= TT256:
            raise InvalidTransaction("Values way too high!")

        log.debug('deserialized tx', tx=encode_hex(self.hash)[:8])

    @property
    def sender(self):
        if not self._sender:
            # Determine sender
            if self.v:
                if self.r >= N or self.s >= P or self.v < 27 or self.v > 28 or self.r == 0 or self.s == 0:
                    raise InvalidTransaction("Invalid signature values!")
                log.debug('recovering sender')
                rlpdata = rlp.encode(self, UnsignedTransaction)
                rawhash = utils.sha3(rlpdata)
                pub = ecdsa_raw_recover(rawhash, (self.v, self.r, self.s))
                if pub is False:
                    raise InvalidTransaction("Invalid signature values (x^3+7 is non-residue)")
                if pub == (0, 0):
                    raise InvalidTransaction("Invalid signature (zero privkey cannot sign)")
                pub = encode_pubkey(pub, 'bin')
                self._sender = utils.sha3(pub[1:])[-20:]
                assert self.sender == self._sender
            else:
                self._sender = 0
        return self._sender

    @sender.setter
    def sender(self, value):
        self._sender = value

    def sign(self, key):
        """Sign this transaction with a private key.

        A potentially already existing signature would be overridden.
        """
        if key in (0, '', '\x00' * 32):
            raise InvalidTransaction("Zero privkey cannot sign")
        rawhash = utils.sha3(rlp.encode(self, UnsignedTransaction))
        self.v, self.r, self.s = ecdsa_raw_sign(rawhash, key)
        self.sender = utils.privtoaddr(key)
        return self

    @property
    def hash(self):
        return utils.sha3(rlp.encode(self))

    def log_bloom(self):
        "returns int"
        bloomables = [x.bloomables() for x in self.logs]
        return bloom.bloom_from_list(utils.flatten(bloomables))

    def log_bloom_b64(self):
        return bloom.b64(self.log_bloom())

    def to_dict(self):
        # TODO: previous version used printers
        d = {}
        for name, _ in self.__class__.fields:
            d[name] = getattr(self, name)
        d['sender'] = self.sender
        d['hash'] = encode_hex(self.hash)
        return d

    def log_dict(self):
        d = self.to_dict()
        d['sender'] = encode_hex(d['sender'] or '')
        d['to'] = encode_hex(d['to'])
        return d

    @property
    def creates(self):
        "returns the address of a contract created by this tx"
        if self.to == '':
            return mk_contract_address(self.sender, self.nonce)


    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.hash == other.hash

    def __hash__(self):
        return utils.big_endian_to_int(self.hash)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return '<Transaction(%s)>' % encode_hex(self.hash)[:4]

    def __structlog__(self):
        return encode_hex(self.hash)


UnsignedTransaction = Transaction.exclude(['v', 'r', 's'])


def contract(nonce, gasprice, startgas, endowment, code, v=0, r=0, s=0):
    """A contract is a special transaction without the `to` argument."""
    tx = Transaction(nonce, gasprice, startgas, '', endowment, code, v, r, s)
    return tx
