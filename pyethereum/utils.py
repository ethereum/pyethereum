from sha3 import sha3_256
from bitcoin import privtopub
import struct
import os
import sys
import rlp
from rlp.sedes import big_endian_int, BigEndianInt, Binary
from rlp.utils import int_to_big_endian, decode_hex, encode_hex, ascii_chr, str_to_bytes
from pyethereum import db
import random

TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1
TT255 = 2 ** 255

if sys.version_info.major == 2:
    is_numeric = lambda x: isinstance(x, (int, long))
    is_string = lambda x: isinstance(x, (str, unicode))

    def to_string(value):
        return str(value)

    def int_to_bytes(value):
        if isinstance(value, str):
            return value
        return int_to_big_endian(value)

else:
    is_numeric = lambda x: isinstance(x, int)
    is_string = lambda x: isinstance(x, bytes)

    def to_string(value):
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return bytes(value, 'utf-8')
        if isinstance(value, int):
            return bytes(str(value), 'utf-8')

    def int_to_bytes(value):
        if isinstance(value, bytes):
            return value
        return int_to_big_endian(value)

def safe_ord(value):
    if isinstance(value, int):
        return value
    else:
        return ord(value)

# decorator

def debug(label):
    def deb(f):
        def inner(*args, **kwargs):
            i = random.randrange(1000000)
            print(label, i, 'start', args)
            x = f(*args, **kwargs)
            print(label, i, 'end', x)
            return x
        return inner
    return deb


def flatten(li):
    o = []
    for l in li:
        o.extend(l)
    return o

big_endian_to_int = lambda x: big_endian_int.deserialize(str_to_bytes(x).lstrip(b'\x00'))
int_to_big_endian = lambda x: big_endian_int.serialize(x)


def bytearray_to_int(arr):
    o = 0
    for a in arr:
        o = (o << 8) + a
    return o


def int_to_32bytearray(i):
    o = [0] * 32
    for x in range(32):
        o[31 - x] = i & 0xff
        i >>= 8
    return o


def sha3(seed):
    return sha3_256(seed).digest()


def privtoaddr(x):
    if len(x) > 32:
        x = decode_hex(x)
    return encode_hex(sha3(privtopub(x)[1:])[12:])


def zpad(x, l):
    return b'\x00' * max(0, l - len(x)) + x


def zunpad(x):
    i = 0
    while i < len(x) and (x[i] == 0 or x[i] == '\x00'):
        i += 1
    return x[i:]


def int_to_addr(x):
    o = [''] * 20
    for i in range(20):
        o[19 - i] = ascii_chr(x & 0xff)
        x >>= 8
    return encode_hex(b''.join(o))


def coerce_addr_to_bin(x):
    if is_numeric(x):
        return encode_hex(zpad(big_endian_int.serialize(x), 20))
    elif len(x) == 40 or len(x) == 0:
        return decode_hex(x)
    else:
        return zpad(x, 20)[-20:]


def coerce_addr_to_hex(x):
    if is_numeric(x):
        return encode_hex(zpad(big_endian_int.serialize(x), 20))
    elif len(x) == 40 or len(x) == 0:
        return x
    else:
        return encode_hex(zpad(x, 20)[-20:])


def coerce_to_int(x):
    if is_numeric(x):
        return x
    elif len(x) == 40:
        return big_endian_to_int(decode_hex(x))
    else:
        return big_endian_to_int(x)


def coerce_to_bytes(x):
    if is_numeric(x):
        return big_endian_int.serialize(x)
    elif len(x) == 40:
        return decode_hex(x)
    else:
        return x


def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)


def to_signed(i):
    return i if i < TT255 else i - TT256


def sha3rlp(x):
    return sha3(rlp.encode(x))


def int_to_big_endian4(integer):
    ''' 4 bytes big endian integer'''
    return struct.pack('>I', integer)


def recursive_int_to_big_endian(item):
    ''' convert all int to int_to_big_endian recursively
    '''
    if is_numeric(item):
        return big_endian_int.serialize(item)
    elif isinstance(item, (list, tuple)):
        res = []
        for item in item:
            res.append(recursive_int_to_big_endian(item))
        return res
    return item


def rlp_encode(item):
    '''
    item can be nested string/integer/list of string/integer
    '''
    return rlp.encode(recursive_int_to_big_endian(item))

# Format encoders/decoders for bin, addr, int


def decode_bin(v):
    '''decodes a bytearray from serialization'''
    if not is_string(v):
        raise Exception("Value must be binary, not RLP array")
    return v


def decode_addr(v):
    '''decodes an address from serialization'''
    if len(v) not in [0, 20]:
        raise Exception("Serialized addresses must be empty or 20 bytes long!")
    return encode_hex(v)


def decode_int(v):
    '''decodes and integer from serialization'''
    if len(v) > 0 and (v[0] == '\x00' or v[0] == 0):
        raise Exception("No leading zero bytes allowed for integers")
    return big_endian_to_int(v)


def decode_root(root):
    if isinstance(root, list):
        if len(rlp.encode(root)) >= 32:
            raise Exception("Direct RLP roots must have length <32")
    elif is_string(root):
        if len(root) != 0 and len(root) != 32:
            raise Exception("String roots must be empty or length-32")
    else:
        raise Exception("Invalid root")
    return root


