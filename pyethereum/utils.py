def to_big_endian_binary(val):
    s = '%x' % val
    if len(s) & 1:
        s = '0' + s
    return s.decode('hex')
