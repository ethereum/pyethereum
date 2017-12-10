try:
    from Crypto.Hash import keccak

    def sha3_256(x): return keccak.new(digest_bits=256, data=x).digest()
except ImportError:
    import sha3 as _sha3

    def sha3_256(x): return _sha3.keccak_256(x).digest()
from py_ecc.secp256k1 import privtopub, ecdsa_raw_sign, ecdsa_raw_recover
import sys
import rlp
from rlp.sedes import big_endian_int, BigEndianInt, Binary
from rlp.utils import decode_hex, encode_hex, ascii_chr, str_to_bytes
import random


try:
    import coincurve
except ImportError:
    import warnings
    warnings.warn('could not import coincurve', ImportWarning)
    coincurve = None

class Memoize:
    def __init__(self, fn):
        self.fn = fn
        self.memo = {}
    def __call__(self, *args):
        if args not in self.memo:
            self.memo[args] = self.fn(*args)
        return self.memo[args]

def big_endian_to_int(x): return big_endian_int.deserialize(
    str_to_bytes(x).lstrip(b'\x00'))


def int_to_big_endian(x): return big_endian_int.serialize(x)


TT256 = 2 ** 256
TT256M1 = 2 ** 256 - 1
TT255 = 2 ** 255
SECP256K1P = 2**256 - 4294968273

if sys.version_info.major == 2:
    def is_numeric(x): return isinstance(x, (int, long))

    def is_string(x): return isinstance(x, (str, unicode))

    def to_string(value):
        return str(value)

    def int_to_bytes(value):
        if isinstance(value, str):
            return value
        return int_to_big_endian(value)

    def to_string_for_regexp(value):
        return str(value)
    unicode = unicode

    def bytearray_to_bytestr(value):
        return bytes(''.join(chr(c) for c in value))

    def encode_int32(v):
        return zpad(int_to_big_endian(v), 32)

    def bytes_to_int(value):
        return big_endian_to_int(bytes(''.join(chr(c) for c in value)))

else:
    def is_numeric(x): return isinstance(x, int)

    def is_string(x): return isinstance(x, bytes)

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

    def to_string_for_regexp(value):
        return str(to_string(value), 'utf-8')
    unicode = str

    def bytearray_to_bytestr(value):
        return bytes(value)

    def encode_int32(v):
        return v.to_bytes(32, byteorder='big')

    def bytes_to_int(value):
        return int.from_bytes(value, byteorder='big')


def ecrecover_to_pub(rawhash, v, r, s):
    if coincurve and hasattr(coincurve, "PublicKey"):
        try:
            pk = coincurve.PublicKey.from_signature_and_message(
                zpad(bytearray_to_bytestr(int_to_32bytearray(r)), 32) + zpad(bytearray_to_bytestr(int_to_32bytearray(s)), 32) +
                ascii_chr(v - 27),
                rawhash,
                hasher=None,
            )
            pub = pk.format(compressed=False)[1:]
        except BaseException:
            pub = b"\x00" * 64
    else:
        result = ecdsa_raw_recover(rawhash, (v, r, s))
        if result:
            x, y = result
            pub = encode_int32(x) + encode_int32(y)
        else:
            raise ValueError('Invalid VRS')
    assert len(pub) == 64
    return pub


def ecsign(rawhash, key):
    if coincurve and hasattr(coincurve, 'PrivateKey'):
        pk = coincurve.PrivateKey(key)
        signature = pk.sign_recoverable(rawhash, hasher=None)
        v = safe_ord(signature[64]) + 27
        r = big_endian_to_int(signature[0:32])
        s = big_endian_to_int(signature[32:64])
    else:
        v, r, s = ecdsa_raw_sign(rawhash, key)
    return v, r, s


def mk_contract_address(sender, nonce):
    return sha3(rlp.encode([normalize_address(sender), nonce]))[12:]


def mk_metropolis_contract_address(sender, initcode):
    return sha3(normalize_address(sender) + initcode)[12:]


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

