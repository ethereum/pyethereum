#!/usr/bin/python

import os
import leveldb
import rlp
from sha3 import sha3_256

from utils import print_func_call

def bin_to_nibbles(s):
    """convert string s to nibbles (half-bytes)

    >>> bin_to_nibbles("")
    []
    >>> bin_to_nibbles("h")
    [6, 8]
    >>> bin_to_nibbles("he")
    [6, 8, 6, 5]
    >>> bin_to_nibbles("hello")
    [6, 8, 6, 5, 6, 12, 6, 12, 6, 15]
    """
    res = []
    for x in s:
        res += divmod(ord(x), 16)
    return res


def nibbles_to_bin(nibbles):
    if any(x > 15 or x < 0 for x in nibbles):
        raise Exception("nibbles can only be [0,..15]")

    if len(nibbles) % 2:
        raise Exception("nibbles must be of even numbers")

    res = ''
    for i in range(0, len(nibbles), 2):
        res += chr(16 * nibbles[i] + nibbles[i + 1])
    return res


NIBBLE_TERMINATOR = 16


def with_terminator(nibbles):
    if not nibbles or nibbles[-1] != NIBBLE_TERMINATOR:
        nibbles.append(NIBBLE_TERMINATOR)
    return nibbles


def without_terminator(nibbles):
    if nibbles and nibbles[-1] == NIBBLE_TERMINATOR:
        del nibbles[-1]
    return nibbles


def adapt_terminator(nibbles, has_terminator):
    if has_terminator:
        with_terminator(nibbles)
    else:
        without_terminator(nibbles)
    return nibbles


def pack_nibbles(nibbles):
    """pack nibbles to binary

    :param nibbles: a nibbles sequence. may have a terminator
    """

    if nibbles[-1:] == [NIBBLE_TERMINATOR]:
        flags = 2
        nibbles = nibbles[:-1]
    else:
        flags = 0

    oddlen = len(nibbles) % 2
    flags |= oddlen   # set lowest bit if odd number of nibbles
    if oddlen:
        nibbles = [flags] + nibbles
    else:
        nibbles = [flags, 0] + nibbles
    o = ''
    for i in range(0, len(nibbles), 2):
        o += chr(16 * nibbles[i] + nibbles[i + 1])
    return o


def unpack_to_nibbles(bindata):
    """unpack packed binary data to nibbles

    :param bindata: binary packed from nibbles
    :return: nibbles sequence, may have a terminator
    """
    o = bin_to_nibbles(bindata)
    flags = o[0]
    if flags & 2:
        o.append(NIBBLE_TERMINATOR)
    if flags & 1 == 1:
        o = o[1:]
    else:
        o = o[2:]
    return o


def starts_with(full, part):
    ''' test whether the items in the part is
    the leading items of the full
    '''
    if len(full) < len(part):
        return False
    return full[:len(part)] == part


def sha3(x):
    return sha3_256(x).digest()


class DB(object):

    def __init__(self, dbfile):
        self.db = leveldb.LevelDB(dbfile)

    def get(self, key):
        return self.db.Get(key)

    def put(self, key, value):
        return self.db.Put(key, value)

    def delete(self, key):
        return self.db.Delete(key)


(
    NODE_TYPE_BLANK,
    NODE_TYPE_VALUE,
    NODE_TYPE_LEAF_KEY_VALUE,
    NODE_TYPE_INNER_KEY_VALUE,
    NODE_TYPE_DIVERGE_WITH_VALUE,
    NODE_TYPE_DIVERGE_WITHOUT_VALUE
) = tuple(range(6))


def is_diverge_type(node_type):
    return node_type in [NODE_TYPE_DIVERGE_WITH_VALUE,
                         NODE_TYPE_DIVERGE_WITHOUT_VALUE]


def is_key_value_type(node_type):
    return node_type in [NODE_TYPE_LEAF_KEY_VALUE,
                         NODE_TYPE_INNER_KEY_VALUE]

BLANK_NODE = ''


