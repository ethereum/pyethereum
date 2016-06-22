from ethereum import trie, db, utils
import sys


def benchmark(size):
    t = trie.Trie(db.EphemDB())
    for i in range(size):
        t.update(utils.sha3('k'+str(i)), utils.sha3('v'+str(i)))
    sz = sum([len(v) for k, v in t.db.db.items()])
    nsz = []
    ldb = db.ListeningDB(t.db.db)
    for i in range(min(size, 100)):
        ldb2 = db.ListeningDB(ldb)
        odb = t.db
        t.db = ldb2
        t.get(utils.sha3('k'+str(i)))
        nsz.append(sum([len(v) for k, v in ldb2.kv.items()]))
        t.db = odb
    ldbsz = sum([len(v) for k, v in ldb.kv.items()])
    print(sz, sum(nsz) // len(nsz), ldbsz)

benchmark(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
