from sha3 import sha3_256
from bitcoin import privtopub

def sha3(seed):
    return sha3_256(seed).digest()

def privtoaddr(x):
    if len(x) > 32: x = x.decode('hex')
    return sha3(privtopub(x)[1:])[12:].encode('hex')

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


def print_func_call(ignore_first_arg=False, max_call_number=100):
    '''
    :param ignore_first_arg: whether print the first arg or not.
    useful when ignore the `self` parameter of an object method call
    '''
    from functools import wraps

    def display(x):
        x = str(x)
        try:
            x.decode('ascii')
        except:
            return 'NON_PRINTABLE'
        return x

    local = {'call_number': 0}

    def inner(f):

        @wraps(f)
        def wrapper(*args, **kwargs):
            local['call_number'] = local['call_number'] + 1
            tmp_args = args[1:] if ignore_first_arg and len(args) else args
            print('{0}#{1} args: {2}, {3}'.format(
                f.__name__,
                local['call_number'],
                ', '.join([display(x) for x in tmp_args]),
                ', '.join(display(key) + '=' + str(value)
                          for key, value in kwargs.iteritems())
            ))
            res = f(*args, **kwargs)
            print('{0}#{1} return: {2}'.format(
                f.__name__,
                local['call_number'],
                display(res)))

            if local['call_number'] > 100:
                raise Exception("Touch max call number!")
            return res
        return wrapper
    return inner
