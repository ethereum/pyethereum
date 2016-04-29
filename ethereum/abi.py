import sys
import re
import yaml  # use yaml instead of json to get non unicode (works with ascii only data)
from ethereum import utils
from rlp.utils import decode_hex, encode_hex
from ethereum.utils import encode_int, zpad, big_endian_to_int, is_numeric, is_string, ceil32
from ethereum.utils import isnumeric, TT256, TT255
import ast


def json_decode(x):
    return yaml.safe_load(x)


def _canonical_name(x):
    if x.startswith('int['):
        return 'uint256' + x[3:]
    elif x == 'int':
        return 'uint256'
    elif x.startswith('real['):
        return 'real128x128' + x[4:]
    elif x == 'real':
        return 'real128x128'
    return x


def method_id(name, encode_types):
    sig = name + '(' + ','.join(_canonical_name(x) for x in encode_types) + ')'
    return big_endian_to_int(utils.sha3(sig)[:4])


def event_id(name, encode_types):
    sig = name + '(' + ','.join(_canonical_name(x) for x in encode_types) + ')'
    return big_endian_to_int(utils.sha3(sig))


class ContractTranslator():

    def __init__(self, full_signature):
        self.function_data = {}
        self.event_data = {}
        v = vars(self)
        if is_string(full_signature):
            full_signature = json_decode(full_signature)
        for sig_item in full_signature:
            if sig_item['type'] == 'constructor':
                continue
            encode_types = [f['type'] for f in sig_item['inputs']]
            signature = [(f['type'], f['name']) for f in sig_item['inputs']]
            name = sig_item['name']
            if '(' in name:
                name = name[:name.find('(')]
            if name in v:
                i = 2
                while name + utils.to_string(i) in v:
                    i += 1
                name += utils.to_string(i)
                sys.stderr.write("Warning: multiple methods with the same "
                                 " name. Use %s to call %s with types %r"
                                 % (name, sig_item['name'], encode_types))
            if sig_item['type'] == 'function':
                decode_types = [f['type'] for f in sig_item['outputs']]
                is_unknown_type = len(sig_item['outputs']) and \
                    sig_item['outputs'][0]['name'] == 'unknown_out'
                self.function_data[name] = {
                    "prefix": method_id(name, encode_types),
                    "encode_types": encode_types,
                    "decode_types": decode_types,
                    "is_unknown_type": is_unknown_type,
                    "is_constant": sig_item.get('constant', False),
                    "signature": signature
                }
            elif sig_item['type'] == 'event':
                indexed = [f['indexed'] for f in sig_item['inputs']]
                names = [f['name'] for f in sig_item['inputs']]
                self.event_data[event_id(name, encode_types)] = {
                    "types": encode_types,
                    "name": name,
                    "names": names,
                    "indexed": indexed,
                    "anonymous": sig_item.get('anonymous', False)
                }

    def encode(self, name, args):
        fdata = self.function_data[name]
        o = zpad(encode_int(fdata['prefix']), 4) + \
            encode_abi(fdata['encode_types'], args)
        return o

    def decode(self, name, data):
        # print 'out', utils.encode_hex(data)
        fdata = self.function_data[name]
        if fdata['is_unknown_type']:
            o = [utils.to_signed(utils.big_endian_to_int(data[i:i + 32]))
                 for i in range(0, len(data), 32)]
            return [0 if not o else o[0] if len(o) == 1 else o]
        o = decode_abi(fdata['decode_types'], data)
        return o

    def is_unknown_type(self, name):
        return self.function_data[name]["is_unknown_type"]

    def listen(self, log, noprint=True):
        if not len(log.topics) or log.topics[0] not in self.event_data:
            return
        types = self.event_data[log.topics[0]]['types']
        name = self.event_data[log.topics[0]]['name']
        names = self.event_data[log.topics[0]]['names']
        indexed = self.event_data[log.topics[0]]['indexed']
        indexed_types = [types[i] for i in range(len(types))
                         if indexed[i]]
        unindexed_types = [types[i] for i in range(len(types))
                           if not indexed[i]]
        # print('listen', log.data.encode('hex'), log.topics)
        deserialized_args = decode_abi(unindexed_types, log.data)
        o = {}
        c1, c2 = 0, 0
        for i in range(len(names)):
            if indexed[i]:
                topic_bytes = utils.zpad(utils.encode_int(log.topics[c1 + 1]), 32)
                o[names[i]] = decode_single(process_type(indexed_types[c1]),
                                            topic_bytes)
                c1 += 1
            else:
                o[names[i]] = deserialized_args[c2]
                c2 += 1
        o["_event_type"] = utils.to_string(name)
        if not noprint:
            print(o)
        return o


