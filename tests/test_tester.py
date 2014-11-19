from pyethereum import tester
from random import randrange

def test_u256_string_bijection(values=None, n=None):
    if values is None:
        values = map(lambda x: randrange(2**256), range(10 if n is None else n))
    for v in values:
        assert tester.string_to_u256(tester.u256_to_string(v)) == v
