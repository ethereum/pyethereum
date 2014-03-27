#!/usr/bin/python

import os
import leveldb
import rlp
from sha3 import sha3_256


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


def bin_to_nibbles(s):
    """convert string s to nibbles (half-bytes)

    >>> bin_to_nibble_list("")
    []
    >>> bin_to_nibble_list("h")
    [6, 8]
    >>> bin_to_nibble_list("he")
    [6, 8, 6, 5]
    >>> bin_to_nibble_list("hello")
    [6, 8, 6, 5, 6, 12, 6, 12, 6, 15]
    """
    res = []
    for x in s:
        res += divmod(ord(x), 16)
    return res


NIBBLE_TERMINATOR = 16


def append_terminator(nibbles):
    nibbles.append(NIBBLE_TERMINATOR)


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


(
    NODE_TYPE_BLANK,
    NODE_TYPE_VALUE,
    NODE_TYPE_KEY_VALUE,
    NODE_TYPE_DIVERGE
) = tuple(range(4))

BLANK_NODE = ''


def starts_with(full, part):
    ''' test whether the items in the part is
    the leading items of the full
    '''
    if len(full) < len(part):
        return False
    return full[:len(part)] == part


class Trie(object):
    databases = {}

    def __init__(self, dbfile, root=BLANK_NODE):
        '''
        :param dbfile: key value database
        :root: blank or rlp encoded trie tree
        '''
        self.root = root
        dbfile = os.path.abspath(dbfile)
        if dbfile not in self.databases:
            self.databases[dbfile] = DB(dbfile)
        self.db = self.databases[dbfile]

    def clear(self):
        self.root = BLANK_NODE

    def _inspect_node(self, node):
        ''' inspect node to get node type and content

        :param node: blank or rlp encoded node
        :return: (node_type, content),
        '''
        assert isinstance(node, str)

        if not node:
            return (NODE_TYPE_BLANK, BLANK_NODE)

        content = self._rlp_decode(node)
        if isinstance(content, str):
            node_type = NODE_TYPE_VALUE
            content = node
        elif len(content) == 2:
            node_type = NODE_TYPE_KEY_VALUE
        elif len(content) == 17:
            node_type = NODE_TYPE_DIVERGE
        else:
            raise Exception('node decode error')
        return (node_type, content)

    def _get(self, node, key):
        """ get value inside a node

        :param node: rlp encoded node
        :param key: nibble list without terminator
        :return: None if does not exist, or the rlp encoded value for the key
        """
        node_type, node = self._inspect_node(node)

        if node_type == NODE_TYPE_BLANK:
            return None

        if node_type == NODE_TYPE_VALUE:
            # if key still has nibbles
            return None if key else node

        if node_type == NODE_TYPE_DIVERGE:
            # already reach the expected node
            if not key:
                return node[-1]
            return self._get(node[key[0]], key[1:])

        elif node_type == NODE_TYPE_KEY_VALUE:
            (curr_key, curr_val) = node
            curr_key = unpack_to_nibbles(curr_key)

            # already reach the expected node
            if curr_key[-1] == NIBBLE_TERMINATOR:
                # found
                if key == curr_key[:-1]:
                    return curr_val
                # not found
                else:
                    return None

            # traverse child nodes
            if starts_with(key, curr_key):
                return self._get(curr_val, key[len(curr_key):])
            else:
                return None

    def _rlp_encode(self, node):
        rlpnode = rlp.encode(node)
        if len(rlpnode) < 32:
            return rlpnode

        hashkey = sha3(rlpnode)
        self.db.put(hashkey, rlpnode)
        return hashkey

    def _rlp_decode(self, node):
        if not isinstance(node, (str, unicode)):
            return node
        elif len(node) == 0:
            return node
        elif len(node) < 32:
            return rlp.decode(node)
        else:
            return rlp.decode(self.db.get(node))

    def _update(self, node, key, value):
        """ update item inside a node

        :param node: is a rlp encoded binary array
        :param key: nibble list without terminator
        :param value: nlp encoded value
        :return: the updated node with rlp encoded
        """
        # decode the node
        (node_type, node) = self._inspect_node(node)

        if node_type == NODE_TYPE_BLANK:
            if not key:
                return value
            else:
                # a new key value node
                value_node_type, _ = self._inspect_node(value)
                if value_node_type == NODE_TYPE_VALUE:
                    append_terminator(key)
                return self._rlp_encode([pack_nibbles(key), value])

        elif node_type == NODE_TYPE_VALUE:
            if not key:
                return value
            else:
                # a new diverge node
                new_node = [''] * 17
                new_node[-1] = node
                return self._update(self._rlp_encode(new_node), key, value)

        elif node_type == NODE_TYPE_DIVERGE:
            # already the expected node
            if not key:
                node[-1] = value
                return self._rlp_encode(node)

            slot_type, slot = self._inspect_node(node[key[0]])
            node[key[0]] = self._update(node[key[0]], key[1:], value)
            return self._update(BLANK_NODE, None, self._rlp_encode(node))

        elif node_type == NODE_TYPE_KEY_VALUE:
            return self._update_kv_node(node, key, value)

    def _update_kv_node(self, node, key, value):
        '''when the current node is a (key, value) node

        :param node: an already rlp decoded (key, value) tuple
        :param key: nibble list without terminator, must not be blank
        :param value: nlp encoded value
        :return: the updated node with rlp encoded
        '''
        (curr_key_bin, curr_val) = node
        curr_key = unpack_to_nibbles(curr_key_bin)

        # remove the terminator
        if curr_key[-1] == NIBBLE_TERMINATOR:
            curr_key = curr_key[:-1]

        # find longest common prefix
        prefix_length = 0
        for i in range(min(len(curr_key), len(key))):
            if key[i] != curr_key[i]:
                break
            prefix_length = i + 1

        # merge
        if not prefix_length:
            # a new diverge node
            rlp_diverge_node = self._rlp_encode([''] * 17)
            rlp_diverge_node = self._update(
                rlp_diverge_node, curr_key, curr_val)
            rlp_diverge_node = self._update(
                rlp_diverge_node, key, value)
            return rlp_diverge_node

        # create node for key postfix
        post_curr_key_node = self._update(
            BLANK_NODE, curr_key[prefix_length:], curr_val)
        post_curr_key_node = self._update(
            post_curr_key_node, key[prefix_length:], value)

        # create node for key prefix
        pre_curr_key_node = self._update(
            BLANK_NODE, curr_key[:prefix_length], post_curr_key_node)

        return pre_curr_key_node

    def delete(self, node, key):
        """ delete item inside a node

        todo: delete corresponding value from database
        """
        if len(key) == 0 or not node:
            return ''

        curr_node = self._rlp_decode(node)
        if not curr_node:
            raise Exception("node not found in database")

        if len(curr_node) == 2:
            (curr_key, curr_val) = curr_node
            curr_key = unpack_to_nibbles(curr_key)
            if key == curr_key:
                return ''
            elif key[:len(curr_key)] == curr_key:
                newhash = self.delete(curr_val, key[len(curr_key):])
                childnode = self._rlp_decode(newhash)
                if len(childnode) == 2:
                    newkey = curr_key + unpack_to_nibbles(childnode[0])
                    newnode = [pack_nibbles(newkey), childnode[1]]
                else:
                    newnode = [curr_node[0], newhash]
                return self._rlp_encode(newnode)
            else:
                return node

        newnode = [curr_node[i] for i in range(17)]
        newnode[key[0]] = self.delete(newnode[key[0]], key[1:])
        onlynode = -1
        for i in range(17):
            if newnode[i]:
                if onlynode == -1:
                    onlynode = i
                else:
                    onlynode = -2
        if onlynode == NIBBLE_TERMINATOR:
            newnode2 = [pack_nibbles([NIBBLE_TERMINATOR]), newnode[onlynode]]
        elif onlynode >= 0:
            childnode = self._rlp_decode(newnode[onlynode])
            if not childnode:
                raise Exception("?????")
            if len(childnode) == 17:
                newnode2 = [
                    pack_nibbles([onlynode]), newnode[onlynode]]
            elif len(childnode) == 2:
                newkey = [onlynode] + unpack_to_nibbles(childnode[0])
                newnode2 = [pack_nibbles(newkey), childnode[1]]
        else:
            newnode2 = newnode
        return self._rlp_encode(newnode2)

    def _get_size(self, node):
        '''Get counts of (key, value) stored in this and the descendant nodes
        '''
        if not node:
            return 0
        curr_node = self._rlp_decode(node)
        if not curr_node:
            raise Exception("node not found in database")
        if len(curr_node) == 2:
            key = pack_nibbles(curr_node[0])
            if key[-1] == NIBBLE_TERMINATOR:
                return 1
            else:
                return self._get_size(curr_node[1])
        elif len(curr_node) == 17:
            total = 0
            for i in range(16):
                total += self._get_size(curr_node[i])
            if curr_node[16]:
                total += 1
            return total

    def _to_dict(self, node):
        '''convert (key, value) stored in this and the descendant nodes
        to dict items.

        Here key is in full form, rather than key of the individual node
        '''
        if not node:
            return {}
        curr_node = self._rlp_decode(node)
        if not curr_node:
            raise Exception("node not found in database")
        if len(curr_node) == 2:
            lkey = unpack_to_nibbles(curr_node[0])
            o = {}
            if lkey[-1] == NIBBLE_TERMINATOR:
                o[curr_node[0]] = curr_node[1]
            else:
                d = self._to_dict(curr_node[1])
                for v in d:
                    subkey = unpack_to_nibbles(v)
                    totalkey = pack_nibbles(lkey + subkey)
                    o[totalkey] = d[v]
            return o
        elif len(curr_node) == 17:
            o = {}
            for i in range(16):
                d = self._to_dict(curr_node[i])
                for v in d:
                    subkey = unpack_to_nibbles(v)
                    totalkey = pack_nibbles([i] + subkey)
                    o[totalkey] = d[v]
            if curr_node[16]:
                o[chr(NIBBLE_TERMINATOR)] = curr_node[16]
            return o
        else:
            raise Exception("bad curr_node! " + curr_node)

    def to_dict(self, as_hex=False):
        d = self._to_dict(self.root)
        o = {}
        for v in d:
            curr_val = ''.join(['0123456789abcdef'[x]
                                for x in unpack_to_nibbles(v)[:-1]])
            if not as_hex:
                curr_val = curr_val.decode('hex')
            o[curr_val] = d[v]
        return o

    def get(self, key):
        rlp_value = self._get(self.root, bin_to_nibbles(str(key)))
        return None if not rlp_value else self._rlp_decode(rlp_value)

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

        key = bin_to_nibbles(str(key))

        self.root = self._update(self.root, key, self._rlp_encode(str(value)))
        return self.root

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
