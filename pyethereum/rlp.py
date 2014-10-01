'''
First byte of an encoded item

    x: single byte, itself
    |
    |
0x7f == 127

0x80 == 128
    |
    x: [0, 55] byte long string, x-0x80 == length
    |
0xb7 == 183

0xb8 == 184
    |
    x: [56, ] long string, x-0xf7 == length of the length
    |
0xbf == 191

0xc0 == 192
    |
    x: [0, 55] byte long list, x-0xc0 == length
    |
0xf7 == 247

0xf8 == 248
    |
    x: [56, ] long list, x-0xf7 == length of the length
    |
0xff == 255
'''

class EncodingError(Exception):
    pass

class DecodingError(Exception):
    pass

def int_to_big_endian(integer):
    '''convert a integer to big endian binary string'''
    # 0 is a special case, treated same as ''
    if integer == 0:
        return ''
    s = '%x' % integer
    if len(s) & 1:
        s = '0' + s
    return s.decode('hex')


def big_endian_to_int(string):
    '''convert a big endian binary string to integer'''
    # '' is a special case, treated same as 0
    string = string or '\x00'
    s = string.encode('hex')
    return long(s, 16)


def __decode(s, pos=0):
    ''' decode string start at `pos`
    :param s: string of rlp encoded data
    :param pos: start position of `s` to decode from
    :return:
        o: decoded object
        pos: end position of the obj in the string of rlp encoded data
    '''
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
        return o, pos
    else:
        b = fchar - 247
        b2 = big_endian_to_int(s[pos + 1:pos + 1 + b])
        assert b2 >= 56
        o = []
        pos += 1 + b
        pos_end = pos + b2
        while pos < pos_end:
            obj, pos = __decode(s, pos)
            o.append(obj)
        assert pos == pos_end, "read beyond list boundary in __decode"
        return o, pos


def decode(s):
    assert isinstance(s, str)
    if s:
        return __decode(s)[0]


def into(data, pos):
    fchar = ord(data[pos])
    if fchar < 192:
        raise DecodingError("Cannot descend further")
    elif fchar < 248:
        return pos + 1
    else:
        return pos + 1 + (fchar - 247)


def next_item_pos(data, pos):
    '''get position of next item in the encoded list or string:

        if list, then get next item's start position
        if string, then get next charactor's postion

    :param data: rlp encoded from list or string
    :pos: current item's position
    '''
    fchar = ord(data[pos])
    if fchar < 128:
        return pos + 1
    elif (fchar % 64) < 56:
        return pos + 1 + (fchar % 64)
    else:
        b = (fchar % 64) - 55
        b2 = big_endian_to_int(data[pos + 1:pos + 1 + b])
        assert b2 >= 56
        return pos + 1 + b + b2


def unpack(data):
    fchar = ord(data[0])
    if fchar < 128:
        return data
    elif (fchar % 64) < 56:
        return data[1:]
    else:
        b = (fchar % 64) - 55
        return data[1 + b:]


# eg. given x = rlp([a, [b,c,[d,e]], f]), descend(x,1,2) gives rlp([d,e])
def descend(data, *indices):
    pos = 0
    for i in indices:
        finish_pos = next_item_pos(data, pos)
        pos = into(data, pos)
        for j in range(i):
            pos = next_item_pos(data, pos)
            if pos >= finish_pos:
                raise DecodingError("End of list")
    finish_pos = next_item_pos(data, pos)
    return data[pos: finish_pos]


def descend_to_val(data, *indices):
    return unpack(descend(data, *indices))


def encode_length(L, offset):
    if L < 56:
        return chr(L + offset)
    elif L < 256 ** 8:
        BL = int_to_big_endian(L)
        return chr(len(BL) + offset + 55) + BL
    else:
        raise EncodingError("input too long")


def encode(s):
    # if not s:
    #     return '\x80' if s == '' else '\xc0'
    if isinstance(s, (str, unicode)):
        s = str(s)
        if len(s) == 1 and ord(s) < 128:
            return s
        else:
            return encode_length(len(s), 128) + s
    elif isinstance(s, list):
        return concat(map(encode, s))

    raise TypeError("Encoding of %s not supported" % type(s))


def concat(s):
    '''
    :param s: a list, each item is a string of a rlp encoded data
    '''
    assert isinstance(s, list)
    output = ''.join(s)
    return encode_length(len(output), 192) + output
