from behave import register_type
from .utils import parse_py

import random
from pyethereum import trie

register_type(Py=parse_py)


def gen_random_value():
    value = range(random.randint(5, 40))
    value.extend([0]*20)
    random.shuffle(value)
    value = ''.join(str(x) for x in value)
    return value


@when(u'clear trie tree')  # noqa
def step_impl(context):
    context.trie.clear()


@then(u'root will be blank')  # noqa
def step_impl(context):
    assert context.trie.root_hash == trie.BLANK_ROOT


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


@then(u'get by the key: {key:Py} will return BLANK')  # noqa
def step_impl(context, key):
    assert context.trie.get(key) == ''


@when(u'insert pairs except key: {key:Py}')  # noqa
def step_impl(context, key):
    pairs = []
    for k, v in context.pairs:
        if k != key:
            v = gen_random_value()
            context.trie.update(k, v)
            pairs.append((k, v))
    context.pairs = pairs


@when(u'record hash as old hash')  # noqa
def step_impl(context):
    context.old_hash = context.trie.root_hash


@when(u'insert pair with key: {key:Py}')  # noqa
def step_impl(context, key):
    v = gen_random_value()
    context.trie.update(key, v)


@when(u'record hash as new hash')  # noqa
def step_impl(context):
    context.new_hash = context.trie.root_hash


@then(u'for keys except {key:Py}, get with key will'  # noqa
      ' return the correct value')
def step_impl(context, key):
    for k, v in context.pairs:
        if k != key:
            assert context.trie.get(k) == v


@then(u'old hash is the same with new hash')  # noqa
def step_impl(context):
    assert context.old_hash == context.new_hash


@when(u'delete by the key: {key:Py}')  # noqa
def step_impl(context, key):
    context.trie.delete(key)


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
    assert len(context.trie) == len(context.pairs)


@then(u'to_dict will return the correct dict')  # noqa
def step_impl(context):
    res = context.trie.to_dict()
    assert dict(context.pairs) == res


@given(u'input dictionary: {input_dict:Py}')  # noqa
def step_impl(context, input_dict):
    context.input_dict = input_dict


@when(u'build trie tree from the input')  # noqa
def step_impl(context):
    if isinstance(context.input_dict, dict):
        dic = context.input_dict.iteritems()
    else:
        dic = context.input_dict
    for key, value in dic:
        context.trie.update(key, value)


@given(u'trie fixtures file path')  # noqa
def step_impl(context):
    context.trie_fixture_path = 'fixtures/trietest.json'


@when(u'load the trie fixtures')  # noqa
def step_impl(context):
    import json
    data = json.load(file(context.trie_fixture_path))
    context.examples = data


@then(u'for each example, then the hash of the tree root'  # noqa
' is the expectation')
def step_impl(context):
    for title, example in context.examples.iteritems():
        context.trie.clear()
        for pair in example['inputs']:
            context.trie.update(pair[0], pair[1])
        hex_hash = context.trie.root_hash.encode('hex')
        assert hex_hash == example['expectation'], '{} fails'.format(title)
