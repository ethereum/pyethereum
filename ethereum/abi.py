# -*- coding: utf8 -*-
from __future__ import print_function

import ast
import re
import warnings

import yaml  # use yaml instead of json to get non unicode (works with ascii only data)
from rlp.utils import decode_hex, encode_hex

from ethereum import utils
from ethereum.utils import (
    big_endian_to_int, ceil32, int_to_big_endian, encode_int, is_numeric, isnumeric, is_string,
    rzpad, TT255, TT256, zpad,
)

# The number of bytes is encoded as a uint256
# Type used to encode a string/bytes length
INT256 = 'uint', '256', []
lentyp = INT256  # pylint: disable=invalid-name


class EncodingError(Exception):
    pass


class ValueOutOfBounds(EncodingError):
    pass


def json_decode(data):
    return yaml.safe_load(data)


def split32(data):
    """ Split data into pieces of 32 bytes. """
    all_pieces = []

    for position in range(0, len(data), 32):
        piece = data[position:position + 32]
        all_pieces.append(piece)

    return all_pieces


def _canonical_type(name):  # pylint: disable=too-many-return-statements
    """ Replace aliases to the corresponding type to compute the ids. """

    if name == 'int':
        return 'int256'

    if name == 'uint':
        return 'uint256'

    if name == 'fixed':
        return 'fixed128x128'

    if name == 'ufixed':
        return 'ufixed128x128'

    if name.startswith('int['):
        return 'int256' + name[3:]

    if name.startswith('uint['):
        return 'uint256' + name[4:]

    if name.startswith('fixed['):
        return 'fixed128x128' + name[5:]

    if name.startswith('ufixed['):
        return 'ufixed128x128' + name[6:]

    return name


def normalize_name(name):
    """ Return normalized event/function name. """
    if '(' in name:
        return name[:name.find('(')]

    return name


def method_id(name, encode_types):
    """ Return the unique method id.

    The signature is defined as the canonical expression of the basic
    prototype, i.e. the function name with the parenthesised list of parameter
    types. Parameter types are split by a single comma - no spaces are used.

    The method id is defined as the first four bytes (left, high-order in
    big-endian) of the Keccak (SHA-3) hash of the signature of the function.
    """
    function_types = [
        _canonical_type(type_)
        for type_ in encode_types
    ]

    function_signature = '{function_name}({canonical_types})'.format(
        function_name=name,
        canonical_types=','.join(function_types),
    )

    function_keccak = utils.sha3(function_signature)
    first_bytes = function_keccak[:4]

    return big_endian_to_int(first_bytes)


def event_id(name, encode_types):
    """ Return the event id.

    Defined as:

        `keccak(EVENT_NAME+"("+EVENT_ARGS.map(canonical_type_of).join(",")+")")`

    Where `canonical_type_of` is a function that simply returns the canonical
    type of a given argument, e.g. for uint indexed foo, it would return
    uint256). Note the lack of spaces.
    """

    event_types = [
        _canonical_type(type_)
        for type_ in encode_types
    ]

    event_signature = '{event_name}({canonical_types})'.format(
        event_name=name,
        canonical_types=','.join(event_types),
    )

    return big_endian_to_int(utils.sha3(event_signature))


def decint(n, signed=False):  # pylint: disable=invalid-name,too-many-branches
    ''' Decode an unsigned/signed integer. '''

    if isinstance(n, str):
        n = utils.to_string(n)

    if n is True:
        return 1

    if n is False:
        return 0

    if n is None:
        return 0

    if is_numeric(n):
        if signed:
            if not -TT255 <= n <= TT255 - 1:
                raise EncodingError('Number out of range: %r' % n)
        else:
            if not 0 <= n <= TT256 - 1:
                raise EncodingError('Number out of range: %r' % n)

        return n

    if is_string(n):
        if len(n) > 32:
            raise EncodingError('String too long: %r' % n)

        if len(n) == 40:
            int_bigendian = decode_hex(n)
        else:
            int_bigendian = n  # pylint: disable=redefined-variable-type

        result = big_endian_to_int(int_bigendian)
        if signed:
            if result >= TT255:
                result -= TT256

            if not -TT255 <= result <= TT255 - 1:
                raise EncodingError('Number out of range: %r' % n)
        else:
            if not 0 <= result <= TT256 - 1:
                raise EncodingError('Number out of range: %r' % n)

        return result

    raise EncodingError('Cannot decode integer: %r' % n)


