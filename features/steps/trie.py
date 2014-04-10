from behave import register_type
from .utils import parse_py

import random
from pyethereum import trie
from pyethereum import rlp

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


@then(u'tree has no change if key does not exist')  # noqa
def step_impl(context):
    if not context.key_exisits:
        assert context.trie.root == context.original_root


@when(u'delete by the key: {key:Py}')  # noqa
def step_impl(context, key):
    new_pairs = []
    context.key_exisits = False
    for (k, v) in context.pairs:
        if k == key:
            context.trie.delete(k)
            context.key_exisits = True
        else:
            new_pairs.append((k, v))
    context.original_root = context.trie.root
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


@then(u'to_dict will return the correct dict')  # noqa
def step_impl(context):
    res = context.trie.to_dict()
    assert dict(context.pairs) == res


@given(u'input dictionary: {input_dict:Py}')  # noqa
def step_impl(context, input_dict):
    context.input_dict = input_dict


@when(u'build trie tree from the input')  # noqa
def step_impl(context):
    for key, value in context.input_dict.iteritems():
        context.trie.update(key, value)


@then(u'the hash of the tree root is {root_hash:Py}')  # noqa
def step_impl(context, root_hash):
    t = context.trie
    rlp_root = rlp.encode(t._rlp_decode(t.root))
    assert trie.sha3(rlp_root).encode('hex') == root_hash
