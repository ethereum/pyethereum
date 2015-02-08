import utils, sys, re, json

from utils import encode_int, zpad, big_endian_to_int


def json_decode(x):
    return json_non_unicode(json.loads(x))


def json_non_unicode(x):
    if isinstance(x, unicode):
        return str(x)
    elif isinstance(x, list):
        return [json_non_unicode(y) for y in x]
    elif isinstance(x, dict):
        return {x: json_non_unicode(y) for x, y in x.items()}
    else:
        return x


class ContractTranslator():

    def __init__(self, full_signature):
        self.function_data = {}
        v = vars(self)
        if isinstance(full_signature, str):
            full_signature = json_decode(full_signature)
        for sig_item in full_signature:
            encode_types = [f['type'] for f in sig_item['inputs']]
            name = sig_item['name']
            if name in v:
                i = 2
                while name+str(i) in v:
                    i += 1
                name += str(i)
                sys.stderr.write("Warning: multiple methods with the same "
                                 " name. Use %s to call %s with types %r"
                                 % (name, sig_item['name'], encode_types))
            sig = name + '(' + ','.join(encode_types) + ')'
            prefix = big_endian_to_int(utils.sha3(sig)[:4])
            decode_types = [f['type'] for f in sig_item['outputs']]
            is_unknown_type = len(sig_item['outputs']) and \
                sig_item['outputs'][0]['name'] == 'unknown_out'
            self.function_data[name] = {
                "prefix": prefix,
                "encode_types": encode_types,
                "decode_types": decode_types,
                "is_unknown_type": is_unknown_type
            }
            print self.function_data[name]

    def encode(self, name, args):
        fdata = self.function_data[name]
        return zpad(encode_int(fdata['prefix']), 4) + \
            encode_abi(fdata['encode_types'], args)

    def decode(self, name, data):
        fdata = self.function_data[name]
        if fdata['is_unknown_type']:
            o = [utils.to_signed(utils.big_endian_to_int(data[i:i+32]))
                 for i in range(0, len(data), 32)]
            return [0 if not o else o[0] if len(o) == 1 else o]
        return decode_abi(fdata['decode_types'], data)

    def is_unknown_type(self, name):
        return self.function_data[name]["is_unknown_type"]


is_numeric = lambda x: isinstance(x, (int, long))
is_string = lambda x: isinstance(x, (str, unicode))


# Decode an integer
def decint(n):
    if is_numeric(n) and n < 2**256 and n > -2**255:
        return n
    elif is_numeric(n):
        raise Exception("Number out of range: %r" % n)
    elif is_string(n) and len(n) == 40:
        return big_endian_to_int(n.decode('hex'))
    elif is_string(n) and len(n) <= 32:
        return big_endian_to_int(n)
    elif is_string(n) and len(n) > 32:
        raise Exception("String too long: %r" % n)
    elif n is True:
        return 1
    elif n is False or n is None:
        return 0
    else:
        raise Exception("Cannot encode integer: %r" % n)


