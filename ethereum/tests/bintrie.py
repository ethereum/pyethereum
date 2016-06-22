# All nodes are of the form [path1, child1, path2, child2]
# or <value>

from ethereum import utils
from ethereum.db import EphemDB, ListeningDB
import rlp, sys
import copy

hashfunc = utils.sha3

HASHLEN = 32


# 0100000101010111010000110100100101001001 -> ASCII
def decode_bin(x):
    return ''.join([chr(int(x[i:i+8], 2)) for i in range(0, len(x), 8)])


# ASCII -> 0100000101010111010000110100100101001001
def encode_bin(x):
    o = ''
    for c in x:
        c = ord(c)
        p = ''
        for i in range(8):
            p = str(c % 2) + p
            c /= 2
        o += p
    return o


# Encodes a binary list [0,1,0,1,1,0] of any length into bytes
def encode_bin_path(li):
    if li == []:
        return ''
    b = ''.join([str(x) for x in li])
    b2 = '0' * ((4 - len(b)) % 4) + b
    prefix = ['00', '01', '10', '11'][len(b) % 4]
    if len(b2) % 8 == 4:
        return decode_bin('00' + prefix + b2)
    else:
        return decode_bin('100000' + prefix + b2)


# Decodes bytes into a binary list
def decode_bin_path(p):
    if p == '':
        return []
    p = encode_bin(p)
    if p[0] == '1':
        p = p[4:]
    assert p[0:2] == '00'
    L = ['00', '01', '10', '11'].index(p[2:4])
    p = p[4+((4 - L) % 4):]
    return [(1 if x == '1' else 0) for x in p]


# Get a node from a database if needed
def dbget(node, db):
    if len(node) == HASHLEN:
        return rlp.decode(db.get(node))
    return node


# Place a node into a database if needed
def dbput(node, db):
    r = rlp.encode(node)
    if len(r) == HASHLEN or len(r) > HASHLEN * 2:
        h = hashfunc(r)
        db.put(h, r)
        return h
    return node


# Get a value from a tree
def get(node, db, key):
    node = dbget(node, db)
    if key == []:
        return node[0]
    elif len(node) == 1 or len(node) == 0:
        return ''
    else:
        sub = dbget(node[key[0]], db)
        if len(sub) == 2:
            subpath, subnode = sub
        else:
            subpath, subnode = '', sub[0]
        subpath = decode_bin_path(subpath)
        if key[1:len(subpath)+1] != subpath:
            return ''
        return get(subnode, db, key[len(subpath)+1:])


# Get length of shared prefix of inputs
def get_shared_length(l1, l2):
    i = 0
    while i < len(l1) and i < len(l2) and l1[i] == l2[i]:
        i += 1
    return i


# Replace ['', v] with [v] and compact nodes into hashes
# if needed
def contract_node(n, db):
    if len(n[0]) == 2 and n[0][0] == '':
        n[0] = [n[0][1]]
    if len(n[1]) == 2 and n[1][0] == '':
        n[1] = [n[1][1]]
    if len(n[0]) != 32:
        n[0] = dbput(n[0], db)
    if len(n[1]) != 32:
        n[1] = dbput(n[1], db)
    return dbput(n, db)


# Update a trie
def update(node, db, key, val):
    node = dbget(node, db)
    # Unfortunately this particular design does not allow
    # a node to have one child, so at the root for empty
    # tries we need to add two dummy children
    if node == '':
        node = [dbput([encode_bin_path([]), ''], db),
                dbput([encode_bin_path([1]), ''], db)]
    if key == []:
        node = [val]
    elif len(node) == 1:
        raise Exception("DB must be prefix-free")
    else:
        assert len(node) == 2, node
        sub = dbget(node[key[0]], db)
        if len(sub) == 2:
            _subpath, subnode = sub
        else:
            _subpath, subnode = '', sub[0]
        subpath = decode_bin_path(_subpath)
        sl = get_shared_length(subpath, key[1:])
        if sl == len(subpath):
            node[key[0]] = [_subpath, update(subnode, db, key[sl+1:], val)]
        else:
            subpath_next = subpath[sl]
            n = [0, 0]
            n[subpath_next] = [encode_bin_path(subpath[sl+1:]), subnode]
            n[(1 - subpath_next)] = [encode_bin_path(key[sl+2:]), [val]]
            n = contract_node(n, db)
            node[key[0]] = dbput([encode_bin_path(subpath[:sl]), n], db)
    return contract_node(node, db)


