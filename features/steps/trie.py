from behave import register_type
from .utils import parse_py

import random

register_type(Py=parse_py)


def gen_random_value():
    value = range(random.randint(5, 40))
    random.shuffle(value)
    value = ''.join(str(x) for x in value)
    return value


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
        context.pairs.append((key, gen_random_value()))


@when(u'insert pairs')  # noqa
def step_impl(context):
    for (key, value) in context.pairs:
        context.trie.update(key, value)


@then(u'for each pair, get with key will return the correct value')  # noqa
def step_impl(context):
    for (key, value) in context.pairs:
        assert context.trie.get(key) == str(value)


@then(u'get by the key: {key:Py} will return None')  # noqa
def step_impl(context, key):
    assert context.trie.get(key) is None


@when(u'delete by the key: {key:Py}')  # noqa
def step_impl(context, key):
    new_pairs = []
    for (k, v) in context.pairs:
        if k == key:
            context.trie.delete(k)
        else:
            new_pairs.append((k, v))
    context.pairs = new_pairs


@when(u'update by the key: {key:Py}')  # noqa
def step_impl(context, key):
    new_pairs = []
    for (k, v) in context.pairs:
        if k == key:
            v = gen_random_value()
            context.trie.update(k, v)
        new_pairs.append((k, v))
    context.pairs = new_pairs


@then(u'get size will return the correct number')  # noqa
def step_impl(context):
    assert context.trie.get_size() == len(context.pairs)