def decode_int256(v):
    return big_endian_to_int(v)


def encode_bin(v):
    '''encodes a bytearray into serialization'''
    return v


def encode_root(v):
    '''encodes a trie root into serialization'''
    return v


def encode_addr(v):
    '''encodes an address into serialization'''
    if not is_string(v) or len(v) not in [0, 40]:
        raise Exception("Address must be empty or 40 chars long")
    return decode_hex(v)


def encode_int(v):
    '''encodes an integer into serialization'''
    if not is_numeric(v) or v < 0 or v >= TT256:
        raise Exception("Integer invalid or out of range: %r" % v)
    return int_to_big_endian(v)


def encode_int256(v):
    return zpad(int_to_big_endian(v), 256)


def scan_bin(v):
    if v[:2] == '0x':
        return decode_hex(v[2:])
    else:
        return decode_hex(v)


def scan_int(v):
    if v[:2] == '0x':
        return big_endian_to_int(decode_hex(v[2:]))
    else:
        return int(v)


# Decoding from RLP serialization
decoders = {
    "bin": decode_bin,
    "addr": decode_addr,
    "int": decode_int,
    "trie_root": decode_root,
    "int256b": decode_int256,
}

# Encoding to RLP serialization
encoders = {
    "bin": encode_bin,
    "addr": encode_addr,
    "int": encode_int,
    "trie_root": encode_root,
    "int256b": encode_int256,
}

# Encoding to printable format
printers = {
    "bin": lambda v: b'0x' + encode_hex(v),
    "addr": lambda v: v,
    "int": lambda v: to_string(v),
    "trie_root": lambda v: encode_hex(v),
    "int256b": lambda x: encode_hex(zpad(encode_int256(x), 256))
}

# Decoding from printable format
scanners = {
    "bin": scan_bin,
    "addr": lambda x: x[2:] if x[:2] == b'0x' else x,
    "int": scan_int,
    "trie_root": lambda x: scan_bin,
    "int256b": lambda x: big_endian_to_int(decode_hex(x))
}


def print_func_call(ignore_first_arg=False, max_call_number=100):
    ''' utility function to facilitate debug, it will print input args before
    function call, and print return value after function call

    usage:

        @print_func_call
        def some_func_to_be_debu():
            pass

    :param ignore_first_arg: whether print the first arg or not.
    useful when ignore the `self` parameter of an object method call
    '''
    from functools import wraps

    def display(x):
        x = to_string(x)
        try:
            x.decode('ascii')
        except:
            return 'NON_PRINTABLE'
        return x

    local = {'call_number': 0}

    def inner(f):

        @wraps(f)
        def wrapper(*args, **kwargs):
            local['call_number'] += 1
            tmp_args = args[1:] if ignore_first_arg and len(args) else args
            this_call_number = local['call_number']
            print(('{0}#{1} args: {2}, {3}'.format(
                f.__name__,
                this_call_number,
                ', '.join([display(x) for x in tmp_args]),
                ', '.join(display(key) + '=' + to_string(value)
                          for key, value in kwargs.items())
            )))
            res = f(*args, **kwargs)
            print(('{0}#{1} return: {2}'.format(
                f.__name__,
                this_call_number,
                display(res))))

            if local['call_number'] > 100:
                raise Exception("Touch max call number!")
            return res
        return wrapper
    return inner


class DataDir(object):

    ethdirs = {
        "linux2": "~/.pyethereum",
        "darwin": "~/Library/Application Support/Pyethereum/",
        "win32": "~/AppData/Roaming/Pyethereum",
        "win64": "~/AppData/Roaming/Pyethereum",
    }

    def __init__(self):
        self._path = None

    def set(self, path):
        path = os.path.abspath(path)
        if not os.path.exists(path):
            os.makedirs(path)
        assert os.path.isdir(path)
        self._path = path

    def _set_default(self):
        p = self.ethdirs.get(sys.platform, self.ethdirs['linux2'])
        self.set(os.path.expanduser(os.path.normpath(p)))

    @property
    def path(self):
        if not self._path:
            self._set_default()
        return self._path

#data_dir = DataDir()

default_data_dir = DataDir().path


def db_path(data_dir):
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return os.path.join(data_dir, 'statedb')


def dump_state(trie):
    res = ''
    for k, v in list(trie.to_dict().items()):
        res += '%r:%r\n' % (encode_hex(k), encode_hex(v))
    return res


class Denoms():

    def __init__(self):
        self.wei = 1
        self.babbage = 10 ** 3
        self.lovelace = 10 ** 6
        self.shannon = 10 ** 9
        self.szabo = 10 ** 12
        self.finney = 10 ** 15
        self.ether = 10 ** 18
        self.turing = 2 ** 256

denoms = Denoms()


address = Binary.fixed_length(20, allow_empty=True)
int20 = BigEndianInt(20)
int32 = BigEndianInt(32)
int256 = BigEndianInt(256)
hash32 = Binary.fixed_length(32)
trie_root = Binary.fixed_length(32, allow_empty=True)