def split32(s):
    o = []
    for i in range(0, len(s), 32):
        o.append(s[i:i + 32])
    return o


class EncodingError(Exception):
    pass


class ValueOutOfBounds(EncodingError):
    pass


# Decode an unsigned/signed integer
def decint(n, signed=False):
    if isinstance(n, str):
        n = utils.to_string(n)

    if is_numeric(n):
        min, max = (-TT255,TT255-1) if signed else (0,TT256-1)
        if n > max or n < min:
            raise EncodingError("Number out of range: %r" % n)
        return n
    elif is_string(n):
        if len(n) == 40:
            n = decode_hex(n)
        if len(n) > 32:
            raise EncodingError("String too long: %r" % n)

        i = big_endian_to_int(n)
        return (i - TT256) if signed and i >= TT255 else i
    elif n is True:
        return 1
    elif n is False or n is None:
        return 0
    else:
        raise EncodingError("Cannot encode integer: %r" % n)

# Encodes a base datum
def encode_single(typ, arg):
    base, sub, _ = typ
    # Unsigned integers: uint<sz>
    if base == 'uint':
        sub = int(sub)
        i = decint(arg, False)

        if not 0 <= i < 2**sub:
            raise ValueOutOfBounds(repr(arg))
        return zpad(encode_int(i), 32)
    # bool: int<sz>
    elif base == 'bool':
        assert isinstance(arg, bool)
        return zpad(encode_int(int(arg)), 32)
    # Signed integers: int<sz>
    elif base == 'int':
        sub = int(sub)
        i = decint(arg, True)
        if not -2**(sub - 1) <= i < 2**(sub - 1):
            raise ValueOutOfBounds(repr(arg))
        return zpad(encode_int(i % 2**sub), 32)
    # Unsigned reals: ureal<high>x<low>
    elif base == 'ureal':
        high, low = [int(x) for x in sub.split('x')]
        if not 0 <= arg < 2**high:
            raise ValueOutOfBounds(repr(arg))
        return zpad(encode_int(int(arg * 2**low)), 32)
    # Signed reals: real<high>x<low>
    elif base == 'real':
        high, low = [int(x) for x in sub.split('x')]
        if not -2**(high - 1) <= arg < 2**(high - 1):
            raise ValueOutOfBounds(repr(arg))
        i = int(arg * 2**low)
        return zpad(encode_int(i % 2**(high+low)), 32)
    # Strings
    elif base == 'string' or base == 'bytes':
        if not is_string(arg):
            raise EncodingError("Expecting string: %r" % arg)
        # Fixed length: string<sz>
        if len(sub):
            assert int(sub) <= 32
            assert len(arg) <= int(sub)
            return arg + b'\x00' * (32 - len(arg))
        # Variable length: string
        else:
            return zpad(encode_int(len(arg)), 32) + \
                arg + \
                b'\x00' * (utils.ceil32(len(arg)) - len(arg))
    # Hashes: hash<sz>
    elif base == 'hash':
        if not (int(sub) and int(sub) <= 32):
            raise EncodingError("too long: %r" % arg)
        if isnumeric(arg):
            return zpad(encode_int(arg), 32)
        elif len(arg) == int(sub):
            return zpad(arg, 32)
        elif len(arg) == int(sub) * 2:
            return zpad(decode_hex(arg), 32)
        else:
            raise EncodingError("Could not parse hash: %r" % arg)
    # Addresses: address (== hash160)
    elif base == 'address':
        assert sub == ''
        if isnumeric(arg):
            return zpad(encode_int(arg), 32)
        elif len(arg) == 20:
            return zpad(arg, 32)
        elif len(arg) == 40:
            return zpad(decode_hex(arg), 32)
        elif len(arg) == 42 and arg[:2] == '0x':
            return zpad(decode_hex(arg[2:]), 32)
        else:
            raise EncodingError("Could not parse address: %r" % arg)
    raise EncodingError("Unhandled type: %r %r" % (base, sub))


