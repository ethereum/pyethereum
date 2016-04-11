from ethereum import utils
from rlp.utils import str_to_bytes

from .base_db import BaseDB

# Used for making temporary objects
class OverlayDB(BaseDB):

    def __init__(self, db):
        self.db = db
        self.kv = None
        self.overlay = {}

    def get(self, key):
        if key in self.overlay:
            if self.overlay[key] is None:
                raise KeyError()
            return self.overlay[key]
        return self.db.get(key)

    def put(self, key, value):
        self.overlay[key] = value

    def delete(self, key):
        self.overlay[key] = None

    def commit(self):
        pass

    def __contains__(self, key):
        if key in self.overlay:
            return self.overlay[key] is not None
        return key in self.db

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.db == other.db

    def __hash__(self):
        return utils.big_endian_to_int(str_to_bytes(self.__repr__()))

    def inc_refcount(self, key, value):
        self.put(key, value)

    def dec_refcount(self, key):
        pass

    def revert_refcount_changes(self, epoch):
        pass

    def commit_refcount_changes(self, epoch):
        pass

    def cleanup(self, epoch):
        pass

    def put_temporarily(self, key, value):
        self.inc_refcount(key, value)
        self.dec_refcount(key)
