import db
import rlp
import utils


class LevelNode(object):

    '''node for a multiple level tree

    each node corresponds to a (key, value) pair for the key-value DB, here
    *value* is one of the following case:

    #.  for a intermediate node, the *value* is a list of subnode key
    #.  for a leaf node, the *value* is a string or a list of string
    '''
    def __init__(self, db, key, value=None, parent=None):
        self.key = key
        self.value = value
        self.value_hash_saved = self.compute_hash(value)
        self.parent = parent
        self.db = db

    @classmethod
    def compute_hash(cls, value):
        if value is None:
            return None
        return utils.sha3(rlp.encode(value))

    @classmethod
    def load_value(cls, db, key):
        return rlp.decode(db.get(key))

    def set_sanity(self):
        self.value_hash_saved = self.value

    def delete(self):
        # delete this node
        self.db.delete(self.key)
        if self.parent:
            self.parent.value.remove(self.key)
            self.parent.save_util_root()
            self.set_sanity()

    def save_util_root(self):
        new_hash = self.compute_hash(self.value)

        # not changed
        if self.value_hash_saved == new_hash:
            return

        if self.value_hash_saved and new_hash is None:
            self.delete()

        # self is already root node
        if not self.parent:
            self.db.put(self.key, rlp.encode(self.value))
            self.db.commit()
            self.set_sanity()
            return

        # self is intermediate node
        self.db.put(new_hash, rlp.encode(self.value))

        # update parent value
        if self.value_hash_saved is None:
            # newly created
            self.parent.value.append(new_hash)
        else:
            # modified
            self.parent.value[self.parent.value.index(self.key)] = self.key

        self.parent.save_util_root()
        self.set_sanity()

    def __len__(self):
        self.value.__len__()

    def __getitem__(self, key):
        self.value.__getitem__(key)

    def __setitem__(self, key, value):
        self.value.__setitem__()

    def __delitem__(self, key):
        self.value.__delitem__()

    def __iter__(self):
        self.value.__iter__()

    def __reversed__(self):
        self.value.__reversed__()

    def __contains__(self, item):
        self.value.__contains__(item)


class AccountTxIndex(object):
    '''two level for this index:

    #.  acccount
    #.  pagination
    '''
    def __init__(self):
        self.db = db.DB(utils.get_db_path())
        self.pagenation = 1000

    def create_account_node(self, account):
        account_node = LevelNode(self.db, account)
        account_node.save_util_root()
        return account_node

    def get_account_node(self, account):
        if account not in self.db:
            return None

        account_node = LevelNode(self.db, key=account,
                                 value=LevelNode.load_value(self.db, account))
        return account_node

    def get_or_create_account_node(self, account):
        account_node = self.get_account_node(account)
        if account_node is None:
            return self.create_account_node()
        return account_node

    def get_page_node(self, account_node, page):
        if page >= len(account_node):
            return None
        key = account_node[page]
        return LevelNode(self.db, key=key,
                         value=LevelNode.load_value(self.db, key))

    def create_page_node(self, account_node):
        page_node = LevelNode(self.db, key=LevelNode.compute_hash([]),
                              value=[], parent=account_node)
        return page_node

    def get_all_page_iter(self, account_node):
        # second level
        for key in account_node:
            yield LevelNode.load_value(self.db, key)

    def get_all_tx_iter(self, account_node):
        page_iter = self.get_page_iter(account_node)
        for tx in page_iter:
            yield tx

    def get_tx_range_iter(self, account_node, offset, count):
        page, inner_offset = divmod(offset, self.pagenation)
        i = 0
        while True:
            if page >= len(account_node):
                return
            page_txs = LevelNode.load_value(self.db, account_node[page])
            while inner_offset < len(page_txs):
                if i >= count:
                    return
                yield page_txs[inner_offset]
                i = i + 1
                inner_offset = inner_offset + 1
            page = page + 1

    def add_tx(self, account, tx):
        self.add_txs(self.get_or_create_account_node(account), [tx])

    def add_txs(self, account_node, txs):
        if not txs:
            return
        if not len(account_node):
            page_node = self.create_page_node(account_node)
        else:
            page_node = self.get_page_node(account_node, len(account_node)-1)
        for tx in txs:
            if len(page_node) >= self.pagenation:
                page_node.save_util_root()
                page_node = self.create_page_node(account_node)
            page_node.append(tx)
        page_node.save_util_root()
