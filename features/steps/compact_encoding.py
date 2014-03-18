@given(u'an Even length hex sequence')
def step_impl(context):
    context.srcs = [
        [],
        [0x0, 0x1],
        [0x1, 0x2, 0x3, 0x4]
    ]

@given(u'an odd length hex sequence')
def step_impl(context):
    context.srcs = [
        [0x0],
        [0x1, 0x2, 0x3]
    ]

@when(u'append a terminator')
def step_impl(context):
    for src in context.srcs:
        src.append(16)

@when(u'compactly encoded')
def step_impl(context):
    import trie
    context.pairs = [
        (src, trie.hexarraykey_to_bin(src))
        for src in context.srcs
    ]

@when(u'remove terminator from source')
def step_impl(context):
    for src in context.srcs:
        del src[-1]

@then(u'the first byte should be 0x00')
def step_impl(context):
    for src, dst in context.pairs:
        assert ord(dst[0]) == 0
    context.prefex_hex_count = 2

@then(u'the first byte should start with 0x1')
def step_impl(context):
    for src, dst in context.pairs:
        assert ord(dst[0]) & 0xF0 == 0x10
    context.prefex_hex_count = 1

@then(u'the first byte should be 0x20')
def step_impl(context):
    for src, dst in context.pairs:
        assert ord(dst[0]) & 0xF0 == 0x20
    context.prefex_hex_count = 2

@then(u'the first byte should start with 0x3')
def step_impl(context):
    for src, dst in context.pairs:
        assert ord(dst[0]) & 0xF0 == 0x30
    context.prefex_hex_count = 1

@then(u'the remain bits will be same of the original hex sequence')
def step_impl(context):
    for src, dst in context.pairs:
        print src, len(dst), ord(dst[0])
        assert len(src) == len(dst)*2 - context.prefex_hex_count

        dst_hexes = []

        for byte in dst:
            dst_hexes.extend([ord(byte) >> 4, ord(byte) & 0x0F])

        for src_hex, dst_hex in zip(src, dst_hexes[context.prefex_hex_count:]):
            assert src_hex == dst_hex

@then(u'decode the compactly encoded hex sequence will get the original one')
def step_impl(context):
    import trie
    for src, dst in context.pairs:
        decoded_hexes = trie.bin_to_hexarraykey(dst)
        for src_hex, dst_hex in zip(src, decoded_hexes):
            assert src_hex == dst_hex
