from ethereum.compress import compress, decompress
from ethereum import utils
from ethereum.slogging import get_logger
from rlp.utils import str_to_bytes
log = get_logger('db')


databases = {}


class _EphemDB(object):

    def __init__(self):
        self.db = {}

    def get(self, key):
        return decompress(self.db[key])

    def put(self, key, value):
        self.db[key] = compress(value)

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
