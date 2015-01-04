import utils, bitcoin


def proc_ecrecover(ext, msg):
    print 'ecrecover proc', msg.gas
    OP_GAS = 500
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    b = [0] * 32
    msg.data.extract_copy(b, 0, 0, 32)
    h = ''.join([chr(x) for x in b])
    v = msg.data.extract32(32)
    r = msg.data.extract32(64)
    s = msg.data.extract32(96)
    if r >= bitcoin.N or s >= bitcoin.P or v < 27 or v > 28:
        return 1, msg.gas - 500, [0] * 32
    pub = bitcoin.encode_pubkey(bitcoin.ecdsa_raw_recover(h, (v, r, s)), 'bin')
    o = [0] * 12 + [ord(x) for x in utils.sha3(pub[1:])[-20:]]
    return 1, msg.gas - gas_cost, o


def proc_sha256(ext, msg):
    print 'sha256 proc', msg.gas
    OP_GAS = 50 + (utils.ceil32(msg.data.size) / 32) * 50
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    d = msg.data.extract_all()
    o = [ord(x) for x in bitcoin.bin_sha256(d)]
    return 1, msg.gas - gas_cost, o


def proc_ripemd160(ext, msg):
    print 'ripemd160 proc', msg.gas
    OP_GAS = 50 + (utils.ceil32(msg.data.size) / 32) * 50
    gas_cost = OP_GAS
    if msg.gas < gas_cost:
        return 0, 0, []
    d = msg.data.extract_all()
    o = [0] * 12 + [ord(x) for x in bitcoin.ripemd.RIPEMD160(d).digest()]
    return 1, msg.gas - gas_cost, o

specials = {
    '0000000000000000000000000000000000000001': proc_ecrecover,
    '0000000000000000000000000000000000000002': proc_sha256,
    '0000000000000000000000000000000000000003': proc_ripemd160,
}

if __name__ == '__main__':
    class msg(object):
        data = 'testdata'
        gas = 500
    proc_ripemd160(None, None, msg)
