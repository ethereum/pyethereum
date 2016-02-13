import bitcoin
import utils
import opcodes
from utils import safe_ord, decode_hex, big_endian_to_int, \
    encode_int32, match_shard, shardify, sha3
from rlp.utils import ascii_chr
from config import ETHER, BLOOM, LOG, EXECUTION_STATE, TXINDEX
import rlp

ZERO_PRIVKEY_ADDR = decode_hex('3f17f1962b36e491b30a40b2405849e597ba5fb5')


def proc_ecrecover(ext, msg):
    # print('ecrecover proc', msg.gas)
    OP_GAS = opcodes.GECRECOVER
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    b = [0] * 32
    msg.data.extract_copy(b, 0, 0, 32)
    h = b''.join([ascii_chr(x) for x in b])
    v = msg.data.extract32(32)
    r = msg.data.extract32(64)
    s = msg.data.extract32(96)
    if r >= bitcoin.N or s >= bitcoin.N or v < 27 or v > 28:
        return 1, msg.gas - opcodes.GECRECOVER, []
    recovered_addr = bitcoin.ecdsa_raw_recover(h, (v, r, s))
    if recovered_addr in (False, (0, 0)):
        return 1, msg.gas - gas_cost, []
    pub = bitcoin.encode_pubkey(recovered_addr, 'bin')
    o = [0] * 12 + [safe_ord(x) for x in utils.sha3(pub[1:])[-20:]]
    return 1, msg.gas - gas_cost, o


def proc_ecadd(ext, msg):
    OP_GAS = opcodes.GECADD
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    x1 = msg.data.extract32(0)
    y1 = msg.data.extract32(32)
    x2 = msg.data.extract32(64)
    y2 = msg.data.extract32(96)
    # point not on curve
    if (x1*x1*x1+x1-y1*y1) % bitcoin.P != 0:
        return 0, 0, []
    # point not on curve
    if (x2*x2*x2+x2-y2*y2) % bitcoin.P != 0:
        return 0, 0, []
    c, d = bitcoin.fast_add((x1, y1), (x2, y2))
    c2, d2 = encode_int32(c), encode_int32(d)
    return 1, msg.gas - gas_cost, map(ord, c2 + d2)


def proc_ecmul(ext, msg):
    OP_GAS = opcodes.GECMUL
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    x1 = msg.data.extract32(0)
    y1 = msg.data.extract32(32)
    n = msg.data.extract32(64)
    # point not on curve
    if (x1*x1*x1+x1-y1*y1) % bitcoin.P != 0:
        return 0, 0, []
    c, d = bitcoin.fast_multiply((x1, y1), n)
    c2, d2 = encode_int32(c), encode_int32(d)
    return 1, msg.gas - gas_cost, map(ord, c2 + d2)


def proc_modexp(ext, msg):
    OP_GAS = opcodes.GMODEXP
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    b = msg.data.extract32(0)
    e = msg.data.extract32(32)
    m = msg.data.extract32(64)
    return 1, msg.gas - gas_cost, map(ord, encode_int32(pow(b, e, m)))


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

def proc_send_ether(ext, msg):
    SENDER_ETHER = match_shard(ETHER, msg.sender)
    TO_ETHER = match_shard(ETHER, msg.to)
    OP_GAS = opcodes.GCALLVALUETRANSFER
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    to = utils.int_to_addr(msg.data.extract32(0) % 2**160)
    value = msg.data.extract32(32)
    prebal = utils.big_endian_to_int(ext.get_storage(SENDER_ETHER, msg.sender))
    if prebal >= value:
        print 'xferring %d wei from %s to %s' % (value, msg.sender.encode('hex'), to.encode('hex'))
        ext.set_storage(TO_ETHER, to, utils.big_endian_to_int(ext.get_storage(TO_ETHER, to)) + value)
        ext.set_storage(SENDER_ETHER, msg.sender, prebal - value)
        return 1, msg.gas - gas_cost, [0] * 31 + [1]
    else:
        return 1, msg.gas - gas_cost, [0] * 32

def proc_log(ext, msg):
    _LOG = shardify(LOG, msg.left_bound)
    _EXSTATE = shardify(EXECUTION_STATE, msg.left_bound)
    data = msg.data.extract_all()
    topics = [data[i*32:i*32+32] for i in range(0, 128, 32)]
    OP_GAS = opcodes.GLOGBYTE * max(len(data) - 128, 0) + \
        opcodes.GLOGBASE + len([t for t in topics if t]) * opcodes.GLOGTOPIC
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    bloom = big_endian_to_int(ext.get_storage(_LOG, BLOOM)) or 0
    for t in topics:
        if t:
            t += '\x00' * (32 - len(t))
            h = sha3(t)
            for i in range(5):
                bloom |= 2**ord(h[i])
    ext.set_storage(_LOG, BLOOM, encode_int32(bloom))
    # print big_endian_to_int(state.get_storage(TXINDEX, 0)), state.get_storage(LOG, state.get_storage(TXINDEX, 0)).encode('hex')
    old_storage = ext.get_storage(_LOG, ext.get_storage(_EXSTATE, TXINDEX))
    new_storage = rlp.append(old_storage, data)
    ext.set_storage(_LOG, ext.get_storage(_EXSTATE, TXINDEX), new_storage)
    for listener in ext._listeners:
        listener(msg.sender, map(big_endian_to_int, topics), data[128:])
    return 1, msg.gas - gas_cost, [0] * 32

def proc_rlp_get(ext, msg, output_string=0):
    # print('rlpget proc', msg.gas)
    OP_GAS = opcodes.GRLPBASE + \
        (utils.ceil32(msg.data.size) // 32) * opcodes.GRLPWORD
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    try:
        data = msg.data.extract_all()
        rlpdata = rlp.decode(data[32:])
        index = big_endian_to_int(data[:32])
        assert isinstance(rlpdata[index], str)
        if output_string:
            return 1, msg.gas - gas_cost, map(ord, encode_int32(len(rlpdata[index])) + rlpdata[index])
        else:
            assert len(rlpdata[index]) <= 32
            return 1, msg.gas - gas_cost, [0] * (32 - len(rlpdata[index])) + map(ord, rlpdata[index])
    except:
        return 0, 0, []

def proc_rlp_get_bytes32(ext, msg):
    return proc_rlp_get(ext, msg, False)

def proc_rlp_get_string(ext, msg):
    return proc_rlp_get(ext, msg, True)

specials = {
    1: proc_ecrecover,
    2: proc_sha256,
    3: proc_ripemd160,
    4: proc_identity,
    5: proc_ecadd,
    6: proc_ecmul,
    7: proc_modexp,
    8: proc_rlp_get_bytes32,
    9: proc_rlp_get_string,
    big_endian_to_int(ETHER): proc_send_ether,
    big_endian_to_int(LOG): proc_log,
}

if __name__ == '__main__':
    class msg(object):
        data = 'testdata'
        gas = 500
    proc_ripemd160(None, msg)
