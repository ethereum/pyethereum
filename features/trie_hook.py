import os
from os import path

class TrieFeatureHooker(object):
    db_dir = "tmp"
    db_file_name = "trie-test.db"

    def __init__(self):
        self.db_path = path.join(self.db_dir, self.db_file_name)

    def before(self, context, feature):
        from pyethereum import trie
        self.__create_dir()
        self.__delete_db()

        context.trie = trie.Trie(self.db_path)
        self.__load_fixture()

    def after(self, context, feature):
        del context.trie
        self.__delete_db()

    def __create_dir(self):
        if not path.exists(self.db_dir):
            os.mkdir(self.db_dir)

    def __delete_db(self):
        import leveldb
        leveldb.DestroyDB(self.db_path)

    def __load_fixture(self):
        pass

trie_feature_hooker = TrieFeatureHooker()
