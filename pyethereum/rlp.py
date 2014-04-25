from utils import big_endian_to_int, int_to_big_endian


def __decode(s, pos=0):
    assert pos < len(s), "read beyond end of string in __decode"

    fchar = ord(s[pos])
    if fchar < 128:
        return (s[pos], pos + 1)
    elif fchar < 184:
        b = fchar - 128
        return (s[pos + 1:pos + 1 + b], pos + 1 + b)
    elif fchar < 192:
        b = fchar - 183
        b2 = big_endian_to_int(s[pos + 1:pos + 1 + b])
        return (s[pos + 1 + b:pos + 1 + b + b2], pos + 1 + b + b2)
    elif fchar < 248:
        o = []
        pos += 1
        pos_end = pos + fchar - 192

        while pos < pos_end:
            obj, pos = __decode(s, pos)
            o.append(obj)
        assert pos == pos_end, "read beyond list boundary in __decode"
        return (o, pos)
    else:
        b = fchar - 247
        b2 = big_endian_to_int(s[pos + 1:pos + 1 + b])
        o = []
        pos += 1 + b
        pos_end = pos + b2
        while pos < pos_end:
            obj, pos = __decode(s, pos)
            o.append(obj)
        assert pos == pos_end, "read beyond list boundary in __decode"
        return (o, pos)


def decode(s):
    if s:
        return __decode(s)[0]


def into(data, pos):
    fchar = ord(data[pos])
    if fchar < 192:
        raise Exception("Cannot descend further")
    elif fchar < 248:
        return pos + 1
    else:
        return pos + 1 + (fchar - 247)


def next(data, pos):
    fchar = ord(data[pos])
    if fchar < 128:
        return pos + 1
    elif (fchar % 64) < 56:
        return pos + 1 + (fchar % 64)
    else:
        b = (fchar % 64) - 55
        b2 = big_endian_to_int(data[pos + 1:pos + 1 + b])
        return pos + 1 + b + b2


def descend(data, *indices):
    pos = 0
    for i in indices:
        fin = next(data, pos)
        pos = into(data, pos)
        for j in range(i):
            pos = next(data, pos)
            if pos >= fin:
                raise Exception("End of list")
    return data[pos: fin]


def encode_length(L, offset):
    if L < 56:
        return chr(L + offset)
    elif L < 256 ** 8:
        BL = int_to_big_endian(L)
        return chr(len(BL) + offset + 55) + BL
    else:
        raise Exception("input too long")


def encode(s):
    if isinstance(s, (str, unicode)):
        s = str(s)
        if len(s) == 1 and ord(s) < 128:
            return s
        else:
            return encode_length(len(s), 128) + s
    elif isinstance(s, list):
        output = ''
        for item in s:
            output += encode(item)
        return encode_length(len(output), 192) + output
    raise TypeError("Encoding of %s not supported" % type(s))
