import os
import leveldb
import threading
import logging
logger = logging.getLogger(__name__)

databases = {}


class DB(object):

    def __init__(self, dbfile):
        self.dbfile = os.path.abspath(dbfile)
        if dbfile not in databases:
            logger.debug('Opening db #%d @%r', len(databases)+1, dbfile)
            databases[dbfile] = (leveldb.LevelDB(dbfile), dict(), threading.Lock())
        self.db, self.uncommitted, self.lock = databases[dbfile]
#        logger.debug('%r initialized', self)

    def get(self, key):
#        logger.debug('%r: get:%r uncommited:%r', self, key, key in self.uncommitted)
        if key in self.uncommitted:
            return self.uncommitted[key]
        return self.db.Get(key)

    def put(self, key, value):
#       logger.debug('%r: put:%r:%r', self, key, value)
        with self.lock:
            self.uncommitted[key] = value

    def commit(self):
        logger.debug('%r: commit', self)
        with self.lock:
            batch = leveldb.WriteBatch()
            for k, v in self.uncommitted.iteritems():
                batch.Put(k, v)
            self.db.Write(batch, sync=False)
            self.uncommitted.clear()

    def delete(self, key):
#        logger.debug('%r: delete %r', self, key)
        with self.lock:
            if key in self.uncommitted:
                del self.uncommitted[key]
                if key in self:
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
