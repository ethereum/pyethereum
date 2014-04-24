import leveldb

databases = {}


class DB(object):

    def __init__(self, dbfile):
        if dbfile not in databases:
            databases[dbfile] = leveldb.LevelDB(dbfile)
        self.db = databases[dbfile]
        self.uncommitted = {}

    def get(self, key):
        if key in self.uncommitted:
            return self.uncommitted[key]
        return self.db.Get(key)

    def put(self, key, value):
        self.uncommitted[key] = value

    def commit(self):
        batch = leveldb.WriteBatch()
        for k in self.uncommitted:
            batch.Put(k, self.uncommitted[k])
        self.db.Write(batch, sync=True)

    def delete(self, key):
        return self.db.Delete(key)
