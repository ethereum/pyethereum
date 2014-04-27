#!/usr/bin/env python

import os
import rlp
from utils import sha3
from db import DB


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


(
    NODE_TYPE_BLANK,
    NODE_TYPE_LEAF_KEY_VALUE,
    NODE_TYPE_INNER_KEY_VALUE,
    NODE_TYPE_DIVERGE_WITH_VALUE,
    NODE_TYPE_DIVERGE_WITHOUT_VALUE
) = tuple(range(5))


def is_diverge_type(node_type):
    return node_type in [NODE_TYPE_DIVERGE_WITH_VALUE,
                         NODE_TYPE_DIVERGE_WITHOUT_VALUE]


def is_key_value_type(node_type):
    return node_type in [NODE_TYPE_LEAF_KEY_VALUE,
                         NODE_TYPE_INNER_KEY_VALUE]

BLANK_NODE = ''


class Trie(object):

    def __init__(self, dbfile, root=BLANK_NODE):
        '''
        :param dbfile: key value database
        :root: blank or trie node in form of [key, value] or [v0,v1..v15,v]
        '''
        self.root = root
        dbfile = os.path.abspath(dbfile)
        self.db = DB(dbfile)

    def clear(self):
        ''' clear all tree data
        '''
        # FIXME: remove saved (hash, value) from database
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

        if len(content) == 2:
            nibbles = unpack_to_nibbles(content[0])
            has_terminator = (nibbles and nibbles[-1] == NIBBLE_TERMINATOR)
            content = (without_terminator(nibbles), content[1])
            return (NODE_TYPE_LEAF_KEY_VALUE, content) if has_terminator\
                else (NODE_TYPE_INNER_KEY_VALUE, content)

        if len(content) == 17:
            return (NODE_TYPE_DIVERGE_WITH_VALUE, content) if content[-1]\
                else (NODE_TYPE_DIVERGE_WITHOUT_VALUE, content)

    def _get(self, node, is_node, key):
        """ get value inside a node

        :param node: node or hash
        :param is_node: node is a node or a value
        :param key: nibble list without terminator
        :return: None if does not exist, otherwise value or hash
        is_node denote whether the node is a node or a value
        """
        if not is_node:
            if not key:
                return node, False
            return None, False

        node_type, content = self._inspect_node(node)

        if node_type == NODE_TYPE_BLANK:
            return None, False

        if is_diverge_type(node_type):
            # already reach the expected node
            if not key:
                return content[-1] if content[-1] else None, False
            return self._get(content[key[0]], True, key[1:])

        # key value node
        (curr_key, curr_val) = content
        if node_type == NODE_TYPE_LEAF_KEY_VALUE:
            if key == curr_key:
                return curr_val, True
            # not found
            else:
                return None, True

        if node_type == NODE_TYPE_INNER_KEY_VALUE:
            # traverse child nodes
            if starts_with(key, curr_key):
                return self._get(curr_val, True, key[len(curr_key):])
            else:
                return None, True

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

    def _update(self, node, is_node, key, value, value_is_node):
        """ update item inside a node

        :param node: node or hash
        :param is_node: node is a node or a value
        :param key: nibble list without terminator
        :param value: node or hash, a blank node means to delete it
        :param value_is_node: value is leaf or intermediate node
        :return: (node, is_node) where `node` is the updated normalized node
        or hash, `is_node` denote whether the node is a node or a value
        """
        # FIXME: delete unused data from db
        if not is_node:
            if not key:
                return value, value_is_node
            else:
                # a new diverge node
                new_node = [''] * 17
                new_node[-1] = node
                new_node[key[0]] = self._update(
                    BLANK_NODE, True, key[1:], value, value_is_node)
                return self._normalize_node(
                    self._rlp_encode(new_node), True)

        # node is a node, rather than a value
        (node_type, content) = self._inspect_node(node)

        if node_type == NODE_TYPE_BLANK:
            if not value_is_node:
                return self._normalize_node(
                    self._rlp_encode(
                        [pack_nibbles(with_terminator(key)), value]),
                    True)
            # a inner node
            else:
                if value == BLANK_NODE:
                    return BLANK_NODE, True

                return self._normalize_node(
                    self._rlp_encode([pack_nibbles(key), value]), True)

        elif is_diverge_type(node_type):
            return self._update_diverge_node(node_type, content, key,
                                             value, value_is_node)

        elif is_key_value_type(node_type):
            return self._update_kv_node(node_type, content, key,
                                        value, value_is_node)

    def _update_diverge_node(self, node_type, content,
                             key, value, value_is_node):
        if key:
            content[key[0]], slot_is_node = self._update(
                content[key[0]], True, key[1:], value, value_is_node)
        else:
            content[-1] = value

        return self._normalize_node(
            self._rlp_encode(content), True)

    def _update_kv_node(self, node_type, content, key, value, value_is_node):

        '''when the current node is a (key, value) node

        :param content: an  (key, value) tuple
        :param key: nibble list without terminator, must not be blank
        :param value: node or hash
        :return: the updated node or hash

        .. note::

            (key, value, value_is_node) has already normalized,
            content itself as a valid node should already be normalized too
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

        if not prefix_length:
            return self._merge_two_pairs(curr_key, curr_val, curr_val_is_node,
                                         key, value, value_is_node)

        # create node for key postfix
        post_curr_key_node, is_node = self._update(
            BLANK_NODE, True,
            curr_key[prefix_length:], curr_val, curr_val_is_node)

        post_curr_key_node, is_node = self._update(
            post_curr_key_node, is_node,
            key[prefix_length:], value, value_is_node)

        # create node for key prefix
        return self._update(
            BLANK_NODE, True,
            curr_key[:prefix_length], post_curr_key_node, is_node)

    def _normalize_pair(self, key, value, value_is_node):
        '''if value is also a key-value node, merge its key to key
        '''
        if not value_is_node:
            return key, value, value_is_node
        (value_node_type, value_content) = self._inspect_node(value)
        if is_key_value_type(value_node_type):
            key.extend(value_content[0])
            return (key, value_content[1],
                    value_node_type == NODE_TYPE_INNER_KEY_VALUE)
        return key, value, value_is_node

    def _normalize_node(self, node, is_node):
        '''
        :return: (normalized_node, is_node)
        '''
        if not is_node:
            return node, is_node

        (node_type, content) = self._inspect_node(node)

        # for NODE_TYPE_LEAF_KEY_VALUE, no need to normalize

        if node_type == NODE_TYPE_INNER_KEY_VALUE:
            key, value, value_is_node = self._normalize_pair(
                content[0][:], content[1], True)
            if not key:
                return value, value_is_node
            if key == content[0]:
                return node, is_node
            return self._update(BLANK_NODE, True, key, value, value_is_node)

        if is_diverge_type(node_type):
            not_blank_slots_count = sum(1 for x in range(17) if content[x])

            if not not_blank_slots_count:
                return BLANK_NODE, True

            if not_blank_slots_count > 1:
                return node, True

            # only one slot/value is not blank

            # convert to a key value node
            if content[-1]:
                return self._update(BLANK_NODE, True, [], content[-1], False)

            index = [i for i, item in enumerate(content) if item][0]

            return self._update(
                [], True, [index], content[index], value_is_node=True)

        return node, True

    def _merge_two_pairs(self,
                         key1, value1, value1_is_node,
                         key2, value2, value2_is_node):
        '''
        merge (key2, value2) to (key1, value1)
        key1 and key2 has no common prefix
        '''
        key1, value1, value1_is_node = self._normalize_pair(
            key1, value1, value1_is_node)

        key2, value2, value2_is_node = self._normalize_pair(
            key2, value2, value2_is_node)

        diverge_node = [BLANK_NODE] * 17

        if not key1:
            diverge_node[-1] = value1
        else:
            diverge_node[key1[0]] = self._update(
                [], True, key1[1:], value1, value1_is_node)[0]
        if not key2:
            diverge_node[-1] = value2
        else:
            diverge_node[key2[0]] = self._update(
                [], True, key2[1:], value2, value2_is_node)[0]

        return self._normalize_node(
            self._rlp_encode(diverge_node), True)

    def delete(self, key):
        '''
        :param key: a string with length of [0, 32]
        '''
        if not isinstance(key, (str, unicode)):
            raise Exception("Key must be strings")

        if len(key) > 32:
            raise Exception("Max key length is 32")

        ''' .. note:: value_is_node should be true, or the key will be updated
        with a blank value
        '''
        self.root, _ = self._update(
            self.root,
            True,
            bin_to_nibbles(str(key)),
            BLANK_NODE,
            value_is_node=True)
        self.db.commit()
        return self._rlp_decode(self.root)

    def _get_size(self, node, is_node):
        '''Get counts of (key, value) stored in this and the descendant nodes

        :param node: node or hash
        :is_node: true if node is not a value, other wise false
        '''
        if not is_node:
            return 1

        (node_type, content) = self._inspect_node(node)
        if node_type == NODE_TYPE_BLANK:
            return 0
        elif is_key_value_type(node_type):
            value_is_node = node_type == NODE_TYPE_INNER_KEY_VALUE
            return self._get_size(content[1], value_is_node)
        elif is_diverge_type(node_type):
            return sum(self._get_size(content[x], True) for x in range(16)) \
                + (1 if content[-1] else 0)

    def _to_dict(self, node, is_node):
        '''convert (key, value) stored in this and the descendant nodes
        to dict items.

        :param node: node or hash
        :is_node: true if node is not a value, other wise false

        .. note::

            Here key is in full form, rather than key of the individual node
        '''
        if not is_node:
            return {'': self._rlp_decode(node)}

        (node_type, content) = self._inspect_node(node)

        if node_type == NODE_TYPE_BLANK:
            return {}

        elif is_key_value_type(node_type):
            key = '+'.join([str(x) for x in content[0]])
            value_is_node = node_type == NODE_TYPE_INNER_KEY_VALUE
            sub_dict = self._to_dict(content[1], value_is_node)

            # prepend key of this node to the keys of children
            res = {}
            for sub_key, sub_value in sub_dict.iteritems():
                full_key = '{0}+{1}'.format(key, sub_key) if sub_key else key
                res[full_key] = sub_value
            return res

        elif is_diverge_type(node_type):
            res = {}
            for i in range(16):
                sub_dict = self._to_dict(content[i], True)

                for sub_key, sub_value in sub_dict.iteritems():
                    full_key = '{0}+{1}'.format(i, sub_key) if sub_key else i
                    res[full_key] = sub_value

            if content[-1]:
                res[str(NIBBLE_TERMINATOR)] = self._rlp_decode(content[-1])
            return res

    def to_dict(self, as_hex=False):
        d = self._to_dict(self.root, True)
        res = {}
        for key_str, value in d.iteritems():
            nibbles = [int(x) for x in key_str.split('+')]
            key = nibbles_to_bin(without_terminator(nibbles))
            res[key] = value
        return res

    def get(self, key):
        rlp_value, _ = self._get(self.root, True, bin_to_nibbles(str(key)))
        return self._rlp_decode(rlp_value) if rlp_value is not None else None

    def get_size(self):
        return self._get_size(self.root, True)

    def update(self, key, value):
        '''
        :param key: a string with length of [0, 32]
        :value: a string or list
        '''
        if not isinstance(key, (str, unicode)):
            raise Exception("Key must be strings")

        if len(key) > 32:
            raise Exception("Max key length is 32")

        self.root, _ = self._update(
            self.root,
            True,
            bin_to_nibbles(str(key)),
            self._rlp_encode(value),
            value_is_node=False)
        self.db.commit()
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