def process_type(typ):
    # Crazy reg expression to separate out base type component (eg. uint),
    # size (eg. 256, 128x128, none), array component (eg. [], [45], none)
    regexp = '([a-z]*)([0-9]*x?[0-9]*)((\[[0-9]*\])*)'
    base, sub, arr, _ = re.match(regexp, utils.to_string_for_regexp(typ)).groups()
    arrlist = re.findall('\[[0-9]*\]', arr)
    assert len(''.join(arrlist)) == len(arr), \
        "Unknown characters found in array declaration"
    # Check validity of string type
    if base == 'string' or base == 'bytes':
        assert re.match('^[0-9]*$', sub), \
            "String type must have no suffix or numerical suffix"
        assert not sub or int(sub) <= 32, \
            "Maximum 32 bytes for fixed-length str or bytes"
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
    return base, sub, [ast.literal_eval(x) for x in arrlist]


# Returns the static size of a type, or None if dynamic
def get_size(typ):
    base, sub, arrlist = typ
    if not len(arrlist):
        if base in ('string', 'bytes') and not sub:
            return None
        return 32
    if arrlist[-1] == []:
        return None
    o = get_size((base, sub, arrlist[:-1]))
    if o is None:
        return None
    return arrlist[-1][0] * o


lentyp = 'uint', 256, []


# Encodes a single value (static or dynamic)
def enc(typ, arg):
    base, sub, arrlist = typ
    sz = get_size(typ)
    # Encode dynamic-sized strings as <len(str)> + <str>
    if base in ('string', 'bytes') and not sub:
        assert isinstance(arg, (str, bytes, utils.unicode)), \
            "Expecting a string"
        return enc(lentyp, len(arg)) + \
            utils.to_string(arg) + \
            b'\x00' * (utils.ceil32(len(arg)) - len(arg))
    # Encode dynamic-sized lists via the head/tail mechanism described in
    # https://github.com/ethereum/wiki/wiki/Proposal-for-new-ABI-value-encoding
    elif sz is None:
        assert isinstance(arg, list), \
            "Expecting a list argument"
        subtyp = base, sub, arrlist[:-1]
        subsize = get_size(subtyp)
        myhead, mytail = b'', b''
        if arrlist[-1] == []:
            myhead += enc(lentyp, len(arg))
        else:
            assert len(arg) == arrlist[-1][0], \
                "Wrong array size: found %d, expecting %d" % \
                (len(arg), arrlist[-1][0])
        for i in range(len(arg)):
            if subsize is None:
                myhead += enc(lentyp, 32 * len(arg) + len(mytail))
                mytail += enc(subtyp, arg[i])
            else:
                myhead += enc(subtyp, arg[i])
        return myhead + mytail
    # Encode static-sized lists via sequential packing
    else:
        if arrlist == []:
            return utils.to_string(encode_single(typ, arg))
        else:
            subtyp = base, sub, arrlist[:-1]
            o = b''
            for x in arg:
                o += enc(subtyp, x)
            return o


# Encodes multiple arguments using the head/tail mechanism
def encode_abi(types, args):
    headsize = 0
    proctypes = [process_type(typ) for typ in types]
    sizes = [get_size(typ) for typ in proctypes]
    for i, arg in enumerate(args):
        if sizes[i] is None:
            headsize += 32
        else:
            headsize += sizes[i]
    myhead, mytail = b'', b''
    for i, arg in enumerate(args):
        if sizes[i] is None:
            myhead += enc(lentyp, headsize + len(mytail))
            mytail += enc(proctypes[i], args[i])
        else:
            myhead += enc(proctypes[i], args[i])
    return myhead + mytail


