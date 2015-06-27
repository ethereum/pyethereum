import ethereum.pruning_trie as pruning_trie
from ethereum.db import EphemDB
import rlp
import ethereum.utils as utils
import sys


def test_basic_pruning():
    db = EphemDB()
    NODES = 60

    t = pruning_trie.Trie(db)
    t.death_row_timeout = 0

    for i in range(NODES):
        t.update(str(i), str(i))
        t.commit_death_row(0)
        t.process_epoch(0)
        if len(db.kv) != len(t.all_nodes()):
            a = t.all_nodes()
            for k in db.kv:
                if k not in a:
                    print utils.encode_hex(k)
            raise Exception("unpruned key leak: %d %d" % (len(db.kv), len(t.all_nodes())))
    for i in range(NODES):
        t.update(str(i), str(i ** 3))
        t.commit_death_row(0)
        t.process_epoch(0)
        if len(db.kv) != len(t.all_nodes()):
            a = t.all_nodes()
            for k in db.kv:
                if k not in a:
                    print utils.encode_hex(k)
            raise Exception("unpruned key leak: %d %d" % (len(db.kv), len(t.all_nodes())))
    for i in range(NODES):
        t.delete(str(i))
        t.commit_death_row(0)
        t.process_epoch(0)
        if len(db.kv) != len(t.all_nodes()):
            a = t.all_nodes()
            for k in db.kv:
                if k not in a:
                    print utils.encode_hex(k)
            raise Exception("unpruned key leak: %d %d" % (len(db.kv), len(t.all_nodes())))
    assert len(t.to_dict()) == 0
    assert len(db.kv) == 0


def test_delayed_pruning():
    db = EphemDB()
    NODES = 60
    t = pruning_trie.Trie(db)
    t.death_row_timeout = NODES // 4
    for i in range(NODES):
        t.update(str(i), str(i))
        t.commit_death_row(i)
        t.process_epoch(i)
    for i in range(NODES):
        t.update(str(i), str(i ** 3))
        t.commit_death_row(i + NODES)
        t.process_epoch(i + NODES)
    for i in range(NODES):
        t.delete(str(i))
        t.commit_death_row(i + NODES * 2)
        t.process_epoch(i + NODES * 2)
    for i in range(NODES // 4):
        t.process_epoch(i + NODES * 3)
    assert len(t.to_dict()) == 0
    assert len(db.kv) == 0


def test_clear():
    db = EphemDB()
    NODES = 60
    t = pruning_trie.Trie(db)
    t.death_row_timeout = NODES // 4
    for i in range(NODES):
        t.update(str(i), str(i))
        t.commit_death_row(i)
        t.process_epoch(i)
    t.clear_all()
    t.commit_death_row(NODES)
    t.process_epoch(NODES)
    for i in range(NODES // 4 + 1):
        t.process_epoch(i + NODES)
    assert len(db.kv) == 0


def test_two_trees():
    db = EphemDB()
    NODES = 60
    t1 = pruning_trie.Trie(db)
    t1.death_row_timeout = NODES // 4
    t2 = pruning_trie.Trie(db)
    t2.death_row_timeout = NODES // 4
    for i in range(NODES):
        t1.update(str(i), str(i))
        if i < NODES // 2:
            t2.update(str(i), str(i))
        t1.commit_death_row(i)
        t2.commit_death_row(i)
        t1.process_epoch(i)
    for i in range(NODES):
        t1.delete(str(NODES - 1 - i))
        t1.commit_death_row(NODES + i)
        t1.process_epoch(NODES + i)
    assert t2.to_dict() == {str(i): str(i) for i in range(NODES // 2)}
    for i in range(NODES // 2):
        t2.delete(str(i))
        t2.commit_death_row(NODES * 2 + i)
        t1.process_epoch(NODES * 2 + i)
    for i in range(NODES // 4):
        t1.process_epoch(NODES * 2 + NODES // 2 + i)
    assert len(db.kv) == 0


def test_two_trees_with_clear():
    db = EphemDB()
    NODES = 60
    t1 = pruning_trie.Trie(db)
    t1.death_row_timeout = NODES // 4
    t2 = pruning_trie.Trie(db)
    t2.death_row_timeout = NODES // 4
    for i in range(NODES):
        t1.update(str(i), str(i))
        if i < NODES // 2:
            t2.update(str(i), str(i))
        t1.commit_death_row(i)
        t2.commit_death_row(i)
        t1.process_epoch(i)
    t1.clear_all()
    t1.commit_death_row(NODES)
    assert t2.to_dict() == {str(i): str(i) for i in range(NODES // 2)}
    for i in range(NODES // 2):
        t2.delete(str(i))
        t2.commit_death_row(NODES + i)
        t1.process_epoch(NODES + i)
    for i in range(NODES // 4):
        t1.process_epoch(NODES + NODES // 2 + i)
    assert len(db.kv) == 0
