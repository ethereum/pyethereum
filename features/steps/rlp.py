from behave import register_type
from .utils import parse_py, AssertException

from pyethereum.utils import int_to_big_endian, recursive_int_to_big_endian
from pyethereum import rlp

register_type(Py=parse_py)


@given(u'a to be rlp encoded payload: {src:Py}')  # noqa
def step_impl(context, src):
    context.src = recursive_int_to_big_endian(src)


@when(u'encoded in RLP')  # noqa
def step_impl(context):
    context.dst = rlp.encode(context.src)


@then(u'decode the RLP encoded data will get the original data')  # noqa
def step_impl(context):
    assert context.src == rlp.decode(context.dst)


@then(u'the byte is its own RLP encoding')  # noqa
def step_impl(context):
    assert context.dst == context.src


@then(u'the first byte is 0x80 plus the length of the string')  # noqa
def step_impl(context):
    assert context.dst[0] == chr(0x80 + len(context.src))


@then(u'followed by the string')  # noqa
def step_impl(context):
    assert context.dst[1:] == context.src


@then(u'the first byte is 0xb7 plus the length of the length of the string')  # noqa
def step_impl(context):
    context.length_bin = int_to_big_endian(len(context.src))
    assert context.dst[0] == chr(0xb7 + len(context.length_bin))


@then(u'following bytes are the payload string length')
def step_impl(context):
    assert context.dst[1:1 + len(context.length_bin)] == context.length_bin


@then(u'following bytes are the payload string itself')
def step_impl(context):
    assert context.dst[1 + len(context.length_bin):] == context.src


@then(u'the first byte is 0xc0 plus the length of the list')  # noqa
def step_impl(context):
    total_payload_length = sum(len(rlp.encode(x)) for x in context.src)
    assert context.dst[0] == chr(0xc0 + total_payload_length)


@then(u'following bytes are concatenation of the RLP encodings of the items')  # noqa
def step_impl(context):
    assert context.dst[1:] == ''.join(rlp.encode(x) for x in context.src)


@then(u'the first byte is 0xf7 plus the length of the length of the list')  # noqa
def step_impl(context):
    total_payload_length = sum(len(rlp.encode(x)) for x in context.src)
    context.length_bin = int_to_big_endian(total_payload_length)
    assert context.dst[0] == chr(0xf7 + len(context.length_bin))


@then(u'following bytes are the payload list length')  # noqa
def step_impl(context):
    assert context.dst[1:1 + len(context.length_bin)] == context.length_bin


@then(u'following bytes are the payload list itself')  # noqa
def step_impl(context):
    encodeds = [rlp.encode(x) for x in context.src]
    assert context.dst[1 + len(context.length_bin):] == ''.join(encodeds)


@then(u'raise TypeError')  # noqa
def step_impl(context):
    with AssertException(TypeError):
        rlp.encode(context.src)


@then(u'the rlp encoded result will be equal to {dst:Py}')  # noqa
def step_impl(context, dst):
    assert context.dst.encode('hex') == dst
