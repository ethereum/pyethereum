import ethereum.pruning_trie as pruning_trie
from ethereum.db import EphemDB
import rlp
import ethereum.utils as utils
import sys

db = EphemDB()

NODES = 200

t = pruning_trie.Trie(db)
t.death_row_timeout = 0

for i in range(NODES):
    print '######################################################'
    t.update(str(i), str(i))
    t.commit_death_row(0)
    t.process_epoch(0)
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
    t.commit_death_row(0)
    t.process_epoch(0)
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
    t.commit_death_row(0)
    t.process_epoch(0)
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

t.death_row_timeout = NODES // 4
for i in range(NODES):
    t.update(str(i), str(i))
    t.commit_death_row(i)
    t.process_epoch(i)
    print 'db size: ', len(db.kv), ', trie size: ', len(t.all_nodes())
for i in range(NODES):
    t.update(str(i), str(i ** 3))
    t.commit_death_row(i + NODES)
    t.process_epoch(i + NODES)
    print 'db size: ', len(db.kv), ', trie size: ', len(t.all_nodes())
for i in range(NODES):
    t.delete(str(i))
    t.commit_death_row(i + NODES * 2)
    t.process_epoch(i + NODES * 2)
    print 'db size: ', len(db.kv), ', trie size: ', len(t.all_nodes())
for i in range(NODES // 4):
    t.process_epoch(i + NODES * 3)
assert len(t.to_dict()) == 0