def encode_single(typ, arg):  # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements,too-many-locals
    ''' Encode `arg` as `typ`.

    `arg` will be encoded in a best effort manner, were necessary the function
    will try to correctly define the underlying binary representation (ie.
    decoding a hex-encoded address/hash).

    Args:
        typ (Tuple[(str, int, list)]): A 3-tuple defining the `arg` type.

            The first element defines the type name.
            The second element defines the type length in bits.
            The third element defines if it's an array type.

            Together the first and second defines the elementary type, the third
            element must be present but is ignored.

            Valid type names are:
                - uint
                - int
                - bool
                - ufixed
                - fixed
                - string
                - bytes
                - hash
                - address

        arg (object): The object to be encoded, it must be a python object
            compatible with the `typ`.

    Raises:
        ValueError: when an invalid `typ` is supplied.
        ValueOutOfBounds: when `arg` cannot be encoded as `typ` because of the
            binary contraints.

    Note:
        This function don't work with array types, for that use the `enc`
        function.
    '''
    base, sub, _ = typ

    if base == 'uint':
        sub = int(sub)

        if not (0 < sub <= 256 and sub % 8 == 0):
            raise ValueError('invalid unsigned integer bit length {}'.format(sub))

        try:
            i = decint(arg, signed=False)
        except EncodingError:
            # arg is larger than 2**256
            raise ValueOutOfBounds(repr(arg))

        if not 0 <= i < 2 ** sub:
            raise ValueOutOfBounds(repr(arg))

        value_encoded = int_to_big_endian(i)
        return zpad(value_encoded, 32)

    if base == 'int':
        sub = int(sub)
        bits = sub - 1

        if not (0 < sub <= 256 and sub % 8 == 0):
            raise ValueError('invalid integer bit length {}'.format(sub))

        try:
            i = decint(arg, signed=True)
        except EncodingError:
            # arg is larger than 2**255
            raise ValueOutOfBounds(repr(arg))

        if not -2 ** bits <= i < 2 ** bits:
            raise ValueOutOfBounds(repr(arg))

        value = i % 2 ** sub  # convert negative to "equivalent" positive
        value_encoded = int_to_big_endian(value)
        return zpad(value_encoded, 32)

    if base == 'bool':
        if arg is True:
            value_encoded = int_to_big_endian(1)
        elif arg is False:
            value_encoded = int_to_big_endian(0)
        else:
            raise ValueError('%r is not bool' % arg)

        return zpad(value_encoded, 32)

    if base == 'ufixed':
        sub = str(sub)  # pylint: disable=redefined-variable-type

        high_str, low_str = sub.split('x')
        high = int(high_str)
        low = int(low_str)

        if not (0 < high + low <= 256 and high % 8 == 0 and low % 8 == 0):
            raise ValueError('invalid unsigned fixed length {}'.format(sub))

        if not 0 <= arg < 2 ** high:
            raise ValueOutOfBounds(repr(arg))

        float_point = arg * 2 ** low
        fixed_point = int(float_point)
        return zpad(int_to_big_endian(fixed_point), 32)

    if base == 'fixed':
        sub = str(sub)  # pylint: disable=redefined-variable-type

        high_str, low_str = sub.split('x')
        high = int(high_str)
        low = int(low_str)
        bits = high - 1

        if not (0 < high + low <= 256 and high % 8 == 0 and low % 8 == 0):
            raise ValueError('invalid unsigned fixed length {}'.format(sub))

        if not -2 ** bits <= arg < 2 ** bits:
            raise ValueOutOfBounds(repr(arg))

        float_point = arg * 2 ** low
        fixed_point = int(float_point)
        value = fixed_point % 2 ** 256
        return zpad(int_to_big_endian(value), 32)

    if base == 'string':
        if isinstance(arg, utils.unicode):
            arg = arg.encode('utf8')
        else:
            try:
                arg.decode('utf8')
            except UnicodeDecodeError:
                raise ValueError('string must be utf8 encoded')

        if len(sub):  # fixed length
            if not 0 <= len(arg) <= int(sub):
                raise ValueError('invalid string length {}'.format(sub))

            if not 0 <= int(sub) <= 32:
                raise ValueError('invalid string length {}'.format(sub))

            return rzpad(arg, 32)

        if not 0 <= len(arg) < TT256:
            raise Exception('Integer invalid or out of range: %r' % arg)

        length_encoded = zpad(int_to_big_endian(len(arg)), 32)
        value_encoded = rzpad(arg, utils.ceil32(len(arg)))

        return length_encoded + value_encoded

    if base == 'bytes':
        if not is_string(arg):
            raise EncodingError('Expecting string: %r' % arg)

        arg = utils.to_string(arg)  # py2: force unicode into str

        if len(sub):  # fixed length
            if not 0 <= len(arg) <= int(sub):
                raise ValueError('string must be utf8 encoded')

            if not 0 <= int(sub) <= 32:
                raise ValueError('string must be utf8 encoded')

            return rzpad(arg, 32)

        if not 0 <= len(arg) < TT256:
            raise Exception('Integer invalid or out of range: %r' % arg)

        length_encoded = zpad(int_to_big_endian(len(arg)), 32)
        value_encoded = rzpad(arg, utils.ceil32(len(arg)))

        return length_encoded + value_encoded

    if base == 'hash':
        if not (int(sub) and int(sub) <= 32):
            raise EncodingError('too long: %r' % arg)

        if isnumeric(arg):
            return zpad(encode_int(arg), 32)

        if len(arg) == int(sub):
            return zpad(arg, 32)

        if len(arg) == int(sub) * 2:
            return zpad(decode_hex(arg), 32)

        raise EncodingError('Could not parse hash: %r' % arg)

    if base == 'address':
        assert sub == ''

        if isnumeric(arg):
            return zpad(encode_int(arg), 32)

        if len(arg) == 20:
            return zpad(arg, 32)

        if len(arg) == 40:
            return zpad(decode_hex(arg), 32)

        if len(arg) == 42 and arg[:2] == '0x':
            return zpad(decode_hex(arg[2:]), 32)

        raise EncodingError('Could not parse address: %r' % arg)
    raise EncodingError('Unhandled type: %r %r' % (base, sub))