class Trie(object):
    databases = {}

    def __init__(self, dbfile, root=BLANK_NODE):
        '''
        :param dbfile: key value database
        :root: blank or trie node in form of [key, value] or [v0,v1..v15,v]
        '''
        self.root = root
        dbfile = os.path.abspath(dbfile)
        if dbfile not in self.databases:
            self.databases[dbfile] = DB(dbfile)
        self.db = self.databases[dbfile]

    def clear(self):
        ''' clear all tree data

        todo: remove saved (hash, value) from database
        '''
        self.root = BLANK_NODE

    def _inspect_node(self, node):
        ''' get node type and content

        :param node: node or hash
        :return: (NODE_TYPE_*, content), content is the decoded node,
        unless a key-value node, which will result a (key, value)
        with key is nibbles without the terminator
        '''
        content = self._rlp_decode(node)

        if not content:
            return (NODE_TYPE_BLANK, BLANK_NODE)

        if isinstance(content, str):
            return (NODE_TYPE_VALUE, content)

        if len(content) == 2:
            nibbles = unpack_to_nibbles(content[0])
            has_terminator = (nibbles and nibbles[-1] == NIBBLE_TERMINATOR)
            content = (without_terminator(nibbles), content[1])
            return (NODE_TYPE_LEAF_KEY_VALUE, content) if has_terminator\
                else (NODE_TYPE_INNER_KEY_VALUE, content)

        if len(content) == 17:
            return (NODE_TYPE_DIVERGE_WITH_VALUE, content) if content[-1]\
                else (NODE_TYPE_DIVERGE_WITHOUT_VALUE, content)

    def _get(self, node, key):
        """ get value inside a node

        :param node: node or hash
        :param key: nibble list without terminator
        :return: None if does not exist, otherwise value or hash
        """
        node_type, content = self._inspect_node(node)

        if node_type == NODE_TYPE_BLANK:
            return None

        if node_type == NODE_TYPE_VALUE:
            return None

        if is_diverge_type(node_type):
            # already reach the expected node
            if not key:
                return content[-1]
            return self._get(content[key[0]], key[1:])

        # key value node
        (curr_key, curr_val) = content
        if node_type == NODE_TYPE_LEAF_KEY_VALUE:
            if key == curr_key:
                return curr_val
            # not found
            else:
                return None

        if node_type == NODE_TYPE_INNER_KEY_VALUE:
            # traverse child nodes
            if starts_with(key, curr_key):
                return self._get(curr_val, key[len(curr_key):])
            else:
                return None

    def _rlp_encode(self, node):
        rlpnode = rlp.encode(node)
        if len(rlpnode) < 32:
            return node

        hashkey = sha3(rlpnode)
        self.db.put(hashkey, rlpnode)
        return hashkey

    def _rlp_decode(self, node):
        if not isinstance(node, (str, unicode)):
            return node
        elif len(node) == 0:
            return node
        elif len(node) < 32:
            return node
        else:
            return rlp.decode(self.db.get(node))

    def _update(self, node, key, value, value_is_node):
        """ update item inside a node

        :param node: node or hash
        :param key: nibble list without terminator
        :param value: node or hash
        :param value_is_node: value is leaf or intermediate node
        :return: the updated node or hash
        """
        # decode the node
        (node_type, content) = self._inspect_node(node)

        if node_type == NODE_TYPE_BLANK:
            # a inner node
            if value_is_node:
                if not key:
                    return value
                else:
                    return self._rlp_encode([pack_nibbles(key), value])
            else:
                return self._rlp_encode([pack_nibbles(with_terminator(key)),
                                         value])

        elif node_type == NODE_TYPE_VALUE:
            if not key:
                return value
            else:
                # a new diverge node
                new_node = [''] * 17
                new_node[-1] = node
                return self._update(new_node, key, value, value_is_node)

        elif is_diverge_type(node_type):
            # already the expected node
            if not key:
                content[-1] = value
                return self._rlp_encode(content)

            slot_type, slot = self._inspect_node(content[key[0]])
            content[key[0]] = self._update(content[key[0]], key[1:],
                                           value, value_is_node)
            return self._update(BLANK_NODE, [],
                                self._rlp_encode(content), value_is_node=True)

        elif is_key_value_type(node_type):
            return self._update_kv_node(node_type, content, key,
                                        value, value_is_node)

    def _update_kv_node(self, node_type, content, key, value, value_is_node):
        '''when the current node is a (key, value) node

        :param content: an  (key, value) tuple
        :param key: nibble list without terminator, must not be blank
        :param value: node or hash
        :return: the updated node or hash
        '''
        curr_key, curr_val = content
        curr_val_is_node = node_type != NODE_TYPE_LEAF_KEY_VALUE

        without_terminator(curr_key)

        # find longest common prefix
        prefix_length = 0
        for i in range(min(len(curr_key), len(key))):
            if key[i] != curr_key[i]:
                break
            prefix_length = i + 1

        # merge
        if not prefix_length:
            # a new diverge node
            diverge_node = [''] * 17
            diverge_node = self._update(diverge_node, curr_key, curr_val,
                                        curr_val_is_node)
            diverge_node = self._update(diverge_node, key, value,
                                        value_is_node)
            return diverge_node

        # create node for key postfix
        post_curr_key_node = self._update(
            BLANK_NODE, curr_key[prefix_length:], curr_val, curr_val_is_node)
        post_curr_key_node = self._update(
            post_curr_key_node, key[prefix_length:], value, value_is_node)

        post_curr_key_node_type, _ = self._inspect_node(post_curr_key_node)
        is_node = post_curr_key_node_type != NODE_TYPE_LEAF_KEY_VALUE

        # create node for key prefix
        pre_curr_key_node = self._update(
            BLANK_NODE, curr_key[:prefix_length], post_curr_key_node, is_node)

        return pre_curr_key_node

    def delete(self, key):
        if not isinstance(key, (str, unicode)):
            raise Exception("Key must be strings")
        if not key:
            raise Exception("Key should not be blank")

        if len(key) > 32:
            raise Exception("Max key length is 32")

        key = bin_to_nibbles(str(key))

        self.root = self._update(self.root, key, BLANK_NODE, True)
        return self.root

    def _get_size(self, node):
        '''Get counts of (key, value) stored in this and the descendant nodes
        '''
        (node_type, node) = self._inspect_node(node)
        if node_type == NODE_TYPE_BLANK:
            return 0
        elif node_type == NODE_TYPE_VALUE:
            return 1
        elif node_type == NODE_TYPE_KEY_VALUE:
            (key_bin, value) = node
            return self._get_size(value)
        elif node_type == NODE_TYPE_DIVERGE:
            return sum([self._get_size(node[x]) for x in range(16)]) \
                + (1 if node[-1] else 0)

    def _to_dict(self, node):
        '''convert (key, value) stored in this and the descendant nodes
        to dict items.

        .. note:: Here key is in full form,
        rather than key of the individual node
        '''
        (node_type, node) = self._inspect_node(node)

        if node_type == NODE_TYPE_BLANK:
            return {}

        elif node_type == NODE_TYPE_VALUE:
            return {'': self._rlp_decode(node)}

        elif node_type == NODE_TYPE_KEY_VALUE:
            (key_bin, value) = node
            key = '+'.join([str(x) for x in unpack_to_nibbles(key_bin)])
            sub_dict = self._to_dict(value)

            # prepend key of this node to the keys of children
            res = {}
            for sub_key, sub_value in sub_dict.iteritems():
                full_key = '{0}+{1}'.format(key, sub_key) if sub_key else key
                res[full_key] = sub_value
            return res

        elif node_type == NODE_TYPE_DIVERGE:
            res = {}
            for i in range(16):
                sub_dict = self._to_dict(node[i])

                for sub_key, sub_value in sub_dict.iteritems():
                    full_key = '{0}+{1}'.format(i, sub_key) if sub_key else i
                    res[full_key] = sub_value

            if node[-1]:
                res[str(NIBBLE_TERMINATOR)] = self._rlp_decode(node[-1])
            return res

    def to_dict(self, as_hex=False):
        d = self._to_dict(self.root)
        res = {}
        for key_str, value in d.iteritems():
            nibbles = [int(x) for x in key_str.split('+')]
            key = nibbles_to_bin(without_terminator(nibbles))
            res[key] = value
        return res

    def get(self, key):
        rlp_value = self._get(self.root, bin_to_nibbles(str(key)))
        return self._rlp_decode(rlp_value) if rlp_value is not None else None

    def get_size(self):
        return self._get_size(self.root)

    def update(self, key, value):
        if not isinstance(key, (str, unicode)) or\
                not isinstance(value, (str, unicode)):
            raise Exception("Key and value must be strings")
        if not key:
            raise Exception("Key should not be blank")

        if len(key) > 32:
            raise Exception("Max key length is 32")

        self.root = self._update(
            self.root,
            bin_to_nibbles(str(key)),
            self._rlp_encode(value),
            value_is_node=False)
        return self._rlp_decode(self.root)

if __name__ == "__main__":
    import sys

    def encode_node(nd):
        if isinstance(nd, str):
            return nd.encode('hex')
        else:
            return rlp.encode(nd).encode('hex')

    if len(sys.argv) >= 2:
        if sys.argv[1] == 'insert':
            t = Trie(sys.argv[2], sys.argv[3].decode('hex'))
            t.update(sys.argv[4], sys.argv[5])
            print encode_node(t.root)
        elif sys.argv[1] == 'get':
            t = Trie(sys.argv[2], sys.argv[3].decode('hex'))
            print t.get(sys.argv[4])
