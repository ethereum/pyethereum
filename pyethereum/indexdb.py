import struct
import db
from utils import get_index_path


class AccountTxIndex(object):
    "acct|nonce > tx"

    def __init__(self):
        self.db = db.DB(get_index_path())

    def _key(self, account, nonce):
        return account + struct.pack('>I', nonce)

    def add_transaction(self, account, nonce, transaction_hash):
        self.db.put(self._key(account, nonce), transaction_hash)

    def get_transactions(self, account, offset=0):
        assert not self.db.uncommitted
        account_from = self._key(account, offset)
        for k, v in self.db.db.RangeIter(include_value=True,
                                         key_from=account_from):
            if k.startswith(account) and struct.unpack('>I', k[-4:]) >= offset:
                yield v

    def delete_transactions(self, account, offset=0):
        while self._key(account, offset) in self.db:
            self.db.delete(self._key(account, offset))
            offset += 1

    def get_accounts(self, account_from=None):
        assert not self.db.uncommitted
        zero = struct.pack('>I', 0)
        for key in self.db.db.RangeIter(include_value=False,
                                        key_from=account_from):
            if key.endswith(zero):
                yield key[:-4]

    def num_transactions(self, account, start=0):
        if self._key(account, start) not in self.db:
            return start
        test = start + 1
        while self._key(account, test*2) in self.db:
            test *= 2
        return self.num_transactions(account, test)
