import os
import threading
from pyethereum.compress import compress, decompress
from hashlib import md5
from pyethereum.slogging import get_logger
from rlp.utils import str_to_bytes
log = get_logger('db')


compress = decompress = lambda x: x  # compress is broken

databases = {}


try:
    from CodernityDB.database import Database, DatabasePathException,  \
        RecordNotFound
    from CodernityDB.hash_index import HashIndex
except ImportError:
    _CodernityDB = None
else:
    class MD5Index(HashIndex):

        def __init__(self, *args, **kwargs):
            kwargs['key_format'] = '16s'
            super(MD5Index, self).__init__(*args, **kwargs)

        def make_key_value(self, data):
            return md5(data['key']).digest(), None

        def make_key(self, key):
            return md5(key).digest()

    class _CodernityDB(object):

        def __init__(self, dbfile):
            self.dbfile = os.path.abspath(dbfile)
            if dbfile in databases:
                self.db = databases[dbfile]
                assert isinstance(self.db, self.db.__class__)
            else:
                self.db = Database(dbfile)
                try:
                    self.db.open()
                except DatabasePathException:
                    self.db.create()
                    self.db.add_index(MD5Index(dbfile, 'key'))
                databases[dbfile] = self.db
            self.uncommitted = dict()
            self.uncommitted_lock = threading.Lock()

        def get(self, key):
            if key in self.uncommitted:
                if self.uncommitted[key] is None:
                    raise KeyError("key not in db")
                return self.uncommitted[key]
            try:
                value = self.db.get('key', key, with_doc=True)['doc']['value']
            except RecordNotFound:
                raise KeyError("key not in db")
            return decompress(str_to_bytes(value))

        def put(self, key, value):
            with self.uncommitted_lock:
                self.uncommitted[key] = value

        def commit(self):
            log.debug('commit', db=self)
            with self.uncommitted_lock:
                for k, v in self.uncommitted.items():
                    if v is None:
                        doc = self.db.get('key', k, with_doc=True)['doc']
                        self.db.delete(doc)
                    else:
                        self.db.insert({'key': k, 'value': compress(v)})
                self.uncommitted.clear()

        def delete(self, key):
            with self.uncommitted_lock:
                self.uncommitted[key] = None

        def __contains__(self, key):
            try:
                self.get(key)
            except KeyError:
                return False
            return True

        def __eq__(self, other):
            return isinstance(other, self.__class__) and self.db == other.db

        def __hash__(self):
            from pyethereum import utils
            return utils.big_endian_to_int(str_to_bytes(self.__repr__()))

        def __repr__(self):
            return '<DB at %d uncommitted=%d>' % (id(self.db), len(self.uncommitted))

        def delete_db(self):
            del databases[self.dbfile]

try:
    import leveldb
except ImportError:
    _LevelDB = None
else:
    class _LevelDB(object):

        def __init__(self, dbfile):
            self.dbfile = os.path.abspath(dbfile)
            if dbfile in databases:
                self.db = databases[dbfile]
                assert isinstance(self.db, leveldb.LevelDB)
            else:
                self.db = leveldb.LevelDB(dbfile)
                databases[dbfile] = self.db
            self.uncommitted = dict()
            self.lock = threading.Lock()

        def get(self, key):
            if key in self.uncommitted:
                if self.uncommitted[key] is None:
                    raise KeyError("key not in db")
                return self.uncommitted[key]
            o = decompress(str_to_bytes(self.db.Get(key)))
            self.uncommitted[key] = o
            return o

        def put(self, key, value):
            with self.lock:
                self.uncommitted[key] = value

        def commit(self):
            log.debug('commit', db=self)
            with self.lock:
                batch = leveldb.WriteBatch()
                for k, v in self.uncommitted.items():
                    if v is None:
                        batch.Delete(k)
                    else:
                        batch.Put(k, compress(v))
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

        def __hash__(self):
            from pyethereum import utils
            return utils.big_endian_to_int(str_to_bytes(self.__repr__()))

        def __repr__(self):
            return '<DB at %d uncommitted=%d>' % (id(self.db), len(self.uncommitted))

        def delete_db(self):
            del databases[self.dbfile]


class _EphemDB(object):

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

    def __hash__(self):
        from pyethereum import utils
        return utils.big_endian_to_int(str_to_bytes(self.__repr__()))


DB = _LevelDB or _CodernityDB
assert DB is not None
EphemDB = _EphemDB
