from ethereum import utils
from ethereum.slogging import get_logger
from rlp.utils import str_to_bytes
log = get_logger('db')


databases = {}


class _EphemDB(object):

    def __init__(self):
        self.db = {}
        self.kv = self.db

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
        return utils.big_endian_to_int(str_to_bytes(self.__repr__()))


DB = EphemDB = _EphemDB


# Used for SPV proof creation
class ListeningDB(object):

    def __init__(self, db):
        self.parent = db
        self.kv = {}

    def get(self, key):
        if key not in self.kv:
            self.kv[key] = self.parent.get(key)
        return self.parent.get(key)

    def put(self, key, value):
        self.parent.put(key, value)

    def commit(self):
        pass

    def delete(self, key):
        self.parent.delete(key)

    def _has_key(self, key):
        return self.parent._has_key(key)

    def __contains__(self, key):
        return self.parent.__contains__(key)

    def __eq__(self, other):
        return self.parent == other

    def __hash__(self):
        return self.parent.__hash__()
