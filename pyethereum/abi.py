import utils, sys, re

from utils import encode_int, zpad, decode_int


def encode_factory(id, types):
    def encode(*args):
        return encode_abi(id, types, args)
    return encode


class ContractTranslator():

    def __init__(self, full_signature):
        v = vars(self)
        for sig_item in full_signature:
            types = [f['type'] for f in sig_item['inputs']]
            name = sig_item['name']
            if name in v:
                i = 2
                while name+str(i) in v:
                    i += 1
                name += str(i)
                sys.stderr.write("Warning: multiple methods with the same "
                                 " name. Use %s to call %s with types %r"
                                 % (name, sig_item['name'], types))
            sig = name + '(' + ','.join(types) + ')'
            id = utils.decode_int(utils.sha3(sig)[:4])
            v[name] = encode_factory(id, types)


# Encodes a base type
def encode_single(arg, base, sub):
    normal_args, len_args, var_args = '', '', ''
    # Unsigned integers: uint<sz>
    if base == 'uint':
        sub = int(sub)
        assert sub % 8 == 0 and sub >= 8 and sub <= 256
        i = decint(arg)
        assert 0 <= i < 2**sub, "Value out of bounds: %r" % arg
        normal_args = zpad(encode_int(i), sub // 8)
    # Signed integers: int<sz>
    elif base == 'int':
        sub = int(sub)
        assert sub % 8 == 0 and sub >= 8 and sub <= 256
        i = decint(arg)
        assert -2**(sub-1) <= i < 2**(sub-1), "Value out of bounds: %r" % arg
        normal_args = zpad(encode_int(i % 2**sub), sub // 8)
    # Unsigned reals: ureal<high>x<low>
    elif base == 'ureal':
        high, low = [int(x) for x in sub.split('x')]
        assert high % 8 == 0 and low % 8 == 0 and high >= 0 and low >= 0 and \
            (high + low) >= 8 and (high + low) <= 256
        assert 0 <= arg < 2**high, "Value out of bounds: %r" % arg
        normal_args = zpad(encode_int(arg * 2**low), (high + low) // 8)
    # Signed reals: real<high>x<low>
    elif base == 'real':
        high, low = [int(x) for x in sub.split('x')]
        assert high % 8 == 0 and low % 8 == 0 and high >= 0 and low >= 0 and \
            (high + low) >= 8 and (high + low) <= 256
        assert -2**(high-1) <= arg < 2**(high-1), \
            "Value out of bounds: %r" % arg
        normal_args = zpad(encode_int((arg % 2**high) * 2**low),
                           (high + low) // 8)
    # Strings
    elif base == 'string':
        if not isinstance(arg, str):
            raise Exception("Expecting string: %r" % arg)
        # Fixed length: string<sz>
        if len(sub):
            assert len(arg) <= int(sub)
            normal_args = arg + '\x00' * (int(sub) - len(arg))
        # Variable length: string
        else:
            len_args = zpad(encode_int(len(arg)), 32)
            var_args = arg
    # Hashes: hash<sz>
    elif base == 'hash':
        if isinstance(arg, int):
            normal_args = zpad(encode_int(arg), int(sub))
        elif len(arg) == len(sub):
            normal_args = arg
        elif len(arg) == len(sub) * 2:
            normal_args = arg.decode('hex')
        else:
            raise Exception("Could not parse hash: %r" % arg)
    # Addresses: address (== hash160)
    elif base == 'address':
        assert sub == ''
        if isinstance(arg, int):
            normal_args = zpad(encode_int(arg), int(sub))
        elif len(arg) == 20:
            normal_args = arg
        elif len(arg) == 40:
            normal_args = arg.decode('hex')
        else:
            raise Exception("Could not parse address: %r" % arg)
    return len_args, normal_args, var_args


def process_type(typ):
    # Crazy reg expression to separate out base type component (eg. uint),
    # size (eg. 256, 128x128, none), array component (eg. [], [45], none)
    regexp = '([a-z]*)([0-9]*x?[0-9]*)((\[[0-9]*\])*)'
    base, sub, arr, _ = re.match(regexp, typ).groups()
    arrlist = re.findall('\[[0-9]*\]', arr)
    assert len(''.join(arrlist)) == len(arr), \
        "Unknown characters found in array declaration"
    for a in arrlist[:-1]:
        assert len(a) > 2, "Inner arrays must have fixed size"
    if base == 'string':
        assert len(sub) or len(arrlist) == 0, \
            "Cannot have an array of var-sized strings"
    return base, sub, arrlist


# Encodes an item of any type
def encode_any(arg, base, sub, arrlist):
    # Not an array, then encode a fixed-size type
    if len(arrlist) == 0:
        return encode_single(arg, base, sub)
    # Variable-sized arrays
    if arrlist[-1] == '[]':
        if base == 'string' and sub == '':
            raise Exception('Array of dynamic-sized items not allowed: %r'
                            % arg)
        o = ''
        assert isinstance(arg, list), "Expecting array: %r" % arg
        for a in arg:
            _, n, _ = encode_any(a, base, sub, arrlist[:-1])
            o += n
        return zpad(encode_int(len(arg)), 32), '', o
    # Fixed-sized arrays
    else:
        if base == 'string' and sub == '':
            raise Exception('Array of dynamic-sized items not allowed')
        sz = int(arrlist[-1][1:-1])
        assert isinstance(arg, list), "Expecting array: %r" % arg
        assert sz == len(arg), "Wrong number of elements in array: %r" % arg
        o = ''
        for a in arg:
            _, n, _ = encode_any(a, base, sub, arrlist[:-1])
            o += n
        return '', o, ''


# Encodes ABI data given a prefix, a list of types, and a list of arguments
def encode_abi(prefix, types, args):
    len_args = ''
    normal_args = ''
    var_args = ''
    if len(types) != len(args):
        raise Exception("Wrong number of arguments!")
    for typ, arg in zip(types, args):
        base, sub, arrlist = process_type(typ)
        l, n, v = encode_any(arg, base, sub, arrlist)
        len_args += l
        normal_args += n
        var_args += v
    return zpad(encode_int(prefix), 4) + len_args + normal_args + var_args


is_numeric = lambda x: isinstance(x, (int, long))
is_string = lambda x: isinstance(x, (str, unicode))


# Decode an integer
def decint(n):
    if is_numeric(n) and n < 2**256 and n > -2**255:
        return n
    elif is_numeric(n):
        raise Exception("Number out of range: %r" % n)
    elif is_string(n) and len(n) == 40:
        return decode_int(n.decode('hex'))
    elif is_string(n) and len(n) <= 32:
        return decode_int(n)
    elif is_string(n) and len(n) > 32:
        raise Exception("String too long: %r" % n)
    elif n is True:
        return 1
    elif n is False or n is None:
        return 0
    else:
        raise Exception("Cannot encode integer: %r" % n)