# Encodes a base type
def encode_single(arg, base, sub):
    normal_args, len_args, var_args = '', '', ''
    # Unsigned integers: uint<sz>
    if base == 'uint':
        sub = int(sub)
        i = decint(arg)
        assert 0 <= i < 2**sub, "Value out of bounds: %r" % arg
        normal_args = zpad(encode_int(i), sub // 8)
    # Signed integers: int<sz>
    elif base == 'int':
        sub = int(sub)
        i = decint(arg)
        assert -2**(sub-1) <= i < 2**(sub-1), "Value out of bounds: %r" % arg
        normal_args = zpad(encode_int(i % 2**sub), sub // 8)
    # Unsigned reals: ureal<high>x<low>
    elif base == 'ureal':
        high, low = [int(x) for x in sub.split('x')]
        assert 0 <= arg < 2**high, "Value out of bounds: %r" % arg
        normal_args = zpad(encode_int(arg * 2**low), (high + low) // 8)
    # Signed reals: real<high>x<low>
    elif base == 'real':
        high, low = [int(x) for x in sub.split('x')]
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
    # Only outermost array can be var-sized
    for a in arrlist[:-1]:
        assert len(a) > 2, "Inner arrays must have fixed size"
    # Check validity of string type
    if base == 'string':
        assert re.match('^[0-9]*$', sub), \
            "String type must have no suffix or numerical suffix"
        assert len(sub) or len(arrlist) == 0, \
            "Cannot have an array of var-sized strings"
    # Check validity of integer type
    elif base == 'uint' or base == 'int':
        assert re.match('^[0-9]+$', sub), \
            "Integer type must have numerical suffix"
        assert 8 <= int(sub) <= 256, \
            "Integer size out of bounds"
        assert int(sub) % 8 == 0, \
            "Integer size must be multiple of 8"
    # Check validity of real type
    elif base == 'ureal' or base == 'real':
        assert re.match('^[0-9]+x[0-9]+$', sub), \
            "Real type must have suffix of form <high>x<low>, eg. 128x128"
        high, low = [int(x) for x in sub.split('x')]
        assert 8 <= (high + low) <= 256, \
            "Real size out of bounds (max 32 bytes)"
        assert high % 8 == 0 and low % 8 == 0, \
            "Real high/low sizes must be multiples of 8"
    # Check validity of hash type
    elif base == 'hash':
        assert re.match('^[0-9]+$', sub), \
            "Hash type must have numerical suffix"
    # Check validity of address type
    elif base == 'address':
        assert sub == '', "Address cannot have suffix"
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
def encode_abi(types, args):
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
    return len_args + normal_args + var_args


def is_varsized(base, sub, arrlist):
    return (len(arrlist) and arrlist[-1] == '[]') or (base == 'string' and sub == '')


def getlen(base, sub, arrlist):
    if base == 'address':
        sz = 20
    elif base == 'string':
        sz = int(sub) if len(sub) else 1
    elif base == 'uint' or base == 'int' or base == 'hash':
        sz = int(sub) // 8
    elif base == 'ureal' or base == 'real':
        high, low = [int(x) for x in sub.split('x')]
        sz = int(high) // 8 + int(low) // 8
    for a in arrlist:
        if len(a) > 2:
            sz *= int(a[1:-1])
    return sz


def decode_single(data, base, sub):
    if base == 'address':
        return data.encode('hex')
    elif base == 'string' or base == 'hash':
        return data
    elif base == 'uint':
        return big_endian_to_int(data)
    elif base == 'int':
        o = big_endian_to_int(data)
        return (o - 2**int(sub)) if o >= 2**(int(sub)-1) else o
    elif base == 'ureal':
        high, low = [int(x) for x in sub.split('x')]
        return big_endian_to_int(data) * 1.0 / 2**low
    elif base == 'real':
        high, low = [int(x) for x in sub.split('x')]
        return (big_endian_to_int(data) * 1.0 / 2**low) % 2**high


def decode_any(data, base, sub, arrlist):
    if not len(arrlist):
        return decode_single(data, base, sub)
    sz = getlen(base, sub, arrlist[:-1])
    o = []
    for i in range(0, len(data), sz):
        o.append(decode_any(data[i: i+sz], base, sub, arrlist[:-1]))
    return o


def decode_abi(types, data):
    # List of processed types
    processed_types = [process_type(typ) for typ in types]
    # List of { 1 if variable-sized else 0 }
    is_varsized_bools = [1 if is_varsized(*t) else 0 for t in processed_types]
    # List of lengths (item lengths if variable-sized)
    lengths = [getlen(*t) for t in processed_types]
    # Portion of data corresponding to lengths
    lenl = sum(is_varsized_bools) * 32
    len_args = data[:lenl]
    # Total length of data dedicated to constant-sized types
    constl = sum([(1 - v) * l for v, l in zip(is_varsized_bools, lengths)])
    # Portion of data corresponding to normal args
    normal_args = data[lenl: lenl + constl]
    # Not enough data for static-length arguments?
    if len(data) < lenl + constl:
        raise Exception("ABI decode failed: not enough data")
    # Portion of data corresponding to variable-sized types
    var_args = data[lenl + constl:]
    lenpos, normalpos, varpos = 0, 0, 0
    o = []
    for t, v, l in zip(processed_types, is_varsized_bools, lengths):
        if v:
            L = l * big_endian_to_int(len_args[lenpos: lenpos + 32])
            lenpos += 32
            data = var_args[varpos: varpos + L]
            varpos += L
            if varpos > len(var_args):
                raise Exception("ABI decode failed: not enough data")
            o.append(decode_any(data, *t))
        else:
            data = normal_args[normalpos: normalpos + l]
            normalpos += l
            o.append(decode_any(data, *t))
    return o
