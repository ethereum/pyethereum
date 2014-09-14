#!/usr/bin/env python

import os
import rlp
import utils
import db

DB = db.DB


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
RECORDING = 1
NONE = 0
VERIFYING = -1


class InvalidSPVProof(Exception):
    pass


def with_terminator(nibbles):
    nibbles = nibbles[:]
    if not nibbles or nibbles[-1] != NIBBLE_TERMINATOR:
        nibbles.append(NIBBLE_TERMINATOR)
    return nibbles


def without_terminator(nibbles):
    nibbles = nibbles[:]
    if nibbles and nibbles[-1] == NIBBLE_TERMINATOR:
        del nibbles[-1]
    return nibbles


def adapt_terminator(nibbles, has_terminator):
    if has_terminator:
        return with_terminator(nibbles)
    else:
        return without_terminator(nibbles)


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
    NODE_TYPE_LEAF,
    NODE_TYPE_EXTENSION,
    NODE_TYPE_BRANCH
) = tuple(range(4))


def is_key_value_type(node_type):
    return node_type in [NODE_TYPE_LEAF,
                         NODE_TYPE_EXTENSION]

BLANK_NODE = ''
BLANK_ROOT = ''


class Trie(object):
    proof_mode = 0

    def __init__(self, dbfile, root_hash=BLANK_ROOT):
        '''it also present a dictionary like interface

        :param dbfile: key value database
        :root: blank or trie node in form of [key, value] or [v0,v1..v15,v]
        '''
        if isinstance(dbfile, str):
            dbfile = os.path.abspath(dbfile)
            self.db = DB(dbfile)
        else:
            self.db = dbfile  # Pass in a database object directly
        self.set_root_hash(root_hash)
        self.proof_mode = 0
        self.proof_nodes = []

    # For SPV proof production/verification purposes
    def spv_check(self, node):
        if not self.proof_mode:
            pass
        elif self.proof_mode == RECORDING:
            self.proof_nodes.append(node)
        elif self.proof_mode == VERIFYING:
            if node not in self.proof_nodes:
                raise InvalidSPVProof("Proof invalid!")

    @property
    def root_hash(self):
        '''always empty or a 32 bytes string
        '''
        return self.get_root_hash()

    def get_root_hash(self):
        if self.root_node == BLANK_NODE:
            return BLANK_ROOT
        assert isinstance(self.root_node, list)
        val = rlp.encode(self.root_node)
        key = utils.sha3(val)
        self.db.put(key, val)
        self.spv_check(self.root_node)
        return key

    @root_hash.setter
    def root_hash(self, value):
        self.set_root_hash(value)

    def set_root_hash(self, root_hash):
        if root_hash == BLANK_ROOT:
            self.root_node = BLANK_NODE
            return
        assert isinstance(root_hash, (str, unicode))
        assert len(root_hash) in [0, 32]
        self.root_node = self._decode_to_node(root_hash)

    def clear(self):
        ''' clear all tree data
        '''
        self._delete_child_storage(self.root_node)
        self._delete_node_storage(self.root_node)
        self.root_node = BLANK_NODE

    def _delete_child_storage(self, node):
        node_type = self._get_node_type(node)
        if node_type == NODE_TYPE_BRANCH:
            for item in node[:16]:
                self._delete_child_storage(self._decode_to_node(item))
        elif is_key_value_type(node_type):
            node_type = self._get_node_type(node)
            if node_type == NODE_TYPE_EXTENSION:
                self._delete_child_storage(self._decode_to_node(node[1]))

    def _encode_node(self, node):
        if node == BLANK_NODE:
            return BLANK_NODE
        assert isinstance(node, list)
        rlpnode = rlp.encode(node)
        if len(rlpnode) < 32:
            return node

        hashkey = utils.sha3(rlpnode)
        self.db.put(hashkey, rlpnode)
        self.spv_check(node)
        return hashkey

    def _decode_to_node(self, encoded):
        if encoded == BLANK_NODE:
            return BLANK_NODE
        if isinstance(encoded, list):
            return encoded
        o = rlp.decode(self.db.get(encoded))
        self.spv_check(o)
        return o

    def _get_node_type(self, node):
        ''' get node type and content

        :param node: node in form of list, or BLANK_NODE
        :return: node type
        '''
        if node == BLANK_NODE:
            return NODE_TYPE_BLANK

        if len(node) == 2:
            nibbles = unpack_to_nibbles(node[0])
            has_terminator = (nibbles and nibbles[-1] == NIBBLE_TERMINATOR)
            return NODE_TYPE_LEAF if has_terminator\
                else NODE_TYPE_EXTENSION
        if len(node) == 17:
            return NODE_TYPE_BRANCH

    def _get(self, node, key):
        """ get value inside a node

        :param node: node in form of list, or BLANK_NODE
        :param key: nibble list without terminator
        :return:
            BLANK_NODE if does not exist, otherwise value or hash
        """
        node_type = self._get_node_type(node)
        if node_type == NODE_TYPE_BLANK:
            return BLANK_NODE

        if node_type == NODE_TYPE_BRANCH:
            # already reach the expected node
            if not key:
                return node[-1]
            sub_node = self._decode_to_node(node[key[0]])
            return self._get(sub_node, key[1:])

        # key value node
        curr_key = without_terminator(unpack_to_nibbles(node[0]))
        if node_type == NODE_TYPE_LEAF:
            return node[1] if key == curr_key else BLANK_NODE

        if node_type == NODE_TYPE_EXTENSION:
            # traverse child nodes
            if starts_with(key, curr_key):
                sub_node = self._decode_to_node(node[1])
                return self._get(sub_node, key[len(curr_key):])
            else:
                return BLANK_NODE

    def _update(self, node, key, value):
        """ update item inside a node

        :param node: node in form of list, or BLANK_NODE
        :param key: nibble list without terminator
            .. note:: key may be []
        :param value: value string
        :return: new node

        if this node is changed to a new node, it's parent will take the
        responsibility to *store* the new node storage, and delete the old
        node storage
        """
        node_type = self._get_node_type(node)

        if node_type == NODE_TYPE_BLANK:
            return [pack_nibbles(with_terminator(key)), value]

        elif node_type == NODE_TYPE_BRANCH:
            if not key:
                node[-1] = value
            else:
                new_node = self._update_and_delete_storage(
                    self._decode_to_node(node[key[0]]),
                    key[1:], value)
                node[key[0]] = self._encode_node(new_node)
            return node

        elif is_key_value_type(node_type):
            return self._update_kv_node(node, key, value)

    def _update_and_delete_storage(self, node, key, value):
        old_node = node[:]
        new_node = self._update(node, key, value)
        if old_node != new_node:
            self._delete_node_storage(old_node)
        return new_node

    def _update_kv_node(self, node, key, value):
        node_type = self._get_node_type(node)
        curr_key = without_terminator(unpack_to_nibbles(node[0]))
        is_inner = node_type == NODE_TYPE_EXTENSION

        # find longest common prefix
        prefix_length = 0
        for i in range(min(len(curr_key), len(key))):
            if key[i] != curr_key[i]:
                break
            prefix_length = i + 1

        remain_key = key[prefix_length:]
        remain_curr_key = curr_key[prefix_length:]

        if remain_key == [] == remain_curr_key:
            if not is_inner:
                return [node[0], value]
            new_node = self._update_and_delete_storage(
                self._decode_to_node(node[1]), remain_key, value)

        elif remain_curr_key == []:
            if is_inner:
                new_node = self._update_and_delete_storage(
                    self._decode_to_node(node[1]), remain_key, value)
            else:
                new_node = [BLANK_NODE] * 17
                new_node[-1] = node[1]
                new_node[remain_key[0]] = self._encode_node([
                    pack_nibbles(with_terminator(remain_key[1:])),
                    value
                ])
        else:
            new_node = [BLANK_NODE] * 17
            if len(remain_curr_key) == 1 and is_inner:
                new_node[remain_curr_key[0]] = node[1]
            else:
                new_node[remain_curr_key[0]] = self._encode_node([
                    pack_nibbles(
                        adapt_terminator(remain_curr_key[1:], not is_inner)
                    ),
                    node[1]
                ])

            if remain_key == []:
                new_node[-1] = value
            else:
                new_node[remain_key[0]] = self._encode_node([
                    pack_nibbles(with_terminator(remain_key[1:])), value
                ])

        if prefix_length:
            # create node for key prefix
            return [pack_nibbles(curr_key[:prefix_length]),
                    self._encode_node(new_node)]
        else:
            return new_node

    def _getany(self, node, reverse=False, path=[]):
        node_type = self._get_node_type(node)
        if node_type == NODE_TYPE_BLANK:
            return None
        if node_type == NODE_TYPE_BRANCH:
            if node[16]:
                return [16]
            scan_range = range(16)
            if reverse:
                scan_range.reverse()
            for i in scan_range:
                o = self._getany(self._decode_to_node(node[i]), path=path+[i])
                if o:
                    return [i] + o
            return None
        curr_key = without_terminator(unpack_to_nibbles(node[0]))
        if node_type == NODE_TYPE_LEAF:
            return curr_key

        if node_type == NODE_TYPE_EXTENSION:
            curr_key = without_terminator(unpack_to_nibbles(node[0]))
            sub_node = self._decode_to_node(node[1])
            return self._getany(sub_node, path=path+curr_key)

    def _iter(self, node, key, reverse=False, path=[]):
        node_type = self._get_node_type(node)

        if node_type == NODE_TYPE_BLANK:
            return None

        elif node_type == NODE_TYPE_BRANCH:
            if len(key):
                sub_node = self._decode_to_node(node[key[0]])
                o = self._iter(sub_node, key[1:], reverse, path+[key[0]])
                if o:
                    return [key[0]] + o
            if reverse:
                scan_range = range(key[0] if len(key) else 0)
            else:
                scan_range = range(key[0]+1 if len(key) else 0, 16)
            for i in scan_range:
                sub_node = self._decode_to_node(node[i])
                o = self._getany(sub_node, reverse, path+[i])
                if o:
                    return [i] + o
            if reverse and node[16]:
                return [16]
            return None

        descend_key = without_terminator(unpack_to_nibbles(node[0]))
        if node_type == NODE_TYPE_LEAF:
            if reverse:
                return descend_key if descend_key < key else None
            else:
                return descend_key if descend_key > key else None

        if node_type == NODE_TYPE_EXTENSION:
            # traverse child nodes
            sub_node = self._decode_to_node(node[1])
            sub_key = key[len(descend_key):]
            if starts_with(key, descend_key):
                o = self._iter(sub_node, sub_key, reverse, path + descend_key)
            elif descend_key > key[:len(descend_key)] and not reverse:
                o = self._getany(sub_node, sub_key, False, path + descend_key)
            elif descend_key < key[:len(descend_key)] and reverse:
                o = self._getany(sub_node, sub_key, True, path + descend_key)
            else:
                o = None
            return descend_key + o if o else None

    def next(self, key):
        key = bin_to_nibbles(key)
        o = self._iter(self.root_node, key)
        return nibbles_to_bin(o) if o else None

    def prev(self, key):
        key = bin_to_nibbles(key)
        o = self._iter(self.root_node, key, reverse=True)
        return nibbles_to_bin(o) if o else None

    def _delete_node_storage(self, node):
        '''delete storage
        :param node: node in form of list, or BLANK_NODE
        '''
        if node == BLANK_NODE:
            return
        assert isinstance(node, list)
        encoded = self._encode_node(node)
        if len(encoded) < 32:
            return
        """
        ===== FIXME ====
        in the current trie implementation two nodes can share identical subtrees
        thus we can not safely delete nodes for now
        """
        #self.db.delete(encoded) # FIXME

    def _delete(self, node, key):
        """ update item inside a node

        :param node: node in form of list, or BLANK_NODE
        :param key: nibble list without terminator
            .. note:: key may be []
        :return: new node

        if this node is changed to a new node, it's parent will take the
        responsibility to *store* the new node storage, and delete the old
        node storage
        """
        node_type = self._get_node_type(node)
        if node_type == NODE_TYPE_BLANK:
            return BLANK_NODE

        if node_type == NODE_TYPE_BRANCH:
            return self._delete_branch_node(node, key)

        if is_key_value_type(node_type):
            return self._delete_kv_node(node, key)

    def _normalize_branch_node(self, node):
        '''node should have only one item changed
        '''
        not_blank_items_count = sum(1 for x in range(17) if node[x])
        assert not_blank_items_count >= 1

        if not_blank_items_count > 1:
            return node

        # now only one item is not blank
        not_blank_index = [i for i, item in enumerate(node) if item][0]

        # the value item is not blank
        if not_blank_index == 16:
            return [pack_nibbles(with_terminator([])), node[16]]

        # normal item is not blank
        sub_node = self._decode_to_node(node[not_blank_index])
        sub_node_type = self._get_node_type(sub_node)

        if is_key_value_type(sub_node_type):
            # collape subnode to this node, not this node will have same
            # terminator with the new sub node, and value does not change
            new_key = [not_blank_index] + \
                unpack_to_nibbles(sub_node[0])
            return [pack_nibbles(new_key), sub_node[1]]
        if sub_node_type == NODE_TYPE_BRANCH:
            return [pack_nibbles([not_blank_index]),
                    self._encode_node(sub_node)]
        assert False

    def _delete_and_delete_storage(self, node, key):
        old_node = node[:]
        new_node = self._delete(node, key)
        if old_node != new_node:
            self._delete_node_storage(old_node)
        return new_node

    def _delete_branch_node(self, node, key):
        # already reach the expected node
        if not key:
            node[-1] = BLANK_NODE
            return self._normalize_branch_node(node)

        encoded_new_sub_node = self._encode_node(
            self._delete_and_delete_storage(
                self._decode_to_node(node[key[0]]), key[1:])
        )

        if encoded_new_sub_node == node[key[0]]:
            return node

        node[key[0]] = encoded_new_sub_node
        if encoded_new_sub_node == BLANK_NODE:
            return self._normalize_branch_node(node)

        return node

    def _delete_kv_node(self, node, key):
        node_type = self._get_node_type(node)
        assert is_key_value_type(node_type)
        curr_key = without_terminator(unpack_to_nibbles(node[0]))

        if not starts_with(key, curr_key):
            # key not found
            return node

        if node_type == NODE_TYPE_LEAF:
            return BLANK_NODE if key == curr_key else node

        # for inner key value type
        new_sub_node = self._delete_and_delete_storage(
            self._decode_to_node(node[1]), key[len(curr_key):])

        if self._encode_node(new_sub_node) == node[1]:
            return node

        # new sub node is BLANK_NODE
        if new_sub_node == BLANK_NODE:
            return BLANK_NODE

        assert isinstance(new_sub_node, list)

        # new sub node not blank, not value and has changed
        new_sub_node_type = self._get_node_type(new_sub_node)

        if is_key_value_type(new_sub_node_type):
            # collape subnode to this node, not this node will have same
            # terminator with the new sub node, and value does not change
            new_key = curr_key + unpack_to_nibbles(new_sub_node[0])
            return [pack_nibbles(new_key), new_sub_node[1]]

        if new_sub_node_type == NODE_TYPE_BRANCH:
            return [pack_nibbles(curr_key), self._encode_node(new_sub_node)]

        # should be no more cases
        assert False

    def delete(self, key):
        '''
        :param key: a string with length of [0, 32]
        '''
        if not isinstance(key, (str, unicode)):
            raise Exception("Key must be string")

        if len(key) > 32:
            raise Exception("Max key length is 32")

        self.root_node = self._delete_and_delete_storage(
            self.root_node,
            bin_to_nibbles(str(key)))
        self.get_root_hash()

    def _get_size(self, node):
        '''Get counts of (key, value) stored in this and the descendant nodes

        :param node: node in form of list, or BLANK_NODE
        '''
        if node == BLANK_NODE:
            return 0

        node_type = self._get_node_type(node)

        if is_key_value_type(node_type):
            value_is_node = node_type == NODE_TYPE_EXTENSION
            if value_is_node:
                return self._get_size(self._decode_to_node(node[1]))
            else:
                return 1
        elif node_type == NODE_TYPE_BRANCH:
            sizes = [self._get_size(self._decode_to_node(node[x]))
                     for x in range(16)]
            sizes = sizes + [1 if node[-1] else 0]
            return sum(sizes)

    def _to_dict(self, node):
        '''convert (key, value) stored in this and the descendant nodes
        to dict items.

        :param node: node in form of list, or BLANK_NODE

        .. note::

            Here key is in full form, rather than key of the individual node
        '''
        if node == BLANK_NODE:
            return {}

        node_type = self._get_node_type(node)

        if is_key_value_type(node_type):
            nibbles = without_terminator(unpack_to_nibbles(node[0]))
            key = '+'.join([str(x) for x in nibbles])
            if node_type == NODE_TYPE_EXTENSION:
                sub_dict = self._to_dict(self._decode_to_node(node[1]))
            else:
                sub_dict = {str(NIBBLE_TERMINATOR): node[1]}

            # prepend key of this node to the keys of children
            res = {}
            for sub_key, sub_value in sub_dict.iteritems():
                full_key = '{0}+{1}'.format(key, sub_key).strip('+')
                res[full_key] = sub_value
            return res

        elif node_type == NODE_TYPE_BRANCH:
            res = {}
            for i in range(16):
                sub_dict = self._to_dict(self._decode_to_node(node[i]))

                for sub_key, sub_value in sub_dict.iteritems():
                    full_key = '{0}+{1}'.format(i, sub_key).strip('+')
                    res[full_key] = sub_value

            if node[16]:
                res[str(NIBBLE_TERMINATOR)] = node[-1]
            return res

    def to_dict(self):
        d = self._to_dict(self.root_node)
        res = {}
        for key_str, value in d.iteritems():
            if key_str:
                nibbles = [int(x) for x in key_str.split('+')]
            else:
                nibbles = []
            key = nibbles_to_bin(without_terminator(nibbles))
            res[key] = value
        return res

    def get(self, key):
        return self._get(self.root_node, bin_to_nibbles(str(key)))

    def __len__(self):
        return self._get_size(self.root_node)

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        return self.update(key, value)

    def __delitem__(self, key):
        return self.delete(key)

    def __iter__(self):
        return iter(self.to_dict())

    def __contains__(self, key):
        return self.get(key) != BLANK_NODE

    def update(self, key, value):
        '''
        :param key: a string
        :value: a string
        '''
        if not isinstance(key, (str, unicode)):
            raise Exception("Key must be string")

        # if len(key) > 32:
        #     raise Exception("Max key length is 32")

        if not isinstance(value, (str, unicode)):
            raise Exception("Value must be string")

        # if value == '':
        #     return self.delete(key)

        self.root_node = self._update_and_delete_storage(
            self.root_node,
            bin_to_nibbles(str(key)),
            value)
        self.get_root_hash()

    def root_hash_valid(self):
        if self.root_hash == BLANK_ROOT:
            return True
        return self.root_hash in self.db

    def produce_spv_proof(self, key):
        self.proof_mode = RECORDING
        self.proof_nodes = [self.root_node]
        self.get(key)
        self.proof_mode = NONE
        o = self.proof_nodes
        self.proof_nodes = []
        return o


def verify_spv_proof(root, key, proof):
    t = Trie(db.EphemDB())
    t.proof_mode = VERIFYING
    t.proof_nodes = proof
    for i, node in enumerate(proof):
        R = rlp.encode(node)
        H = utils.sha3(R)
        t.db.put(H, R)
    try:
        t.root_hash = root
        t.get(key)
        return True
    except Exception, e:
        print e
        return False


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
            print encode_node(t.root_hash)
        elif sys.argv[1] == 'get':
            t = Trie(sys.argv[2], sys.argv[3].decode('hex'))
            print t.get(sys.argv[4])
