import ethereum.pruning_trie as pruning_trie
from ethereum.db import EphemDB
from ethereum.refcount_db import RefcountDB
import rlp
import ethereum.utils as utils
from ethereum.utils import to_string
import sys
import itertools
import ethereum.testutils as testutils
from ethereum.testutils import fixture_to_bytes
import os
import json


def check_db_tightness(trees, db):
    all_nodes = []
    for t in trees:
        for nd in t.all_nodes():
            if nd not in all_nodes:
                all_nodes.append(nd)
    if len(db.kv) != len(all_nodes):
        for k, v in db.kv.items():
            if rlp.decode(rlp.decode(v)[1]) not in all_nodes:
                print(utils.encode_hex(k[2:]), rlp.decode(rlp.decode(v)[1]))
        raise Exception("unpruned key leak: %d %d" % (len(db.kv), len(all_nodes)))


def test_basic_pruning():
    db = RefcountDB(EphemDB())
    NODES = 60

    t = pruning_trie.Trie(db)
    db.ttl = 0
    db.logging = True

    for i in range(NODES):
        t.update(to_string(i), to_string(i))
        db.commit_refcount_changes(0)
        db.cleanup(0)
        check_db_tightness([t], db)
    for i in range(NODES):
        t.update(to_string(i), to_string(i ** 3))
        db.commit_refcount_changes(0)
        db.cleanup(0)
        check_db_tightness([t], db)
    for i in range(NODES):
        t.delete(to_string(i))
        db.commit_refcount_changes(0)
        db.cleanup(0)
        check_db_tightness([t], db)
    assert len(t.to_dict()) == 0
    assert len(db.kv) == 0


