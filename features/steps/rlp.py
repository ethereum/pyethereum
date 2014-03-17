from behave import *
from utils import to_big_endian_binary


@when('encoded in RLP')
def step_impl(ctx):
    import rlp
    dsts = [rlp.encode(src) for src in ctx.srcs]
    ctx.pairs = zip(ctx.srcs, dsts)


@given('the byte is in [0x00, 0x7f] range')
def step_impl(ctx):
    ctx.srcs = [chr(0x00), chr(0x71), chr(0x7f)]


@then('the byte is its own RLP encoding')
def step_impl(ctx):
    import rlp
    for src, dst in ctx.pairs:
        assert dst == src


@given('a single byte is not in [0x00, 0x7f] range')
def step_impl(ctx):
    ctx.srcs = [
        chr(0x80),
        chr(0x81),
        chr(0xFF)
    ]


@given('a 2-55 bytes long string')
def step_impl(ctx):
    ctx.srcs = [
        'abcd',
        'a' * 55
    ]


@given('a blank string')
def step_impl(ctx):
    ctx.srcs = [
        ''
    ]


@then('the first byte is 0x80 plus the length of the string')
def step_impl(ctx):
    for src, dst in ctx.pairs:
        assert dst[0] == chr(0x80 + len(src))


@then('followed by the string')
def step_impl(ctx):
    for src, dst in ctx.pairs:
        assert dst[1:] == src


@given('a string longer than 55')
def step_impl(ctx):
    ctx.srcs = [
        'a' * 56,
        'a' * 1024
    ]
    pass


@then('the first byte is 0xb7 plus the lenth of the lenth')
def step_impl(ctx):
    for src, dst in ctx.pairs:
        length_bin = to_big_endian_binary(len(src))
        assert dst[0] == chr(0xb7 + len(length_bin))


@then('following bytes are the payload string length')
def step_impl(ctx):
    for src, dst in ctx.pairs:
        length_bin = to_big_endian_binary(len(src))
        assert dst[1:1+len(length_bin)] == length_bin


@then('following bytes are the payload string itself')
def step_impl(ctx):
    for src, dst in ctx.pairs:
        length_bin = to_big_endian_binary(len(src))
        assert dst[1+len(length_bin):] == src
