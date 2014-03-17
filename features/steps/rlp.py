from behave import *
from utils import to_big_endian_binary


@when(u'encoded in RLP')
def step_impl(context):
    import rlp
    dsts = [rlp.encode(src) for src in context.srcs]
    context.pairs = zip(context.srcs, dsts)


@given(u'the byte is in [0x00, 0x7f] range')
def step_impl(context):
    context.srcs = [chr(0x00), chr(0x71), chr(0x7f)]


@then(u'the byte is its own RLP encoding')
def step_impl(context):
    import rlp
    for src, dst in context.pairs:
        assert dst == src


@given(u'a single byte is not in [0x00, 0x7f] range')
def step_impl(context):
    context.srcs = [
        chr(0x80),
        chr(0x81),
        chr(0xFF)
    ]


@given(u'a 2-55 bytes long string')
def step_impl(context):
    context.srcs = [
        'abcd',
        'a' * 55
    ]


@given(u'a blank string')
def step_impl(context):
    context.srcs = [
        ''
    ]


@then(u'the first byte is 0x80 plus the length of the string')
def step_impl(context):
    for src, dst in context.pairs:
        assert dst[0] == chr(0x80 + len(src))


@then(u'followed by the string')
def step_impl(context):
    for src, dst in context.pairs:
        assert dst[1:] == src


@given(u'a string longer than 55')
def step_impl(context):
    context.srcs = [
        'a' * 56,
        'a' * 1024
    ]


@then(u'the first byte is 0xb7 plus the lenth of the lenth')
def step_impl(context):
    for src, dst in context.pairs:
        length_bin = to_big_endian_binary(len(src))
        assert dst[0] == chr(0xb7 + len(length_bin))


@then(u'following bytes are the payload string length')
def step_impl(context):
    for src, dst in context.pairs:
        length_bin = to_big_endian_binary(len(src))
        assert dst[1:1+len(length_bin)] == length_bin


@then(u'following bytes are the payload string itself')
def step_impl(context):
    for src, dst in context.pairs:
        length_bin = to_big_endian_binary(len(src))
        assert dst[1+len(length_bin):] == src


@given(u'a list with length of [0-55]')
def step_impl(context):
    context.srcs = [
        [],
        ['a', 'b', 'c'],
        ['a'] * 55,
    ]


@then(u'the first byte is 0xc0 plus the length of the list')
def step_impl(context):
    import rlp
    for src, dst in context.pairs:
        total_payload_length = sum(len(rlp.encode(x)) for x in src)
        assert dst[0] == chr(0xc0 + total_payload_length)


@then(u'following bytes are concatenation of the RLP encodings of the items')
def step_impl(context):
    import rlp
    for src, dst in context.pairs:
        assert dst[1:] == ''.join(rlp.encode(x) for x in src)
