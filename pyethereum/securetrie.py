import rlp, utils


class SecureTrie(object):

    def __init__(self, t):
        self.trie = t
        self.db = t.db

    def update(self, k, v):
        self.trie.update(utils.sha3(k), rlp.encode([k, v]))

    def get(self, k):
        x = self.trie.get(utils.sha3(k))
        return rlp.decode(x)[1] if x else ''

    def delete(self, k):
        self.trie.delete(utils.sha3(k))

    def to_dict(self):
        o = {}
        for k, v in self.trie.to_dict().items():
            key, value = rlp.decode(v)
            o[key] = value
        return o

    def root_hash_valid(self):
        return self.trie.root_hash_valid()

    @property
    def root_hash(self):
        return self.trie.root_hash

    @root_hash.setter
    def root_hash(self, value):
        self.trie.root_hash = value
