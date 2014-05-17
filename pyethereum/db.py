import leveldb

databases = {}


class DB(object):

    def __init__(self, dbfile):
        self.dbfile = dbfile
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
        for k, v in self.uncommitted.iteritems():
            batch.Put(k, v)
        self.db.Write(batch, sync=True)
        self.uncommitted = {}

    def delete(self, key):
        if key in self.uncommitted:
            del self.uncommitted[key]
            if key not in self:
                self.db.Delete(key)
        else:
            self.db.Delete(key)

    def _has_key(self, key):
        try:
            self.get(key)
            return True
        except KeyError:
            return False

    def __contains__(self, key):
        return self._has_key(key)
