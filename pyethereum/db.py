import os
import leveldb
import threading
import compress
from pyethereum.slogging import get_logger
log = get_logger('db')


class DB(object):

    def __init__(self, dbfile):
        self.dbfile = os.path.abspath(dbfile)
        self.db = leveldb.LevelDB(dbfile)
        self.uncommitted = dict()
        self.lock = threading.Lock()

    def get(self, key):
        if key in self.uncommitted:
            if self.uncommitted[key] is None:
                raise Exception("key not in db")
            return self.uncommitted[key]
        o = compress.decompress(self.db.Get(key))
        self.uncommitted[key] = o
        return o

    def put(self, key, value):
        with self.lock:
            self.uncommitted[key] = value

    def commit(self):
        log.debug('commit', db=self)
        with self.lock:
            batch = leveldb.WriteBatch()
            for k, v in self.uncommitted.iteritems():
                if v is None:
                    batch.Delete(k)
                else:
                    batch.Put(k, compress.compress(v))
            self.db.Write(batch, sync=False)
            self.uncommitted.clear()

    def delete(self, key):
        with self.lock:
            self.uncommitted[key] = None

    def _has_key(self, key):
        try:
            self.get(key)
            return True
        except KeyError:
            return False

    def __contains__(self, key):
        return self._has_key(key)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.db == other.db

    def __repr__(self):
        return '<DB at %d uncommitted=%d>' % (id(self.db), len(self.uncommitted))


class EphemDB(object):

    def __init__(self):
        self.db = {}

    def get(self, key):
        return self.db[key]

    def put(self, key, value):
        self.db[key] = value

    def delete(self, key):
        del self.db[key]

    def commit(self):
        pass

    def _has_key(self, key):
        return key in self.db

    def __contains__(self, key):
        return self._has_key(key)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.db == other.db
