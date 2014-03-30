from behave import register_type
from .utils import parse_py

import random

register_type(Py=parse_py)


@when(u'clear trie tree')  # noqa
def step_impl(context):
    context.trie.clear()


@then(u'root will be blank')  # noqa
def step_impl(context):
    assert context.trie.root == ''


@given(u'pairs with keys: {keys:Py}')  # noqa
def step_impl(context, keys):
    context.pairs = []
    for key in keys:
        value = range(random.randint(5, 40))
        random.shuffle(value)
        value = ''.join(str(x) for x in value)
        context.pairs.append((key, value))


@when(u'insert pairs')  # noqa
def step_impl(context):
    for (key, value) in context.pairs:
        context.trie.update(key, value)


@then(u'for each pair, get with key will return the correct value')  # noqa
def step_impl(context):
    for (key, value) in context.pairs:
        assert context.trie.get(key) == str(value)


@given(u'a key: {key:Py}')  # noqa
def step_impl(context, key):
    context.key = key


@then(u'get by the key will return None')  # noqa
def step_impl(context):
    assert context.trie.get(context.key) is None


@when(u'delete by the key')  # noqa
def step_impl(context):
    context.trie.delete(context.key)
