from sha3 import sha3_256
from bitcoin import privtopub
import struct
import os
import sys
import errno
import rlp


def sha3(seed):
    return sha3_256(seed).digest()


def privtoaddr(x):
    if len(x) > 32:
        x = x.decode('hex')
    return sha3(privtopub(x)[1:])[12:].encode('hex')


def zpad(x, l):
    return '\x00' * max(0, l - len(x)) + x


def coerce_addr_to_bin(x):
    if isinstance(x, (int, long)):
        return zpad(int_to_big_endian(x), 20).encode('hex')
    elif len(x) == 40 or len(x) == 0:
        return x.decode('hex')
    else:
        return zpad(x, 20)[-20:]


def coerce_addr_to_hex(x):
    if isinstance(x, (int, long)):
        return zpad(int_to_big_endian(x), 20).encode('hex')
    elif len(x) == 40 or len(x) == 0:
        return x
    else:
        return zpad(x, 20)[-20:].encode('hex')


def coerce_to_int(x):
    if isinstance(x, (int, long)):
        return x
    elif len(x) == 40:
        return big_endian_to_int(x.decode('hex'))
    else:
        return big_endian_to_int(x)


def coerce_to_bytes(x):
    if isinstance(x, (int, long)):
        return int_to_big_endian(x)
    elif len(x) == 40:
        return x.decode('hex')
    else:
        return x


def int_to_big_endian(integer):
    '''convert a integer to big endian binary string'''
    # 0 is a special case, treated same as ''
    if integer == 0:
        return ''
    s = '%x' % integer
    if len(s) & 1:
        s = '0' + s
    return s.decode('hex')


def int_to_big_endian4(integer):
    ''' 4 bytes big endian integer'''
    return struct.pack('>I', integer)


def big_endian_to_int(string):
    '''convert a big endian binary string to integer'''
    # '' is a special case, treated same as 0
    string = string or '\x00'
    s = string.encode('hex')
    return long(s, 16)


def recursive_int_to_big_endian(item):
    ''' convert all int to int_to_big_endian recursively
    '''
    if isinstance(item, (int, long)):
        return int_to_big_endian(item)
    elif isinstance(item, (list, tuple)):
        res = []
        for item in item:
            res.append(recursive_int_to_big_endian(item))
        return res
    return item

# Format encoders/decoders for bin, addr, int


def decode_bin(v):
    '''decodes a bytearray from serialization'''
    if not isinstance(v, (str, unicode)):
        raise Exception("Value must be binary, not RLP array")
    return v


def decode_addr(v):
    '''decodes an address from serialization'''
    if len(v) not in [0, 20]:
        raise Exception("Serialized addresses must be empty or 20 bytes long!")
    return v.encode('hex')


def decode_int(v):
    '''decodes and integer from serialization'''
    if len(v) > 0 and v[0] == '\x00':
        raise Exception("No leading zero bytes allowed for integers")
    return big_endian_to_int(v)


def decode_root(root):
    if isinstance(root, list):
        if len(rlp.encode(root)) >= 32:
            raise Exception("Direct RLP roots must have length <32")
    elif isinstance(root, (str, unicode)):
        if len(root) != 0 and len(root) != 32:
            raise Exception("String roots must be empty or length-32")
    else:
        raise Exception("Invalid root")
    return root


def encode_bin(v):
    '''encodes a bytearray into serialization'''
    return v


def encode_root(v):
    '''encodes a trie root into serialization'''
    return v


def encode_addr(v):
    '''encodes an address into serialization'''
    if not isinstance(v, (str, unicode)) or len(v) not in [0, 40]:
        raise Exception("Address must be empty or 40 chars long")
    return v.decode('hex')


def encode_int(v):
    '''encodes an integer into serialization'''
    if not isinstance(v, (int, long)) or v < 0 or v >= 2**256:
        raise Exception("Integer invalid or out of range")
    return int_to_big_endian(v)

decoders = {
    "bin": decode_bin,
    "addr": decode_addr,
    "int": decode_int,
    "trie_root": decode_root,
}

encoders = {
    "bin": encode_bin,
    "addr": encode_addr,
    "int": encode_int,
    "trie_root": encode_root,
}


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


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def ensure_get_eth_dir():
    ethdirs = {
        "linux2": "~/.pyethereum",
        "darwin": "~/Library/Application Support/Pyethereum/",
        "win32": "~/AppData/Roaming/Pyethereum",
        "win64": "~/AppData/Roaming/Pyethereum",
    }
    eth_dir = ethdirs.get(sys.platform, '~/.pyethereum')
    eth_dir = os.path.expanduser(os.path.normpath(eth_dir))
    mkdir_p(eth_dir)
    return eth_dir


STATEDB_DIR = os.path.join(ensure_get_eth_dir(), 'statedb')


def get_db_path():
    return STATEDB_DIR
