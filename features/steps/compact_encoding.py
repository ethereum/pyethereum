@given(u'an Even length hex sequence')
def step_impl(context):
    context.srcs = [
        []
        [0x0, 0x1]
        [0x1, 0x2, 0x3, 0x4]
    ]

@when(u'compactly encoded')
def step_impl(context):
    import trie
    context.pairs = [
        (src, trie.hexarraykey_to_bin(src))
        for src in context.srcs
    ]

@then(u'the first byte should be 0x00')
def step_impl(context):
    for src, dst in context.pairs:
        assert dst[0] == 0
    context.prefex_hex_count = 2

@then(u'the remain bits with be same of the original hex sequence')
def step_impl(context):
    assert False

@then(u'decode the compactly encoded hex sequence will get the original one')
def step_impl(context):
    assert False

@given(u'an odd length hex sequence')
def step_impl(context):
    assert False

@then(u'the first byte should start with 0x1')
def step_impl(context):
    assert False

@when(u'append a terminator')
def step_impl(context):
    assert False

@then(u'the first byte should start with 0x2')
def step_impl(context):
    assert False

@then(u'the first byte should start with 0x3')
def step_impl(context):
    assert False
