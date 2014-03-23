@when(u'clear trie tree')
def step_impl(context):
    context.trie.clear()

@then(u'root will be blank')
def step_impl(context):
    assert context.trie.root == ''

@given(u'pair1 with key "AB"')
def step_impl(context):
    context.pair1 = ("AB", str(list(range(1024))))

@given(u'pair2 with key "AC"')
def step_impl(context):
    context.pair2 = ("AC", str(list(range(31))))

@given(u'pair3 with key "ABCD"')
def step_impl(context):
    context.pair3 = ("ABCD", str(list(range(32))))

@given(u'pair4 with key "ACD"')
def step_impl(context):
    context.pair4 = ("ACD", str(list(range(24))))

@given(u'pair5 with key "A"')
def step_impl(context):
    context.pair5 = ("A", str(list(range(50))))

@given(u'pair6 with key "B"')
def step_impl(context):
    context.pair6 = ("B", str(list(range(124))))

@given(u'pair7 with key "BCD"')
def step_impl(context):
    context.pair7 = ("BCD", str(list(range(104))))

@when(u'insert {pair}')
def step_impl(context, pair):
    key, value = getattr(context, pair)
    context.trie.update(key, value)

@then(u'get with key of {pair} will return the correct value')
def step_impl(context, pair):
    key, value = getattr(context, pair)
    context.trie.get(key) == str(value)
