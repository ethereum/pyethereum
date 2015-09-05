import sys
import rlp
from utils import int_to_big_endian
import db


def _encode_optimized(item):
    """RLP encode (a nested sequence of) bytes"""
    if isinstance(item, bytes):
        if len(item) == 1 and ord(item) < 128:
            return item
        prefix = length_prefix(len(item), 128)
    else:
        item = b''.join([_encode_optimized(x) for x in item])
        prefix = length_prefix(len(item), 192)
    return prefix + item


def length_prefix(length, offset):
    """Construct the prefix to lists or strings denoting their length.

    :param length: the length of the item in bytes
    :param offset: ``0x80`` when encoding raw bytes, ``0xc0`` when encoding a
                   list
    """
    if length < 56:
        return chr(offset + length)
    else:
        length_string = int_to_big_endian(length)
        return chr(offset + 56 - 1 + len(length_string)) + length_string

#
if sys.version_info.major == 2:
    encode_optimized = _encode_optimized
else:
    encode_optimized = rlp.codec.encode_raw


def main():
    import trie
    import time

    def run():
        st = time.time()
        x = trie.Trie(db.EphemDB())
        for i in range(10000):
            x.update(str(i), str(i**3))
        print 'elapsed', time.time() - st
        return x.root_hash

    trie.rlp_encode = _encode_optimized
    print 'trie.rlp_encode = encode_optimized'
    r3 = run()

    trie.rlp_encode = rlp.codec.encode_raw
    print 'trie.rlp_encode = rlp.codec.encode_raw'
    r2 = run()
    assert r2 == r3

    trie.rlp_encode = rlp.encode
    print 'trie.rlp_encode = rlp.encode'
    r = run()
    assert r == r2

if __name__ == '__main__':
    main()
