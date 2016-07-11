import sys
import rlp
from .utils import int_to_big_endian, big_endian_to_int, safe_ord
from . import db


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

def _decode_optimized(rlp):
    o = []
    pos = 0
    _typ, _len, pos = consume_length_prefix(rlp, pos)
    if _typ != list:
        return rlp[pos: pos + _len]
    while pos < len(rlp):
        _, _l, _p = consume_length_prefix(rlp, pos)
        o.append(_decode_optimized(rlp[pos: _l + _p]))
        pos = _l + _p
    return o

def consume_length_prefix(rlp, start):
    """Read a length prefix from an RLP string.

    :param rlp: the rlp string to read from
    :param start: the position at which to start reading
    :returns: a tuple ``(type, length, end)``, where ``type`` is either ``str``
              or ``list`` depending on the type of the following payload,
              ``length`` is the length of the payload in bytes, and ``end`` is
              the position of the first payload byte in the rlp string
    """
    b0 = safe_ord(rlp[start])
    if b0 < 128:  # single byte
        return (str, 1, start)
    elif b0 < 128 + 56:  # short string
        return (str, b0 - 128, start + 1)
    elif b0 < 192:  # long string
        ll = b0 - 128 - 56 + 1
        l = big_endian_to_int(rlp[start + 1:start + 1 + ll])
        return (str, l, start + 1 + ll)
    elif b0 < 192 + 56:  # short list
        return (list, b0 - 192, start + 1)
    else:  # long list
        ll = b0 - 192 - 56 + 1
        l = big_endian_to_int(rlp[start + 1:start + 1 + ll])
        return (list, l, start + 1 + ll)

#
if sys.version_info.major == 2:
    encode_optimized = _encode_optimized
    decode_optimized = _decode_optimized
else:
    encode_optimized = rlp.codec.encode_raw
    # rlp does not implement a decode_raw function.
    # decode_optimized = rlp.codec.decode_raw
    decode_optimized = _decode_optimized


def main():
    import trie
    import time

    def run():
        st = time.time()
        x = trie.Trie(db.EphemDB())
        for i in range(10000):
            x.update(str(i), str(i**3))
        print('elapsed', time.time() - st)
        return x.root_hash

    trie.rlp_encode = _encode_optimized
    print('trie.rlp_encode = encode_optimized')
    r3 = run()

    trie.rlp_encode = rlp.codec.encode_raw
    print('trie.rlp_encode = rlp.codec.encode_raw')
    r2 = run()
    assert r2 == r3

    trie.rlp_encode = rlp.encode
    print('trie.rlp_encode = rlp.encode')
    r = run()
    assert r == r2

if __name__ == '__main__':
    main()
