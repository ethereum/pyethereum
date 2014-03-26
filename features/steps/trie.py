import random

@when(u'clear trie tree')
def step_impl(context):
    context.trie.clear()

@then(u'root will be blank')
def step_impl(context):
    assert context.trie.root == ''

@given(u'a pair with key "{key}"')
def step_impl(context, key):
    if 'pairs' not in context:
        context.pairs = []
    value =range(random.randint(5, 40))
    random.shuffle(value)
    value = ''.join(str(x) for x in value)
    context.pairs.append((key, value))

@when(u'insert pairs')
def step_impl(context):
    for (key, value) in context.pairs:
        context.trie.update(key, value)

@then(u'for each pair, get with key will return the correct value')
def step_impl(context):
    for (key, value) in context.pairs:
        assert context.trie.get(key) == str(value)