# sha3_count = [0]


def sha3(seed):
    return sha3_256(to_string(seed))


assert encode_hex(
    sha3(b'')) == 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'


@Memoize
def privtoaddr(k):
    k = normalize_key(k)
    x, y = privtopub(k)
    return sha3(encode_int32(x) + encode_int32(y))[12:]


def checksum_encode(addr):  # Takes a 20-byte binary address as input
    addr = normalize_address(addr)
    o = ''
    v = big_endian_to_int(sha3(encode_hex(addr)))
    for i, c in enumerate(encode_hex(addr)):
        if c in '0123456789':
            o += c
        else:
            o += c.upper() if (v & (2**(255 - 4 * i))) else c.lower()
    return '0x' + o


def check_checksum(addr):
    return checksum_encode(normalize_address(addr)) == addr


def normalize_address(x, allow_blank=False):
    if is_numeric(x):
        return int_to_addr(x)
    if allow_blank and x in {'', b''}:
        return b''
    if len(x) in (42, 50) and x[:2] in {'0x', b'0x'}:
        x = x[2:]
    if len(x) in (40, 48):
        x = decode_hex(x)
    if len(x) == 24:
        assert len(x) == 24 and sha3(x[:20])[:4] == x[-4:]
        x = x[:20]
    if len(x) != 20:
        raise Exception("Invalid address format: %r" % x)
    return x


def normalize_key(key):
    if is_numeric(key):
        o = encode_int32(key)
    elif len(key) == 32:
        o = key
    elif len(key) == 64:
        o = decode_hex(key)
    elif len(key) == 66 and key[:2] == '0x':
        o = decode_hex(key[2:])
    else:
        raise Exception("Invalid key format: %r" % key)
    if o == b'\x00' * 32:
        raise Exception("Zero privkey invalid")
    return o


def zpad(x, l):
    """ Left zero pad value `x` at least to length `l`.

    >>> zpad('', 1)
    '\x00'
    >>> zpad('\xca\xfe', 4)
    '\x00\x00\xca\xfe'
    >>> zpad('\xff', 1)
    '\xff'
    >>> zpad('\xca\xfe', 2)
    '\xca\xfe'
    """
    return b'\x00' * max(0, l - len(x)) + x


def rzpad(value, total_length):
    """ Right zero pad value `x` at least to length `l`.

    >>> zpad('', 1)
    '\x00'
    >>> zpad('\xca\xfe', 4)
    '\xca\xfe\x00\x00'
    >>> zpad('\xff', 1)
    '\xff'
    >>> zpad('\xca\xfe', 2)
    '\xca\xfe'
    """
    return value + b'\x00' * max(0, total_length - len(value))


def int_to_addr(x):
    o = [b''] * 20
    for i in range(20):
        o[19 - i] = ascii_chr(x & 0xff)
        x >>= 8
    return b''.join(o)


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


def parse_int_or_hex(s):
    if is_numeric(s):
        return s
    elif s[:2] in (b'0x', '0x'):
        s = to_string(s)
        tail = (b'0' if len(s) % 2 else b'') + s[2:]
        return big_endian_to_int(decode_hex(tail))
    else:
        return int(s)


def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)


def to_signed(i):
    return i if i < TT255 else i - TT256


def sha3rlp(x):
    return sha3(rlp.encode(x))


# Format encoders/decoders for bin, addr, int


def decode_bin(v):
    """decodes a bytearray from serialization"""
    if not is_string(v):
        raise Exception("Value must be binary, not RLP array")
    return v


def decode_addr(v):
    """decodes an address from serialization"""
    if len(v) not in [0, 20]:
        raise Exception("Serialized addresses must be empty or 20 bytes long!")
    return encode_hex(v)


def decode_int(v):
    """decodes and integer from serialization"""
    if len(v) > 0 and (v[0] == b'\x00' or v[0] == 0):
        raise Exception("No leading zero bytes allowed for integers")
    return big_endian_to_int(v)


