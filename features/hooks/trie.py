import os
from os import path


class TrieHook(object):
    db_dir = "tmp"
    db_file_name = "trie-test.db"

    def __init__(self):
        self.db_path = path.join(self.db_dir, self.db_file_name)

    def before_feature(self, context, feature):
        from pyethereum import trie
        self._create_dir()
        self._delete_db()

        context.trie = trie.Trie(self.db_path)
        self._load_fixture()

    def after_feature(self, context, feature):
        del context.trie
        self._delete_db()

    def _create_dir(self):
        if not path.exists(self.db_dir):
            os.mkdir(self.db_dir)

    def _delete_db(self):
        import leveldb
        leveldb.DestroyDB(self.db_path)

    def _load_fixture(self):
        pass

    def before_scenario(self, context, scenario):
        pass

    def after_scenario(self, context, scenario):
        pass

hook = TrieHook()
