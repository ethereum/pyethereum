# -*- coding: utf8 -*-
import bitcoin
from rlp.utils import ascii_chr
from secp256k1 import PublicKey, ALL_FLAGS

from ethereum import utils, opcodes
from ethereum.utils import safe_ord, decode_hex


ZERO_PRIVKEY_ADDR = decode_hex('3f17f1962b36e491b30a40b2405849e597ba5fb5')


def proc_ecrecover(ext, msg):
    # print('ecrecover proc', msg.gas)
    OP_GAS = opcodes.GECRECOVER
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []

    message_hash_bytes = [0] * 32
    msg.data.extract_copy(message_hash_bytes, 0, 0, 32)
    message_hash = b''.join(map(ascii_chr, message_hash_bytes))

    # TODO: This conversion isn't really necessary.
    # TODO: Invesitage if the check below is really needed.
    v = msg.data.extract32(32)
    r = msg.data.extract32(64)
    s = msg.data.extract32(96)

    if r >= bitcoin.N or s >= bitcoin.N or v < 27 or v > 28:
        return 1, msg.gas - opcodes.GECRECOVER, []

    signature_bytes = [0] * 64
    msg.data.extract_copy(signature_bytes, 0, 64, 32)
    msg.data.extract_copy(signature_bytes, 32, 96, 32)
    signature = b''.join(map(ascii_chr, signature_bytes))

    pk = PublicKey(flags=ALL_FLAGS)
    try:
        pk.public_key = pk.ecdsa_recover(
            message_hash,
            pk.ecdsa_recoverable_deserialize(
                signature,
                v - 27
            ),
            raw=True
        )
    except Exception:
        # Recovery failed
        return 1, msg.gas - gas_cost, []

    pub = pk.serialize(compressed=False)
    o = [0] * 12 + [safe_ord(x) for x in utils.sha3(pub[1:])[-20:]]
    return 1, msg.gas - gas_cost, o


def proc_sha256(ext, msg):
    # print('sha256 proc', msg.gas)
    OP_GAS = opcodes.GSHA256BASE + \
        (utils.ceil32(msg.data.size) // 32) * opcodes.GSHA256WORD
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    d = msg.data.extract_all()
    o = [safe_ord(x) for x in bitcoin.bin_sha256(d)]
    return 1, msg.gas - gas_cost, o


def proc_ripemd160(ext, msg):
    # print('ripemd160 proc', msg.gas)
    OP_GAS = opcodes.GRIPEMD160BASE + \
        (utils.ceil32(msg.data.size) // 32) * opcodes.GRIPEMD160WORD
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    d = msg.data.extract_all()
    o = [0] * 12 + [safe_ord(x) for x in bitcoin.ripemd.RIPEMD160(d).digest()]
    return 1, msg.gas - gas_cost, o


def proc_identity(ext, msg):
    #print('identity proc', msg.gas)
    OP_GAS = opcodes.GIDENTITYBASE + \
        opcodes.GIDENTITYWORD * (utils.ceil32(msg.data.size) // 32)
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    o = [0] * msg.data.size
    msg.data.extract_copy(o, 0, 0, len(o))
    return 1, msg.gas - gas_cost, o

specials = {
    decode_hex(k): v for k, v in
    {
        b'0000000000000000000000000000000000000001': proc_ecrecover,
        b'0000000000000000000000000000000000000002': proc_sha256,
        b'0000000000000000000000000000000000000003': proc_ripemd160,
        b'0000000000000000000000000000000000000004': proc_identity,
    }.items()
}

if __name__ == '__main__':
    class msg(object):
        data = 'testdata'
        gas = 500
    proc_ripemd160(None, msg)
