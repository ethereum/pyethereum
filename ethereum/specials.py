# -*- coding: utf8 -*-
from py_ecc.secp256k1 import privtopub, ecdsa_raw_recover, N as secp256k1n
import hashlib
from rlp.utils import ascii_chr

from ethereum import utils, opcodes
from ethereum.utils import safe_ord, decode_hex, encode_int32


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

    if r >= secp256k1n or s >= secp256k1n or v < 27 or v > 28:
        return 1, msg.gas - opcodes.GECRECOVER, []
    try:
        pub = utils.ecrecover_to_pub(message_hash, v, r, s)
    except Exception as e:
        return 1, msg.gas - gas_cost, []
    o = [0] * 12 + [safe_ord(x) for x in utils.sha3(pub)[-20:]]
    return 1, msg.gas - gas_cost, o


def proc_sha256(ext, msg):
    # print('sha256 proc', msg.gas)
    OP_GAS = opcodes.GSHA256BASE + \
        (utils.ceil32(msg.data.size) // 32) * opcodes.GSHA256WORD
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    d = msg.data.extract_all()
    o = [safe_ord(x) for x in hashlib.sha256(d).digest()]
    return 1, msg.gas - gas_cost, o


def proc_ripemd160(ext, msg):
    # print('ripemd160 proc', msg.gas)
    OP_GAS = opcodes.GRIPEMD160BASE + \
        (utils.ceil32(msg.data.size) // 32) * opcodes.GRIPEMD160WORD
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    d = msg.data.extract_all()
    o = [0] * 12 + [safe_ord(x) for x in hashlib.new('ripemd160', d).digest()]
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


def mult_complexity(x):
    if x <= 64:
        return x ** 2
    elif x <= 1024:
        return x ** 2 // 4 + 96 * x - 3072
    else:
        return x ** 2 // 16 + 480 * x - 199680


def proc_modexp(ext, msg):
    if not ext.post_metropolis_hardfork():
        return 1, msg.gas, []
    print('modexp proc', msg.gas)
    baselen = msg.data.extract32(0)
    explen = msg.data.extract32(32)
    modlen = msg.data.extract32(64)
    first_exp_bytes = msg.data.extract32(
        96 + baselen) >> (8 * max(32 - explen, 0))
    bitlength = -1
    while first_exp_bytes:
        bitlength += 1
        first_exp_bytes >>= 1
    adjusted_explen = max(bitlength, 0) + 8 * max(explen - 32, 0)
    gas_cost = (mult_complexity(max(modlen, baselen)) *
                max(adjusted_explen, 1)) // opcodes.GMODEXPQUADDIVISOR
    print(baselen, explen, modlen, 'expected gas cost', gas_cost)
    if msg.gas < gas_cost:
        return 0, 0, []
    if baselen == 0:
        return 1, msg.gas - gas_cost, [0] * modlen
    if modlen == 0:
        return 1, msg.gas - gas_cost, []
    base = bytearray(baselen)
    msg.data.extract_copy(base, 0, 96, baselen)
    exp = bytearray(explen)
    msg.data.extract_copy(exp, 0, 96 + baselen, explen)
    mod = bytearray(modlen)
    msg.data.extract_copy(mod, 0, 96 + baselen + explen, modlen)
    if utils.big_endian_to_int(mod) == 0:
        return 1, msg.gas - gas_cost, [0] * modlen
    o = pow(
        utils.big_endian_to_int(base),
        utils.big_endian_to_int(exp),
        utils.big_endian_to_int(mod))
    return 1, msg.gas - \
        gas_cost, [
            safe_ord(x) for x in utils.zpad(
                utils.int_to_big_endian(o), modlen)]


def validate_point(x, y):
    import py_ecc.optimized_bn128 as bn128
    FQ = bn128.FQ
    if x >= bn128.field_modulus or y >= bn128.field_modulus:
        return False
    if (x, y) != (0, 0):
        p1 = (FQ(x), FQ(y), FQ(1))
        if not bn128.is_on_curve(p1, bn128.b):
            return False
    else:
        p1 = (FQ(1), FQ(1), FQ(0))
    return p1


def proc_ecadd(ext, msg):
    if not ext.post_metropolis_hardfork():
        return 1, msg.gas, []
    import py_ecc.optimized_bn128 as bn128
    FQ = bn128.FQ
    print('ecadd proc:', msg.gas)
    if msg.gas < opcodes.GECADD:
        return 0, 0, []
    x1 = msg.data.extract32(0)
    y1 = msg.data.extract32(32)
    x2 = msg.data.extract32(64)
    y2 = msg.data.extract32(96)
    p1 = validate_point(x1, y1)
    p2 = validate_point(x2, y2)
    if p1 is False or p2 is False:
        return 0, 0, []
    o = bn128.normalize(bn128.add(p1, p2))
    return 1, msg.gas - \
        opcodes.GECADD, [safe_ord(x) for x in (
            encode_int32(o[0].n) + encode_int32(o[1].n))]


def proc_ecmul(ext, msg):
    if not ext.post_metropolis_hardfork():
        return 1, msg.gas, []
    import py_ecc.optimized_bn128 as bn128
    FQ = bn128.FQ
    print('ecmul proc', msg.gas)
    if msg.gas < opcodes.GECMUL:
        return 0, 0, []
    x = msg.data.extract32(0)
    y = msg.data.extract32(32)
    m = msg.data.extract32(64)
    p = validate_point(x, y)
    if p is False:
        return 0, 0, []
    o = bn128.normalize(bn128.multiply(p, m))
    return (1, msg.gas - opcodes.GECMUL,
            [safe_ord(c) for c in (encode_int32(o[0].n) + encode_int32(o[1].n))])


def proc_ecpairing(ext, msg):
    if not ext.post_metropolis_hardfork():
        return 1, msg.gas, []
    import py_ecc.optimized_bn128 as bn128
    FQ = bn128.FQ
    print('pairing proc', msg.gas)
    # Data must be an exact multiple of 192 byte
    if msg.data.size % 192:
        return 0, 0, []
    gascost = opcodes.GPAIRINGBASE + msg.data.size // 192 * opcodes.GPAIRINGPERPOINT
    if msg.gas < gascost:
        return 0, 0, []
    zero = (bn128.FQ2.one(), bn128.FQ2.one(), bn128.FQ2.zero())
    exponent = bn128.FQ12.one()
    for i in range(0, msg.data.size, 192):
        x1 = msg.data.extract32(i)
        y1 = msg.data.extract32(i + 32)
        x2_i = msg.data.extract32(i + 64)
        x2_r = msg.data.extract32(i + 96)
        y2_i = msg.data.extract32(i + 128)
        y2_r = msg.data.extract32(i + 160)
        p1 = validate_point(x1, y1)
        if p1 is False:
            return 0, 0, []
        for v in (x2_i, x2_r, y2_i, y2_r):
            if v >= bn128.field_modulus:
                return 0, 0, []
        fq2_x = bn128.FQ2([x2_r, x2_i])
        fq2_y = bn128.FQ2([y2_r, y2_i])
        if (fq2_x, fq2_y) != (bn128.FQ2.zero(), bn128.FQ2.zero()):
            p2 = (fq2_x, fq2_y, bn128.FQ2.one())
            if not bn128.is_on_curve(p2, bn128.b2):
                return 0, 0, []
        else:
            p2 = zero
        if bn128.multiply(p2, bn128.curve_order)[-1] != bn128.FQ2.zero():
            return 0, 0, []
        exponent *= bn128.pairing(p2, p1, final_exponentiate=False)
    result = bn128.final_exponentiate(exponent) == bn128.FQ12.one()
    return 1, msg.gas - gascost, [0] * 31 + [1 if result else 0]


specials = {
    decode_hex(k): v for k, v in
    {
        b'0000000000000000000000000000000000000001': proc_ecrecover,
        b'0000000000000000000000000000000000000002': proc_sha256,
        b'0000000000000000000000000000000000000003': proc_ripemd160,
        b'0000000000000000000000000000000000000004': proc_identity,
        b'0000000000000000000000000000000000000005': proc_modexp,
        b'0000000000000000000000000000000000000006': proc_ecadd,
        b'0000000000000000000000000000000000000007': proc_ecmul,
        b'0000000000000000000000000000000000000008': proc_ecpairing,
    }.items()
}

if __name__ == '__main__':
    class msg(object):
        data = 'testdata'
        gas = 500
    proc_ripemd160(None, msg)
