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


def recurseive_int_to_big_endian(item):
    ''' convert all int to int_to_big_endian recursively
    '''
    if isinstance(item, (int, long)):
        return int_to_big_endian(item)
    elif isinstance(item, (list, tuple)):
        res = []
        for item in item:
            res.append(recurseive_int_to_big_endian(item))
        return res
    return item


call_id = 0


def print_func_call(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        global call_id
        call_id = call_id + 1
        print('[{0}]{1} args: {2} {3}'.format(
            call_id, f.__name__, args, kwargs))
        res = f(*args, **kwargs)
        print('[{0}]{1} return: {2}'.format(call_id, f.__name__, res))
        return res
    return wrapper
