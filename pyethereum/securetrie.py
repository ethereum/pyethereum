import rlp
from pyethereum import utils


class SecureTrie(object):

    def __init__(self, t):
        self.trie = t
        self.db = t.db

    def update(self, k, v):
        h = utils.sha3(k)
        self.db.put(h, k)
        self.trie.update(h, v)

    def get(self, k):
        return self.trie.get(utils.sha3(k))

    def delete(self, k):
        self.trie.delete(utils.sha3(k))

    def to_dict(self):
        o = {}
        for h, v in list(self.trie.to_dict().items()):
            k = self.db.get(h)
            o[k] = v
        return o

    def root_hash_valid(self):
        return self.trie.root_hash_valid()

    @property
    def root_hash(self):
        return self.trie.root_hash

    @root_hash.setter
    def root_hash(self, value):
        self.trie.root_hash = value
