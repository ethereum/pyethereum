import bitcoin
from ethereum import utils, opcodes
from utils import safe_ord, decode_hex, big_endian_to_int
from rlp.utils import ascii_chr
from config import ETHER

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
    OP_GAS = opcodes.GCALLVALUETRANSFER
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    to = utils.int_to_addr(msg.data.extract32(0) % 2**160)
    value = msg.data.extract32(32)
    prebal = utils.big_endian_to_int(ext.get_storage(ETHER, msg.sender))
    if prebal >= value:
        ext.set_storage(ETHER, to, utils.big_endian_to_int(ext.get_storage(ETHER, to)) + value)
        ext.set_storage(ETHER, msg.sender, prebal - value)
        return 1, msg.gas - gas_cost, [0] * 31 + [1]
    else:
        return 1, msg.gas - gas_cost, [0] * 32
    

specials = {
    1: proc_ecrecover,
    2: proc_sha256,
    3: proc_ripemd160,
    4: proc_identity,
    big_endian_to_int(ETHER): proc_send_ether,
}

if __name__ == '__main__':
    class msg(object):
        data = 'testdata'
        gas = 500
    proc_ripemd160(None, msg)
