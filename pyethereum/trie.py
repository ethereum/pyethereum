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
        try:
            return self.db.Get(key)
        except KeyError:
            return ''

    def put(self, key, value):
        return self.db.Put(key, value)

    def delete(self, key):
        return self.db.Delete(key)


def hexarraykey_to_bin(key):
    """convert key given as list of nibbles to binary"""
    if key[-1:] == [16]:
        flags = 2
        key = key[:-1]
    else:
        flags = 0

    oddlen = len(key) % 2
    flags |= oddlen   # set lowest bit if odd number of nibbles
    if oddlen:
        key = [flags] + key
    else:
        key = [flags, 0] + key
    o = ''
    for i in range(0, len(key), 2):
        o += chr(16 * key[i] + key[i + 1])
    return o


def bin_to_nibble_list(s):
    """convert string s to a list of nibbles (half-bytes)

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


def bin_to_nibble_list_with_terminator(s):
    """same as bin_to_nibble_list, but adds a terminator value at the end"""
    res = bin_to_nibble_list(s)
    res.append(16)
    return res


def bin_to_hexarraykey(bindata):
    o = bin_to_nibble_list(bindata)
    flags = o[0]
    if flags & 2:
        o.append(16)
    if flags & 1 == 1:
        o = o[1:]
    else:
        o = o[2:]
    return o


def encode_node(nd):
    if isinstance(nd, str):
        return nd.encode('hex')
    else:
        return rlp.encode(nd).encode('hex')


class Trie(object):
    databases = {}

    def __init__(self, dbfile, root=''):
        self.root = root
        dbfile = os.path.abspath(dbfile)
        if dbfile not in self.databases:
            self.databases[dbfile] = DB(dbfile)
        self.db = self.databases[dbfile]

    def clear(self):
        self.root = ''

    def _get(self, node, key):
        """ get value inside a node
        """

        # leaf node, note the two cases
        if len(key) == 0 or not node:
            return node

        curr_node = self._rlp_decode(node)
        if not curr_node:
            raise Exception("node not found in database")

        if len(curr_node) == 2:
            (curr_key, curr_val) = curr_node
            curr_key = bin_to_hexarraykey(curr_key)
            if len(key) >= len(curr_key) and curr_key == key[:len(curr_key)]:
                return self._get(curr_val, key[len(curr_key):])
            else:
                return ''
        elif len(curr_node) == 17:
            return self._get(curr_node[key[0]], key[1:])

    def _rlp_encode(self, node, root=False):
        rlpnode = rlp.encode(node)
        if len(rlpnode) >= 32:
            res = sha3(rlpnode)
            self.db.put(res, rlpnode)
        else:
            res = rlpnode if root else node
        return res

    def _rlp_decode(self, node):
        if not isinstance(node, (str, unicode)):
            return node
        elif len(node) == 0:
            return node
        elif len(node) < 32:
            return rlp.decode(node)
        else:
            return rlp.decode(self.db.get(node))

    def _update_or_delete(self, node, key, value):
        """ update item inside a node
        """
        if value != '':
            return self._update(node, key, value)
        else:
            return self.delete(node, key)

    def _update(self, node, key, value):
        """ update item inside a node

        return the updated node with rlp encoded
        """

        if len(key) == 0:
            return value

        # leaf node
        if not node:
            newnode = [hexarraykey_to_bin(key), value]
            return self._rlp_encode(newnode)

        # decode the node
        curr_node = self._rlp_decode(node)
        if not curr_node:
            raise Exception("node not found in database")

        # node is a 17 items sequence
        if len(curr_node) == 17:
            items = [curr_node[i] for i in range(17)]
            items[key[0]] = self._update(
                curr_node[key[0]], key[1:], value)
            return self._rlp_encode(items)

        # node is (key, value)
        return self._update_kv_node(curr_node, key, value)

    def _update_kv_node(self, kv_node, key, value):
        '''when the current node is a (key, value) node

        kv_node is an already rlp decoded (key, value) tupple
        '''
        # node is a (key, value) pair
        (curr_key, curr_val) = kv_node
        curr_key = bin_to_hexarraykey(curr_key)

        # already leaf node
        if key == curr_key:
            return self._rlp_encode(
                [hexarraykey_to_bin(key), value])

        # find common prefix
        next_key_index = len(curr_key)
        for i in range(len(curr_key)):
            if key[i] != curr_key[i]:
                next_key_index = i
                break

        # key starts with curr_key
        if next_key_index == len(curr_key):
            curr_value = self._rlp_encode(
                self._update(curr_val, key[len(curr_key):], value))
            return self._rlp_encode(
                [hexarraykey_to_bin(curr_key), curr_val])

        # convert the node to a 17 items one
        curr_node = [''] * 17
        key_derived_value = self._update('', key[next_key_index + 1:], value)
        curr_key_derived_value = self._update('', curr_key[next_key_index + 1:],
                                               curr_val)
        curr_node[key[next_key_index]] = key_derived_value
        curr_node[curr_key[next_key_index]] = curr_key_derived_value
        curr_node_encoded = self._rlp_encode(curr_node)

        if next_key_index == 0:
            # no common prefix
            return curr_node_encoded
        else:
            # create a new node with common prefix as key
            new_node = [hexarraykey_to_bin(key[:next_key_index]),
                        curr_node_encoded]
            return self._rlp_encode(new_node)

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
            curr_key = bin_to_hexarraykey(curr_key)
            if key == curr_key:
                return ''
            elif key[:len(curr_key)] == curr_key:
                newhash = self.delete(curr_val, key[len(curr_key):])
                childnode = self._rlp_decode(newhash)
                if len(childnode) == 2:
                    newkey = curr_key + bin_to_hexarraykey(childnode[0])
                    newnode = [hexarraykey_to_bin(newkey), childnode[1]]
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
        if onlynode == 16:
            newnode2 = [hexarraykey_to_bin([16]), newnode[onlynode]]
        elif onlynode >= 0:
            childnode = self._rlp_decode(newnode[onlynode])
            if not childnode:
                raise Exception("?????")
            if len(childnode) == 17:
                newnode2 = [
                    hexarraykey_to_bin([onlynode]), newnode[onlynode]]
            elif len(childnode) == 2:
                newkey = [onlynode] + bin_to_hexarraykey(childnode[0])
                newnode2 = [hexarraykey_to_bin(newkey), childnode[1]]
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
            key = hexarraykey_to_bin(curr_node[0])
            if key[-1] == 16:
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
            lkey = bin_to_hexarraykey(curr_node[0])
            o = {}
            if lkey[-1] == 16:
                o[curr_node[0]] = curr_node[1]
            else:
                d = self._to_dict(curr_node[1])
                for v in d:
                    subkey = bin_to_hexarraykey(v)
                    totalkey = hexarraykey_to_bin(lkey + subkey)
                    o[totalkey] = d[v]
            return o
        elif len(curr_node) == 17:
            o = {}
            for i in range(16):
                d = self._to_dict(curr_node[i])
                for v in d:
                    subkey = bin_to_hexarraykey(v)
                    totalkey = hexarraykey_to_bin([i] + subkey)
                    o[totalkey] = d[v]
            if curr_node[16]:
                o[chr(16)] = curr_node[16]
            return o
        else:
            raise Exception("bad curr_node! " + curr_node)

    def to_dict(self, as_hex=False):
        d = self._to_dict(self.root)
        o = {}
        for v in d:
            curr_val = ''.join(['0123456789abcdef'[x]
                         for x in bin_to_hexarraykey(v)[:-1]])
            if not as_hex:
                curr_val = curr_val.decode('hex')
            o[curr_val] = d[v]
        return o

    def get(self, key):
        return self._get(
            self.root, bin_to_nibble_list_with_terminator(str(key)))

    def get_size(self):
        return self._get_size(self.root)

    def update(self, key, value):
        if not isinstance(key, (str, unicode)) or\
                not isinstance(value, (str, unicode)):
            raise Exception("Key and value must be strings")
        if not key:
            raise Exception("Key should not be blank")
        self.root = self._update_or_delete(
            self.root, bin_to_nibble_list_with_terminator(str(key)), str(value))

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2:
        if sys.argv[1] == 'insert':
            t = Trie(sys.argv[2], sys.argv[3].decode('hex'))
            t.update(sys.argv[4], sys.argv[5])
            print encode_node(t.root)
        elif sys.argv[1] == 'get':
            t = Trie(sys.argv[2], sys.argv[3].decode('hex'))
            print t.get(sys.argv[4])
