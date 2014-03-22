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

    def __init__(self, dbfile, root='', debug=False):
        self.root = root
        self.debug = debug
        dbfile = os.path.abspath(dbfile)
        if dbfile not in databases:
            databases[dbfile] = DB(dbfile)
        self.db = databases[dbfile]

    def __get_state(self, node, key):
        if self.debug:
            print('nk', encode_node(node), key)
        if len(key) == 0 or not node:
            return node
        curnode = self.lookup(node)
        if self.debug:
            print ('cn', curnode)
        if not curnode:
            raise Exception("node not found in database")
        elif len(curnode) == 2:
            (k2, v2) = curnode
            k2 = bin_to_hexarraykey(k2)
            if len(key) >= len(k2) and k2 == key[:len(k2)]:
                return self.__get_state(v2, key[len(k2):])
            else:
                return ''
        elif len(curnode) == 17:
            return self.__get_state(curnode[key[0]], key[1:])

    def __put(self, node, root=False):
        rlpnode = rlp.encode(node)
        if len(rlpnode) >= 32:
            h = sha3(rlpnode)
            self.db.put(h, rlpnode)
        else:
            h = rlpnode if root else node
        return h

    def lookup(self, node):
        if not isinstance(node, (str, unicode)):
            return node
        elif len(node) == 0:
            return node
        elif len(node) < 32:
            return rlp.decode(node)
        else:
            return rlp.decode(self.db.get(node))

    def __update_state(self, node, key, value):
        if value != '':
            return self.__insert_state(node, key, value)
        else:
            return self.__delete_state(node, key)

    def __insert_state(self, node, key, value):
        if self.debug:
            print 'ins', encode_node(node), key

        if len(key) == 0:
            return value

        # create a new node if node not exists
        if not node:
            newnode = [hexarraykey_to_bin(key), value]
            return self.__put(newnode)

        # find the node
        curnode = self.lookup(node)
        if self.debug:
            print ('icn', curnode)
        if not curnode:
            raise Exception("node not found in database")

        # node is a 17 items sequence
        if len(curnode) == 17:
            newnode = [curnode[i] for i in range(17)]
            newnode[key[0]] = self.__insert_state(
                curnode[key[0]], key[1:], value)
            return self.__put(newnode)

        # node is a (key, value) pair
        (k2, v2) = curnode
        k2 = bin_to_hexarraykey(k2)

        # key already exists
        if key == k2:
            newnode = [hexarraykey_to_bin(key), value]
            return self.__put(newnode)

        # find max long common prefix
        i = 0
        while key[:i + 1] == k2[:i + 1] and i < len(k2):
            i += 1

        if i == len(k2):
            newhash3 = self.__insert_state(v2, key[i:], value)
        else:
            newnode1 = self.__insert_state('', key[i + 1:], value)
            newnode2 = self.__insert_state('', k2[i + 1:], v2)
            newnode3 = [''] * 17
            newnode3[key[i]] = newnode1
            newnode3[k2[i]] = newnode2
            newhash3 = self.__put(newnode3)

        if i == 0:
            return newhash3
        else:
            newnode4 = [hexarraykey_to_bin(key[:i]), newhash3]
            return self.__put(newnode4)


    def __delete_state(self, node, key):
        if self.debug:
            print 'dnk', encode_node(node), key
        if len(key) == 0 or not node:
            return ''

        curnode = self.lookup(node)
        if not curnode:
            raise Exception("node not found in database")
        if self.debug:
            print ('dcn', curnode)

        if len(curnode) == 2:
            (k2, v2) = curnode
            k2 = bin_to_hexarraykey(k2)
            if key == k2:
                return ''
            elif key[:len(k2)] == k2:
                newhash = self.__delete_state(v2, key[len(k2):])
                childnode = self.lookup(newhash)
                if len(childnode) == 2:
                    newkey = k2 + bin_to_hexarraykey(childnode[0])
                    newnode = [hexarraykey_to_bin(newkey), childnode[1]]
                else:
                    newnode = [curnode[0], newhash]
                return self.__put(newnode)
            else:
                return node

        newnode = [curnode[i] for i in range(17)]
        newnode[key[0]] = self.__delete_state(newnode[key[0]], key[1:])
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
            childnode = self.lookup(newnode[onlynode])
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
        return self.__put(newnode2)

    def __get_size(self, node):
        '''Get counts of (key, value) stored in this and the descendant nodes
        '''
        if not node:
            return 0
        curnode = self.lookup(node)
        if not curnode:
            raise Exception("node not found in database")
        if len(curnode) == 2:
            key = hexarraykey_to_bin(curnode[0])
            if key[-1] == 16:
                return 1
            else:
                return self.__get_size(curnode[1])
        elif len(curnode) == 17:
            total = 0
            for i in range(16):
                total += self.__get_size(curnode[i])
            if curnode[16]:
                total += 1
            return total

    def __to_dict(self, node):
        '''convert (key, value) stored in this and the descendant nodes
        to dict items.

        Here key is in full form, rather than key of the individual node
        '''
        if not node:
            return {}
        curnode = self.lookup(node)
        if not curnode:
            raise Exception("node not found in database")
        if len(curnode) == 2:
            lkey = bin_to_hexarraykey(curnode[0])
            o = {}
            if lkey[-1] == 16:
                o[curnode[0]] = curnode[1]
            else:
                d = self.__to_dict(curnode[1])
                for v in d:
                    subkey = bin_to_hexarraykey(v)
                    totalkey = hexarraykey_to_bin(lkey + subkey)
                    o[totalkey] = d[v]
            return o
        elif len(curnode) == 17:
            o = {}
            for i in range(16):
                d = self.__to_dict(curnode[i])
                for v in d:
                    subkey = bin_to_hexarraykey(v)
                    totalkey = hexarraykey_to_bin([i] + subkey)
                    o[totalkey] = d[v]
            if curnode[16]:
                o[chr(16)] = curnode[16]
            return o
        else:
            raise Exception("bad curnode! " + curnode)

    def to_dict(self, as_hex=False):
        d = self.__to_dict(self.root)
        o = {}
        for v in d:
            v2 = ''.join(['0123456789abcdef'[x]
                         for x in bin_to_hexarraykey(v)[:-1]])
            if not as_hex:
                v2 = v2.decode('hex')
            o[v2] = d[v]
        return o

    def get(self, key):
        return self.__get_state(
            self.root, bin_to_nibble_list_with_terminator(str(key)))

    def get_size(self):
        return self.__get_size(self.root)

    def update(self, key, value):
        if not isinstance(key, (str, unicode)) or\
                not isinstance(value, (str, unicode)):
            raise Exception("Key and value must be strings")
        self.root = self.__update_state(
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
