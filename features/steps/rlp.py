from behave import *

@given('the byte is in [0x00, 0x7f] range')
def step_impl(ctx):
    ctx.srcs = [0x00, 0x71, 0x7f]


@then('the byte is its own RLP encoding')
def step_impl(ctx):
    import rlp
    for src in ctx.srcs:
        assert rlp.encode(src) == chr(src)