def decode_int256(v):
    return big_endian_to_int(v)


def encode_bin(v):
    """encodes a bytearray into serialization"""
    return v


def encode_root(v):
    """encodes a trie root into serialization"""
    return v


def encode_int(v):
    """encodes an integer into serialization"""
    if not is_numeric(v) or v < 0 or v >= TT256:
        raise Exception("Integer invalid or out of range: %r" % v)
    return int_to_big_endian(v)


def encode_int256(v):
    return zpad(int_to_big_endian(v), 256)


def scan_bin(v):
    if v[:2] in ('0x', b'0x'):
        return decode_hex(v[2:])
    else:
        return decode_hex(v)


def scan_int(v):
    if v[:2] in ('0x', b'0x'):
        return big_endian_to_int(decode_hex(v[2:]))
    else:
        return int(v)


# Decoding from RLP serialization
decoders = {
    "bin": decode_bin,
    "addr": decode_addr,
    "int": decode_int,
    "int256b": decode_int256,
}

# Encoding to RLP serialization
encoders = {
    "bin": encode_bin,
    "int": encode_int,
    "trie_root": encode_root,
    "int256b": encode_int256,
}

# Encoding to printable format
printers = {
    "bin": lambda v: '0x' + encode_hex(v),
    "addr": lambda v: v,
    "int": lambda v: to_string(v),
    "trie_root": lambda v: encode_hex(v),
    "int256b": lambda x: encode_hex(zpad(encode_int256(x), 256))
}

# Decoding from printable format
scanners = {
    "bin": scan_bin,
    "addr": lambda x: x[2:] if x[:2] in (b'0x', '0x') else x,
    "int": scan_int,
    "trie_root": lambda x: scan_bin,
    "int256b": lambda x: big_endian_to_int(decode_hex(x))
}


def int_to_hex(x):
    o = encode_hex(encode_int(x))
    return '0x' + (o[1:] if (len(o) > 0 and o[0] == b'0') else o)


def remove_0x_head(s):
    return s[2:] if s[:2] in (b'0x', '0x') else s


def parse_as_bin(s):
    return decode_hex(s[2:] if s[:2] == '0x' else s)


def parse_as_int(s):
    return s if is_numeric(s) else int(
        '0' + s[2:], 16) if s[:2] == '0x' else int(s)


def print_func_call(ignore_first_arg=False, max_call_number=100):
    """ utility function to facilitate debug, it will print input args before
    function call, and print return value after function call

    usage:

        @print_func_call
        def some_func_to_be_debu():
            pass

    :param ignore_first_arg: whether print the first arg or not.
    useful when ignore the `self` parameter of an object method call
    """
    from functools import wraps

    def display(x):
        x = to_string(x)
        try:
            x.decode('ascii')
        except BaseException:
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


def dump_state(trie):
    res = ''
    for k, v in list(trie.to_dict().items()):
        res += '%r:%r\n' % (encode_hex(k), encode_hex(v))
    return res


class Denoms():

    def __init__(self):
        self.wei = 1
        self.babbage = 10 ** 3
        self.ada = 10 ** 3
        self.kwei = 10 ** 6
        self.lovelace = 10 ** 6
        self.mwei = 10 ** 6
        self.shannon = 10 ** 9
        self.gwei = 10 ** 9
        self.szabo = 10 ** 12
        self.finney = 10 ** 15
        self.mether = 10 ** 15
        self.ether = 10 ** 18
        self.turing = 2 ** 256 - 1


denoms = Denoms()


address = Binary.fixed_length(20, allow_empty=True)
int20 = BigEndianInt(20)
int32 = BigEndianInt(32)
int256 = BigEndianInt(256)
hash32 = Binary.fixed_length(32)
trie_root = Binary.fixed_length(32, allow_empty=True)


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[91m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def DEBUG(msg, *args, **kwargs):
    from ethereum import slogging

    slogging.DEBUG(msg, *args, **kwargs)
