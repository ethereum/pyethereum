import ethereum.pruning_trie as pruning_trie
from ethereum.db import EphemDB
import rlp
import ethereum.utils as utils
import sys

db = EphemDB()

NODES = 200

t = pruning_trie.Trie(db)

for i in range(NODES):
    print '######################################################'
    t.update(str(i), str(i))
    print 'added'
    print 'root', utils.encode_hex(t.root_hash), t.root_node
    print 'db size: ', len(db.kv)
    for k, v in db.kv.items():
        refcount, val = rlp.decode(v)
        print utils.encode_hex(k), rlp.decode(val), utils.decode_int(refcount)
    print 'trie size: ', len(t.all_nodes())
    for k in t.all_nodes():
        print utils.encode_hex(utils.sha3(rlp.encode(k))), k
    print 'remaining keys: ', len(t.to_dict())
    if len(db.kv) != len(t.all_nodes()):
        a = t.all_nodes()
        for k in db.kv:
            if k not in a:
                print utils.encode_hex(k)
        raise Exception("unpruned key leak: %d %d" % (len(db.kv), len(t.all_nodes())))
print 'added'
print 'db size: ', len(db.kv), ', trie size: ', len(t.all_nodes())
print 'remaining keys: ', len(t.to_dict())
print '######################################################'
print '######################################################'
for i in range(NODES):
    print '######################################################'
    t.update(str(i), str(i ** 3))
    print 'updated'
    print 'root', utils.encode_hex(t.root_hash), t.root_node
    print 'db size: ', len(db.kv)
    for k, v in db.kv.items():
        refcount, val = rlp.decode(v)
        print utils.encode_hex(k), rlp.decode(val), utils.decode_int(refcount)
    print 'trie size: ', len(t.all_nodes())
    for k in t.all_nodes():
        print utils.encode_hex(utils.sha3(rlp.encode(k))), k
    print 'remaining keys: ', len(t.to_dict())
    if len(db.kv) != len(t.all_nodes()):
        a = t.all_nodes()
        for k in db.kv:
            if k not in a:
                print utils.encode_hex(k)
        raise Exception("unpruned key leak: %d %d" % (len(db.kv), len(t.all_nodes())))
print 'updated'
print 'db size: ', len(db.kv), ', trie size: ', len(t.all_nodes())
print 'remaining keys: ', len(t.to_dict())
print '######################################################'
print '######################################################'
for i in range(NODES):
    print '######################################################'
    t.delete(str(i))
    print 'deleted'
    print 'root', utils.encode_hex(t.root_hash), t.root_node
    print 'db size: ', len(db.kv)
    for k, v in db.kv.items():
        refcount, val = rlp.decode(v)
        print utils.encode_hex(k), rlp.decode(val), utils.decode_int(refcount)
    print 'trie size: ', len(t.all_nodes())
    for k in t.all_nodes():
        print utils.encode_hex(utils.sha3(rlp.encode(k))), k
    print 'remaining keys: ', len(t.to_dict())
    if len(db.kv) != len(t.all_nodes()):
        a = t.all_nodes()
        for k in db.kv:
            if k not in a:
                print utils.encode_hex(k)
        raise Exception("unpruned key leak: %d %d" % (len(db.kv), len(t.all_nodes())))
print 'deleted'
print 'db size: ', len(db.kv), ', trie size: ', len(t.all_nodes())
print 'remaining keys: ', len(t.to_dict())
