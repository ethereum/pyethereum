from behave import register_type
from .utils import parse_py

from pyethereum import trie

register_type(Py=parse_py)


@given(u'nibbles: {src_nibbles:Py}')  # noqa
def step_impl(context, src_nibbles):
    context.src_nibbles = src_nibbles


@when(u'append a terminator')  # noqa
def step_impl(context):
    context.src_nibbles.append(trie.NIBBLE_TERMINATOR)


@when(u'packed to binary')  # noqa
def step_impl(context):
    context.dst_binary = trie.pack_nibbles(context.src_nibbles)


@then(u'in the binary, the first nibbles should be {first_nibble:Py}')  # noqa
def step_impl(context, first_nibble):
    assert ord(context.dst_binary[0]) & 0xF0 == first_nibble << 4
    context.prefix_nibbles_count = 1


@then(u'the second nibbles should be {second_nibble:Py}')  # noqa
def step_impl(context, second_nibble):
    assert ord(context.dst_binary[0]) & 0x0F == second_nibble
    context.prefix_nibbles_count = 2


@then(u'nibbles after should equal to the original nibbles')  # noqa
def step_impl(context):
    dst_nibbles = trie.unpack_to_nibbles(context.dst_binary)
    assert dst_nibbles == context.src_nibbles


@then(u'unpack the binary will get the original nibbles')  # noqa
def step_impl(context):
    assert context.src_nibbles == trie.unpack_to_nibbles(context.dst_binary)


@then(u'the packed result will be {dst:Py}')  # noqa
def step_impl(context, dst):
    assert context.dst_binary.encode('hex') == dst


@given(u'to be packed nibbles: {nibbles:Py} and terminator: {term:Py}')  # noqa
def step_impl(context, nibbles, term):
    context.src_nibbles = nibbles
    if term:
        context.src_nibbles.append(trie.NIBBLE_TERMINATOR)
