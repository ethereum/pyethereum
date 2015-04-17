from ethereum import trie, db, utils
import sys


def benchmark(size):
    t = trie.Trie(db.EphemDB())
    for i in range(size):
        t.update(utils.sha3('k'+str(i)), utils.sha3('v'+str(i)))
    sz = sum([len(v) for k, v in t.db.db.items()])
    nsz = []
    for i in range(min(size, 100)):
        ldb = db.ListeningDB(t.db.db)
        odb = t.db
        t.db = ldb
        t.get(utils.sha3('k'+str(i)))
        nsz.append(sum([len(v) for k, v in ldb.kv.items()]))
        t.db = odb
    print sz, sum(nsz) // len(nsz)

benchmark(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