# Compression algorithm specialized for merkle proof databases
# The idea is similar to standard compression algorithms, where
# you replace an instance of a repeat with a pointer to the repeat,
# except that here you replace an instance of a hash of a value
# with the pointer of a value. This is useful since merkle branches
# usually include nodes which contain hashes of each other
magic = '\xff\x39'


def compress_db(db):
    out = []
    values = db.kv.values()
    keys = [hashfunc(x) for x in values]
    assert len(keys) < 65300
    for v in values:
        o = ''
        pos = 0
        while pos < len(v):
            done = False
            if v[pos:pos+2] == magic:
                o += magic + magic
                done = True
                pos += 2
            for i, k in enumerate(keys):
                if v[pos:].startswith(k):
                    o += magic + chr(i // 256) + chr(i % 256)
                    done = True
                    pos += len(k)
                    break
            if not done:
                o += v[pos]
                pos += 1
        out.append(o)
    return rlp.encode(out)


def decompress_db(ins):
    ins = rlp.decode(ins)
    vals = [None] * len(ins)

    def decipher(i):
        if vals[i] is None:
            v = ins[i]
            o = ''
            pos = 0
            while pos < len(v):
                if v[pos:pos+2] == magic:
                    if v[pos+2:pos+4] == magic:
                        o += magic
                    else:
                        ind = ord(v[pos+2]) * 256 + ord(v[pos+3])
                        o += hashfunc(decipher(ind))
                    pos += 4
                else:
                    o += v[pos]
                    pos += 1
            vals[i] = o
        return vals[i]

    for i in range(len(ins)):
        decipher(i)

    o = EphemDB()
    for v in vals:
        o.put(hashfunc(v), v)
    return o


# Convert a merkle branch directly into RLP (ie. remove
# the hashing indirection). As it turns out, this is a
# really compact way to represent a branch
def compress_branch(db, root):
    o = dbget(copy.copy(root), db)

    def evaluate_node(x):
        for i in range(len(x)):
            if len(x[i]) == HASHLEN and x[i] in db.kv:
                x[i] = evaluate_node(dbget(x[i], db))
            elif isinstance(x, list):
                x[i] = evaluate_node(x[i])
        return x

    o2 = rlp.encode(evaluate_node(o))
    return o2


def decompress_branch(branch):
    branch = rlp.decode(branch)
    db = EphemDB()

    def evaluate_node(x):
        if isinstance(x, list):
            x = [evaluate_node(n) for n in x]
        x = dbput(x, db)
        return x
    evaluate_node(branch)
    return db


# Test with n nodes and k branch picks
def test(n, m=100):
    assert m <= n
    db = EphemDB()
    x = ''
    for i in range(n):
        k = hashfunc(str(i))
        v = hashfunc('v'+str(i))
        x = update(x, db, [int(a) for a in encode_bin(rlp.encode(k))], v)
    print(x)
    print(sum([len(val) for key, val in db.db.items()]))
    l1 = ListeningDB(db)
    o = 0
    p = 0
    q = 0
    ecks = x
    for i in range(m):
        x = copy.deepcopy(ecks)
        k = hashfunc(str(i))
        v = hashfunc('v'+str(i))
        l2 = ListeningDB(l1)
        v2 = get(x, l2,  [int(a) for a in encode_bin(rlp.encode(k))])
        assert v == v2
        o += sum([len(val) for key, val in l2.kv.items()])
        cdb = compress_db(l2)
        p += len(cdb)
        assert decompress_db(cdb).kv == l2.kv
        cbr = compress_branch(l2, x)
        q += len(cbr)
        dbranch = decompress_branch(cbr)
        assert v == get(x, dbranch,  [int(a) for a in encode_bin(rlp.encode(k))])
        # for k in l2.kv:
            # assert k in dbranch.kv
    o = {
        'total_db_size': sum([len(val) for key, val in l1.kv.items()]),
        'avg_proof_size': sum([len(val) for key, val in l1.kv.items()]),
        'avg_compressed_proof_size': (p // min(n, m)),
        'avg_branch_size': (q // min(n, m)),
        'compressed_db_size': len(compress_db(l1))
    }
    return o
