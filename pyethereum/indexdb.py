import struct
import db
from utils import get_index_path


class Index(object):

    """
    stores a list of values for a key
    datastructure: namespace|key|valnum > val
    """

    def __init__(self, namespace):
        self.namespace = namespace
        self.db = db.DB(get_index_path())

    def _key(self, key, valnum=None):
        return self.namespace + key + struct.pack('>I', valnum)

    def add(self, key, valnum, value):
        assert isinstance(value, str)
        self.db.put(self._key(key, valnum), value)
        self.db.commit()

    def append(self, key, value):
        self.add(key, self.num_values(key), value)

    def get(self, key, offset=0):
        assert not self.db.uncommitted
        key_from = self._key(key, offset)
        for k, v in self.db.db.RangeIter(include_value=True,
                                         key_from=key_from):
            if k.startswith(self.namespace + key) and struct.unpack('>I', k[-4:]) >= offset:
                yield v

    def delete(self, key, offset=0):
        while self._key(key, offset) in self.db:
            self.db.delete(self._key(key, offset))
            offset += 1

    def keys(self, key_from=''):
        assert not self.db.uncommitted
        zero = struct.pack('>I', 0)
        for key in self.db.db.RangeIter(include_value=False,
                                        key_from=self.namespace + key_from):
            if key.endswith(zero):
                yield key[len(self.namespace):-4]

    def num_values(self, key, start=0):
        if self._key(key, start) not in self.db:
            return start
        test = start + 1
        while self._key(key, test * 2) in self.db:
            test *= 2
        return self.num_values(key, test)


class AccountTxIndex(Index):

    "acct|txnonce > tx"

    def __init__(self):
        super(AccountTxIndex, self).__init__('tx')

    def add_transaction(self, account, nonce, transaction_hash):
        self.add(account, nonce, transaction_hash)

    def get_transactions(self, account, offset=0):
        return self.get(account, offset)

    def delete_transactions(self, account, offset=0):
        self.delete(account, offset)

    def get_accounts(self, account_from=None):
        return self.keys(key_from=account_from)

    def num_transactions(self, account, start=0):
        return self.num_values(account)
