# -*- coding: utf8 -*-
import rlp
from bitcoin import encode_pubkey, N, encode_privkey, ecdsa_raw_sign
from rlp.sedes import big_endian_int, binary
from rlp.utils import encode_hex, str_to_bytes, ascii_chr

from ethereum.exceptions import InvalidTransaction
from ethereum import bloom
from ethereum import opcodes
from ethereum import utils
from ethereum.slogging import get_logger
from ethereum.utils import TT256, mk_contract_address, zpad, int_to_32bytearray, big_endian_to_int, ecsign, ecrecover_to_pub


log = get_logger('eth.chain.tx')

# in the yellow paper it is specified that s should be smaller than secpk1n (eq.205)
secpk1n = 115792089237316195423570985008687907852837564279074904382605163141518161494337


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
        self.data = None

        to = utils.normalize_address(to, allow_blank=True)
        assert len(to) == 20 or len(to) == 0
        super(Transaction, self).__init__(nonce, gasprice, startgas, to, value, data, v, r, s)
        self.logs = []

        if self.gasprice >= TT256 or self.startgas >= TT256 or \
                self.value >= TT256 or self.nonce >= TT256:
            raise InvalidTransaction("Values way too high!")
        if self.startgas < self.intrinsic_gas_used:
            raise InvalidTransaction("Startgas too low")

        log.debug('deserialized tx', tx=encode_hex(self.hash)[:8])

    @property
    def sender(self):

        if not self._sender:
            # Determine sender
            if self.v:
                if self.r >= N or self.s >= N or self.v not in (27, 28, 37, 38) \
                or self.r == 0 or self.s == 0:
                    raise InvalidTransaction("Invalid signature values!")
                log.debug('reco< 27 or self.v > 28 \vering sender')
                if self.v in (27, 28):
                    rlpdata = rlp.encode(self, UnsignedTransaction)
                    rawhash = utils.sha3(rlpdata)
                    v = self.v
                elif self.v in (37, 38):
                    rlpdata = rlp.encode(rlp.infer_sedes(self).serialize(self)[:-3] + ['\x01', '', ''])
                    rawhash = utils.sha3(rlpdata)
                    v = self.v - 10
                pub = ecrecover_to_pub(rawhash, v, self.r, self.s)
                if pub == b"\x00" * 64:
                    raise InvalidTransaction("Invalid signature (zero privkey cannot sign)")
                self._sender = utils.sha3(pub)[-20:]
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
        if key in (0, '', b'\x00' * 32, '0' * 64):
            raise InvalidTransaction("Zero privkey cannot sign")
        rawhash = utils.sha3(rlp.encode(self, UnsignedTransaction))

        if len(key) == 64:
            # we need a binary key
            key = encode_privkey(key, 'bin')

        self.v, self.r, self.s = ecsign(rawhash, key)

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
        d['data'] = encode_hex(d['data'])
        return d

    @property
    def intrinsic_gas_used(self):
        num_zero_bytes = str_to_bytes(self.data).count(ascii_chr(0))
        num_non_zero_bytes = len(self.data) - num_zero_bytes
        return (opcodes.GTXCOST
                + opcodes.GTXDATAZERO * num_zero_bytes
                + opcodes.GTXDATANONZERO * num_non_zero_bytes)

    @property
    def creates(self):
        "returns the address of a contract created by this tx"
        if self.to in (b'', '\0' * 20):
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

    # This method should be called for block numbers >= HOMESTEAD_FORK_BLKNUM only.
    # The >= operator is replaced by > because the integer division N/2 always produces the value
    # which is by 0.5 less than the real N/2
    def check_low_s_metropolis(self):
        if self.s > N // 2:
            raise InvalidTransaction("Invalid signature S value!")

    def check_low_s_homestead(self):
        if self.s > N // 2 or self.s == 0:
            raise InvalidTransaction("Invalid signature S value!")


UnsignedTransaction = Transaction.exclude(['v', 'r', 's'])


def contract(nonce, gasprice, startgas, endowment, code, v=0, r=0, s=0):
    """A contract is a special transaction without the `to` argument."""
    tx = Transaction(nonce, gasprice, startgas, '', endowment, code, v, r, s)
    return tx