def test_delayed_pruning():
    NODES = 60
    db = RefcountDB(EphemDB())
    t = pruning_trie.Trie(db)
    db.ttl = NODES // 4
    for i in range(NODES):
        t.update(to_string(i), to_string(i))
        db.commit_refcount_changes(i)
        db.cleanup(i)
    for i in range(NODES):
        t.update(to_string(i), to_string(i ** 3))
        db.commit_refcount_changes(i + NODES)
        db.cleanup(i + NODES)
    for i in range(NODES):
        t.delete(to_string(i))
        db.commit_refcount_changes(i + NODES * 2)
        db.cleanup(i + NODES * 2)
    for i in range(NODES // 4):
        db.cleanup(i + NODES * 3)
    assert len(t.to_dict()) == 0
    assert len(db.kv) == 0


def test_clear():
    db = RefcountDB(EphemDB())
    NODES = 60
    t = pruning_trie.Trie(db)
    db.ttl = 0
    for i in range(NODES):
        t.update(to_string(i), to_string(i))
        db.commit_refcount_changes(i)
        db.cleanup(i)
    t.clear_all()
    db.commit_refcount_changes(NODES)
    db.cleanup(NODES)
    assert len(db.kv) == 0


def test_delayed_clear():
    db = RefcountDB(EphemDB())
    NODES = 60
    t = pruning_trie.Trie(db)
    db.ttl = NODES // 4
    for i in range(NODES):
        t.update(to_string(i), to_string(i))
        db.commit_refcount_changes(i)
        db.cleanup(i)
    t.clear_all()
    db.commit_refcount_changes(NODES)
    db.cleanup(NODES)
    for i in range(NODES // 4 + 1):
        db.cleanup(i + NODES)
    assert len(db.kv) == 0


def test_insert_delete():
    for a in (5, 15, 60):
        db = RefcountDB(EphemDB())
        NODES = a
        t1 = pruning_trie.Trie(db)
        db.ttl = 0
        db.logging = True
        for i in range(NODES):
            t1.update(to_string(i), to_string(i))
            db.commit_refcount_changes(i)
            db.cleanup(i)
            check_db_tightness([t1], db)
        for i in range(NODES):
            t1.delete(to_string(NODES - 1 - i))
            db.commit_refcount_changes(NODES + i)
            db.cleanup(NODES + i)
            check_db_tightness([t1], db)
        assert len(db.kv) == 0


def test_two_trees():
    db = RefcountDB(EphemDB())
    NODES = 60
    t1 = pruning_trie.Trie(db)
    t2 = pruning_trie.Trie(db)
    db.ttl = 0
    for i in range(NODES):
        t1.update(to_string(i), to_string(i))
        if i < NODES // 2:
            t2.update(to_string(i), to_string(i))
        db.commit_refcount_changes(i)
        db.cleanup(i)
        check_db_tightness([t1, t2], db)
    for i in range(NODES):
        sys.stderr.write('clearing: %d\n' % i)
        t1.delete(to_string(NODES - 1 - i))
        db.commit_refcount_changes(NODES + i)
        db.cleanup(NODES + i)
        check_db_tightness([t1, t2], db)
    assert t2.to_dict() == {to_string(i): to_string(i) for i in range(NODES // 2)}
    for i in range(NODES // 2):
        t2.delete(to_string(i))
        db.commit_refcount_changes(NODES * 2 + i)
        db.cleanup(NODES * 2 + i)
        check_db_tightness([t1, t2], db)
    assert len(db.kv) == 0


def test_two_trees_with_clear():
    db = RefcountDB(EphemDB())
    NODES = 60
    t1 = pruning_trie.Trie(db)
    t2 = pruning_trie.Trie(db)
    db.ttl = NODES // 4
    for i in range(NODES):
        t1.update(to_string(i), to_string(i))
        if i < NODES // 2:
            t2.update(to_string(i), to_string(i))
        db.commit_refcount_changes(i)
        db.cleanup(i)
    t1.clear_all()
    db.cleanup(NODES)
    assert t2.to_dict() == {to_string(i): to_string(i) for i in range(NODES // 2)}
    for i in range(NODES // 2):
        t2.delete(to_string(i))
        db.commit_refcount_changes(NODES + i)
        db.cleanup(NODES + i)
    for i in range(NODES // 4):
        db.cleanup(NODES + NODES // 2 + i)
    assert len(db.kv) == 0


def test_revert_adds():
    db = RefcountDB(EphemDB())
    NODES = 60
    t1 = pruning_trie.Trie(db)
    t2 = pruning_trie.Trie(db)
    db.ttl = NODES * 2
    for i in range(NODES):
        t1.update(to_string(i), to_string(i))
        db.commit_refcount_changes(i)
        db.cleanup(i)
    for i in range(NODES):
        t2.update(to_string(i), to_string(i))
        db.commit_refcount_changes(NODES + i)
        db.cleanup(NODES + i)
    for i in range(NODES * 2 - 1, NODES - 1, -1):
        db.revert_refcount_changes(i)
    for i in range(NODES):
        t1.delete(to_string(i))
        db.commit_refcount_changes(NODES + i)
        db.cleanup(NODES + i)
    for i in range(NODES * 2):
        db.cleanup(NODES * 2 + i)
    assert len(db.kv) == 0


def test_revert_deletes():
    db = RefcountDB(EphemDB())
    NODES = 60
    t1 = pruning_trie.Trie(db)
    db.ttl = NODES * 2
    for i in range(NODES):
        t1.update(to_string(i), to_string(i))
        db.commit_refcount_changes(i)
        db.cleanup(i)
    x = t1.root_hash
    for i in range(NODES):
        t1.delete(to_string(i))
        db.commit_refcount_changes(NODES + i)
        db.cleanup(NODES + i)
    for i in range(NODES * 2 - 1, NODES - 1, -1):
        db.revert_refcount_changes(i)
    for i in range(NODES * 2):
        db.cleanup(NODES + i)
        db.revert_refcount_changes(i)
    t1.root_hash = x
    assert t1.to_dict() == {to_string(i): to_string(i) for i in range(NODES)}


def test_trie_transfer():
    db = RefcountDB(EphemDB())
    NODES = 60
    t1 = pruning_trie.Trie(db)
    db.ttl = NODES * 2
    for i in range(NODES):
        t1.update(to_string(i), to_string(i))
        db.commit_refcount_changes(i)
        db.cleanup(i)
    t2 = pruning_trie.Trie(db)
    t2.root_hash = t1.root_hash
    assert t2.to_dict() == {to_string(i): to_string(i) for i in range(NODES)}
    for i in range(NODES):
        t2.delete(to_string(i))
        db.commit_refcount_changes(NODES + i)
        db.cleanup(NODES + i)
    for i in range(NODES * 2):
        db.cleanup(2 * NODES + i)
    assert len(db.kv) == 0


def test_two_tries_with_small_root_node():
    db = RefcountDB(EphemDB())
    db.logging = True
    db.ttl = 1
    t1 = pruning_trie.Trie(db)
    t2 = pruning_trie.Trie(db)
    t1.update(b'3', b'5')
    t2.update(b'3', b'5')
    t1.delete(b'3')
    db.commit_refcount_changes(0)
    db.cleanup(0)
    db.cleanup(1)
    db.cleanup(2)
    print(db.kv)
    print(t2.to_dict())


def test_block_18503_changes():
    pre = {'0x0c': '0x29d33c02a200937995e632c4597b4dca8e503978'}
    toadd = [
        ['0x', '0x09'],
    ]
    db = RefcountDB(EphemDB())
    db.logging = True
    NODES = 60
    t1 = pruning_trie.Trie(db)
    t2 = pruning_trie.Trie(db)
    db.ttl = NODES * 2
    c = 0
    for k, v in pre.items():
        triekey = utils.sha3(utils.zpad(utils.decode_hex(k[2:]), 32))
        t1.update(triekey, rlp.encode(utils.decode_hex(v[2:])))
        t2.update(triekey, rlp.encode(utils.decode_hex(v[2:])))
        db.commit_refcount_changes(c)
        db.cleanup(c)
        c += 1
    print(utils.encode_hex(t1.root_hash))
    for k, v in toadd:
        sys.stderr.write('kv: %s %s\n' % (k, v))
        triekey = utils.sha3(utils.zpad(utils.decode_hex(k[2:]), 32))
        if v == '0x':
            t1.delete(triekey)
        else:
            t1.update(triekey, rlp.encode(utils.decode_hex(v[2:])))
        db.commit_refcount_changes(c)
        db.cleanup(c)
        c += 1
    t1.clear_all()
    db.commit_refcount_changes(c)
    for i in range(db.ttl + 1):
        db.cleanup(c)
        c += 1
    t3 = pruning_trie.Trie(db)
    t3.root_hash = t2.root_hash
    print(t3.to_dict())


def test_shared_prefix():
    db = RefcountDB(EphemDB())
    db.logging = True
    db.ttl = 1
    t1 = pruning_trie.Trie(db)
    t2 = pruning_trie.Trie(db)
    t1.update(b'dogecoin', b'\x33' * 50)
    t1.update(b'dogelot', b'\x44' * 50)
    t2.update(b'dogecoin', b'\x33' * 50)
    t2.update(b'dogelot', b'\x44' * 50)
    print(db.kv)
    t1.delete(b'dogecoin')
    t1.delete(b'dogelot')
    print(db.kv)
    db.commit_refcount_changes(0)
    db.cleanup(0)
    db.cleanup(1)
    db.cleanup(2)
    print(db.kv)
    print(t2.to_dict())


def test_deep_inner_branch_deletion():
    db = RefcountDB(EphemDB())
    db.logging = True
    db.ttl = 1
    t1 = pruning_trie.Trie(db)
    t1.update(b'etherdogecoin', b'\x33' * 50)
    t1.update(b'etherdogelot', b'\x44' * 50)
    t1.delete(b'etherhouse')
    t1.delete(b'etherhouse')
    t1.delete(b'etherhouse')
    t1.delete(b'etherhouse')


def test_block_18315_changes():
    pre = {}
    toadd = [
        ['0x0000000000000000000000000000000000000000000000000000000000000000', '0xf9e88bc2b3203e764fe67b4d0f4171b7756117c8'],
        ['0x0000000000000000000000000000000000000000000000000000000000000001', '0x'],
        ['0x0000000000000000000000000000000000000000000000000000000000000002', '0x'],
    ]
    db = RefcountDB(EphemDB())
    db.logging = True
    NODES = 60
    t1 = pruning_trie.Trie(db)
    t2 = pruning_trie.Trie(db)
    db.ttl = NODES * 2
    c = 0
    for k, v in pre.items():
        triekey = utils.sha3(utils.zpad(k[2:].decode('hex'), 32))
        t1.update(triekey, rlp.encode(v[2:].decode('hex')))
        t2.update(triekey, rlp.encode(v[2:].decode('hex')))
        db.commit_refcount_changes(c)
        db.cleanup(c)
        c += 1
    sys.stderr.write('##############################\n')
    print(utils.encode_hex(t1.root_hash))
    print(t1.to_dict())
    for k, v in toadd:
        sys.stderr.write('kv: %s %s\n' % (k, v))
        triekey = utils.sha3(utils.zpad(utils.decode_hex(k[2:]), 32))
        if v == '0x':
            t1.delete(triekey)
        else:
            t1.update(triekey, rlp.encode(utils.decode_hex(v[2:])))
        db.commit_refcount_changes(c)
        db.cleanup(c)
        c += 1
    t1.clear_all()
    db.commit_refcount_changes(c)
    for i in range(db.ttl + 1):
        db.cleanup(c)
        c += 1
    t3 = pruning_trie.Trie(db)
    t3.root_hash = t2.root_hash
    print(t3.to_dict())


def check_testdata(data_keys, expected_keys):
    assert set(data_keys) == set(expected_keys), \
        "test data changed, please adjust tests"


def load_tests():
    try:
        fn = os.path.join(testutils.fixture_path, 'TrieTests', 'trietest.json')
        fixture = json.load(open(fn, 'r'))
    except IOError:
        raise IOError("Could not read trietests.json from fixtures",
                      "Make sure you did 'git submodule init'")
    expected_keys = set(['jeff', 'emptyValues', 'branchingTests'])
    assert set(fixture.keys()) == expected_keys, ("test data changed!", list(fixture.keys()))
    return fixture_to_bytes(fixture)


def run_test(name):

    pairs = load_tests()[name]

    def _dec(x):
        if utils.is_string(x) and x.startswith(b'0x'):
            return utils.decode_hex(x[2:])
        return x

    pairs['in'] = [(_dec(k), _dec(v)) for k, v in pairs['in']]
    deletes = [(k, v) for k, v in pairs['in'] if v is None]

    N_PERMUTATIONS = 100
    for i, permut in enumerate(itertools.permutations(pairs['in'])):
        if i > N_PERMUTATIONS:
            break
        db = RefcountDB(EphemDB())
        db.ttl = 0
        t = pruning_trie.Trie(db)
        for k, v in permut:
            # logger.debug('updating with (%s, %s)' %(k, v))
            if v is not None:
                t.update(k, v)
            else:
                t.delete(k)
        db.commit_refcount_changes(0)
        db.cleanup(0)
        # make sure we have deletes at the end
        for k, v in deletes:
            t.delete(k)
        t.clear_all()
        db.commit_refcount_changes(1)
        db.cleanup(1)
        assert len(db.kv) == 0
        assert pairs['root'] == b'0x' + utils.encode_hex(t.root_hash), (i, list(permut) + deletes)


def test_emptyValues():
    run_test('emptyValues')


def test_jeff():
    run_test('jeff')



# test_basic_pruning = None
# test_delayed_pruning = None
# test_clear = None
# test_delayed_clear = None
# test_insert_delete = None
# test_two_trees = None
# test_two_trees_with_clear = None
# test_revert_adds = None
# test_revert_deletes = None
# test_trie_transfer = None
# test_two_tries_with_small_root_node = None
# test_block_18503_changes = None
# test_shared_prefix = None