# Decodes a single base datum
def decode_single(typ, data):
    base, sub, _ = typ
    if base == 'address':
        return encode_hex(data[12:])
    elif base == 'hash':
        return data[32-int(sub):]
    elif base == 'string' or base == 'bytes':
        if len(sub):
            return data[:int(sub)]
        else:
            l = big_endian_to_int(data[0:32])
            return data[32:][:l]
    elif base == 'uint':
        return big_endian_to_int(data)
    elif base == 'int':
        o = big_endian_to_int(data)
        return (o - 2**int(sub)) if o >= 2**(int(sub) - 1) else o
    elif base == 'ureal':
        high, low = [int(x) for x in sub.split('x')]
        return big_endian_to_int(data) * 1.0 / 2**low
    elif base == 'real':
        high, low = [int(x) for x in sub.split('x')]
        o = big_endian_to_int(data)
        i = (o - 2**(high+low)) if o >= 2**(high+low-1) else o
        return (i * 1.0 / 2**low)
    elif base == 'bool':
        return bool(int(data.encode('hex'), 16))


# Decodes multiple arguments using the head/tail mechanism
def decode_abi(types, data):
    # Process types
    proctypes = [process_type(typ) for typ in types]
    # Get sizes of everything
    sizes = [get_size(typ) for typ in proctypes]
    # Initialize array of outputs
    outs = [None] * len(types)
    # Initialize array of start positions
    start_positions = [None] * len(types) + [len(data)]
    # If a type is static, grab the data directly, otherwise record
    # its start position
    pos = 0
    for i, typ in enumerate(types):
        if sizes[i] is None:
            start_positions[i] = big_endian_to_int(data[pos:pos + 32])
            j = i - 1
            while j >= 0 and start_positions[j] is None:
                start_positions[j] = start_positions[i]
                j -= 1
            pos += 32
        else:
            outs[i] = data[pos:pos + sizes[i]]
            pos += sizes[i]
    # We add a start position equal to the length of the entire data
    # for convenience.
    j = len(types) - 1
    while j >= 0 and start_positions[j] is None:
        start_positions[j] = start_positions[len(types)]
        j -= 1
    assert pos <= len(data), "Not enough data for head"
    # Grab the data for tail arguments using the start positions
    # calculated above
    for i, typ in enumerate(types):
        if sizes[i] is None:
            offset = start_positions[i]
            next_offset = start_positions[i + 1]
            outs[i] = data[offset:next_offset]
    # Recursively decode them all
    return [dec(proctypes[i], outs[i]) for i in range(len(outs))]


# Decode a single value (static or dynamic)
def dec(typ, arg):
    base, sub, arrlist = typ
    sz = get_size(typ)
    # Dynamic-sized strings are encoded as <len(str)> + <str>
    if base in ('string', 'bytes') and not sub:
        L = big_endian_to_int(arg[:32])
        assert len(arg[32:]) == ceil32(L), "Wrong data size for string/bytes object"
        return arg[32:][:L]
    # Dynamic-sized arrays
    elif sz is None:
        L = big_endian_to_int(arg[:32])
        subtyp = base, sub, arrlist[:-1]
        subsize = get_size(subtyp)
        # If children are dynamic, use the head/tail mechanism. Fortunately,
        # here the code is simpler since we do not have to worry about
        # mixed dynamic and static children, as we do in the top-level multi-arg
        # case
        if subsize is None:
            assert len(arg) >= 32 + 32 * L, "Not enough data for head"
            start_positions = [big_endian_to_int(arg[32 + 32 * i: 64 + 32 * i])
                               for i in range(L)] + [len(arg)]
            outs = [arg[start_positions[i]: start_positions[i + 1]]
                    for i in range(L)]
            return [dec(subtyp, out) for out in outs]
        # If children are static, then grab the data slice for each one and
        # sequentially decode them manually
        else:
            return [dec(subtyp, arg[32 + subsize * i: 32 + subsize * (i + 1)])
                    for i in range(L)]
    # Static-sized arrays: decode piece-by-piece
    elif len(arrlist):
        L = arrlist[-1][0]
        subtyp = base, sub, arrlist[:-1]
        subsize = get_size(subtyp)
        return [dec(subtyp, arg[subsize * i:subsize * (i + 1)])
                for i in range(L)]
    else:
        return decode_single(typ, arg)