class ContractTranslator(object):

    def __init__(self, contract_interface):
        if is_string(contract_interface):
            contract_interface = json_decode(contract_interface)

        self.fallback_data = None
        self.constructor_data = None
        self.function_data = {}
        self.event_data = {}

        for description in contract_interface:
            entry_type = description.get('type', 'function')
            encode_types = []
            signature = []

            # If it's a function/constructor/event
            if entry_type != 'fallback' and 'inputs' in description:
                encode_types = [
                    element['type']
                    for element in description.get('inputs')
                ]

                signature = [
                    (element['type'], element['name'])
                    for element in description.get('inputs')
                ]

            if entry_type == 'function':
                normalized_name = normalize_name(description['name'])

                decode_types = [
                    element['type']
                    for element in description['outputs']
                ]

                self.function_data[normalized_name] = {
                    'prefix': method_id(normalized_name, encode_types),
                    'encode_types': encode_types,
                    'decode_types': decode_types,
                    'is_constant': description.get('constant', False),
                    'signature': signature,
                    'payable': description.get('payable', False),
                }

            elif entry_type == 'event':
                normalized_name = normalize_name(description['name'])

                indexed = [
                    element['indexed']
                    for element in description['inputs']
                ]
                names = [
                    element['name']
                    for element in description['inputs']
                ]
                # event_id == topics[0]
                self.event_data[event_id(normalized_name, encode_types)] = {
                    'types': encode_types,
                    'name': normalized_name,
                    'names': names,
                    'indexed': indexed,
                    'anonymous': description.get('anonymous', False),
                }

            elif entry_type == 'constructor':
                if self.constructor_data is not None:
                    raise ValueError('Only one constructor is supported.')

                self.constructor_data = {
                    'encode_types': encode_types,
                    'signature': signature,
                }

            elif entry_type == 'fallback':
                if self.fallback_data is not None:
                    raise ValueError('Only one fallback function is supported.')
                self.fallback_data = {'payable': description['payable']}

            else:
                raise ValueError('Unknown type {}'.format(description['type']))

    def encode(self, function_name, args):
        warnings.warn('encode is deprecated, please use encode_function_call', DeprecationWarning)
        return self.encode_function_call(function_name, args)

    def decode(self, function_name, data):
        warnings.warn('decode is deprecated, please use decode_function_result', DeprecationWarning)
        return self.decode_function_result(function_name, data)

    def encode_function_call(self, function_name, args):
        """ Return the encoded function call.

        Args:
            function_name (str): One of the existing functions described in the
                contract interface.
            args (List[object]): The function arguments that wll be encoded and
                used in the contract execution in the vm.

        Return:
            bin: The encoded function name and arguments so that it can be used
                 with the evm to execute a funcion call, the binary string follows
                 the Ethereum Contract ABI.
        """
        if function_name not in self.function_data:
            raise ValueError('Unkown function {}'.format(function_name))

        description = self.function_data[function_name]

        function_selector = zpad(encode_int(description['prefix']), 4)
        arguments = encode_abi(description['encode_types'], args)

        return function_selector + arguments

    def decode_function_result(self, function_name, data):
        """ Return the function call result decoded.

        Args:
            function_name (str): One of the existing functions described in the
                contract interface.
            data (bin): The encoded result from calling `function_name`.

        Return:
            List[object]: The values returned by the call to `function_name`.
        """
        description = self.function_data[function_name]
        arguments = decode_abi(description['decode_types'], data)
        return arguments

    def encode_constructor_arguments(self, args):
        """ Return the encoded constructor call. """
        if self.constructor_data is None:
            raise ValueError("The contract interface didn't have a constructor")

        return encode_abi(self.constructor_data['encode_types'], args)

    def decode_event(self, log_topics, log_data):
        """ Return a dictionary representation the log.

        Note:
            This function won't work with anonymous events.

        Args:
            log_topics (List[bin]): The log's indexed arguments.
            log_data (bin): The encoded non-indexed arguments.
        """
        # https://github.com/ethereum/wiki/wiki/Ethereum-Contract-ABI#function-selector-and-argument-encoding

        # topics[0]: keccak(EVENT_NAME+"("+EVENT_ARGS.map(canonical_type_of).join(",")+")")
        # If the event is declared as anonymous the topics[0] is not generated;
        if not len(log_topics) or log_topics[0] not in self.event_data:
            raise ValueError('Unknown log type')

        event_id_ = log_topics[0]

        event = self.event_data[event_id_]

        # data: abi_serialise(EVENT_NON_INDEXED_ARGS)
        # EVENT_NON_INDEXED_ARGS is the series of EVENT_ARGS that are not
        # indexed, abi_serialise is the ABI serialisation function used for
        # returning a series of typed values from a function.
        unindexed_types = [
            type_
            for type_, indexed in zip(event['types'], event['indexed'])
            if not indexed
        ]
        unindexed_args = decode_abi(unindexed_types, log_data)

        # topics[n]: EVENT_INDEXED_ARGS[n - 1]
        # EVENT_INDEXED_ARGS is the series of EVENT_ARGS that are indexed
        indexed_count = 1  # skip topics[0]

        result = {}
        for name, type_, indexed in zip(event['names'], event['types'], event['indexed']):
            if indexed:
                topic_bytes = utils.zpad(
                    utils.encode_int(log_topics[indexed_count]),
                    32,
                )
                indexed_count += 1
                value = decode_single(process_type(type_), topic_bytes)
            else:
                value = unindexed_args.pop(0)

            result[name] = value
        result['_event_type'] = utils.to_string(event['name'])

        return result

    def listen(self, log, noprint=True):
        """
        Return a dictionary representation of the Log instance.

        Note:
            This function won't work with anonymous events.

        Args:
            log (processblock.Log): The Log instance that needs to be parsed.
            noprint (bool): Flag to turn off priting of the decoded log instance.
        """
        try:
            result = self.decode_event(log.topics, log.data)
        except ValueError:
            return  # api compatibility

        if not noprint:
            print(result)

        return result


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
    # Check validity of fixed type
    elif base == 'ufixed' or base == 'fixed':
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


