from behave import register_type
from .utils import parse_py

from pyethereum import rlp
from pyethereum.utils import big_endian_to_int, recursive_int_to_big_endian

register_type(Py=parse_py)


@given(u'to be packeted payload data: {data:Py}')  # noqa
def step_impl(context, data):
    context.data = data
    context.encoded_data = rlp.encode(
        recursive_int_to_big_endian(context.data))


@when(u'dump the data to packet')  # noqa
def step_impl(context):
    context.packet = context.packeter.dump_packet(context.data)


@then(u'bytes [0:4) is synchronisation token: (0x22400891)')  # noqa
def step_impl(context):
    assert context.packet[:4] == '22400891'.decode('hex')


@then(u'bytes [4:8) is "payload(rlp serialized data) size" in form of big-endian integer')  # noqa
def step_impl(context):
    length = big_endian_to_int(context.packet[4:8])
    assert length == len(context.encoded_data)


@then(u'bytes [8:] data equal to RLP-serialised payload data')  # noqa
def step_impl(context):
    assert context.packet[8:] == context.encoded_data
