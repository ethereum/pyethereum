def int_to_big_endian(integer):
    '''convert a integer to big endian binary string
    '''
    s = '%x' % integer
    if len(s) & 1:
        s = '0' + s
    return s.decode('hex')

def big_endian_to_int(string):
    '''convert a big endian binary string to integer
    '''
    s = string.encode('hex')
    return int(s, 16)