# Encodes a single value (static or dynamic)
def enc(typ, arg):
    base, sub, arrlist = typ
    type_size = get_size(typ)

    if base in ('string', 'bytes') and not sub:
        return encode_single(typ, arg)

    # Encode dynamic-sized lists via the head/tail mechanism described in
    # https://github.com/ethereum/wiki/wiki/Proposal-for-new-ABI-value-encoding
    if type_size is None:
        assert isinstance(arg, list), \
            "Expecting a list argument"
        subtyp = base, sub, arrlist[:-1]
        subsize = get_size(subtyp)
        myhead, mytail = b'', b''
        if arrlist[-1] == []:
            myhead += enc(INT256, len(arg))
        else:
            assert len(arg) == arrlist[-1][0], \
                "Wrong array size: found %d, expecting %d" % \
                (len(arg), arrlist[-1][0])
        for i in range(len(arg)):
            if subsize is None:
                myhead += enc(INT256, 32 * len(arg) + len(mytail))
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
            myhead += enc(INT256, headsize + len(mytail))
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
        return data[32 - int(sub):]
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
        return (o - 2 ** int(sub)) if o >= 2 ** (int(sub) - 1) else o
    elif base == 'ufixed':
        high, low = [int(x) for x in sub.split('x')]
        return big_endian_to_int(data) * 1.0 // 2 ** low
    elif base == 'fixed':
        high, low = [int(x) for x in sub.split('x')]
        o = big_endian_to_int(data)
        i = (o - 2 ** (high + low)) if o >= 2 ** (high + low - 1) else o
        return (i * 1.0 // 2 ** low)
    elif base == 'bool':
        return bool(int(encode_hex(data), 16))


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
