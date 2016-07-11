from ethereum import tester as t
from ethereum.slogging import set_level
import time


serpent_code = """
def sqrt(n):
    i = 0
    while i * i < n:
        i += 1
    return i

def mul(a:arr, b:arr):
    c = array(len(a))
    sz = self.sqrt(len(a))
    i = 0
    while i < sz:
        j = 0
        while j < sz:
            k = 0
            while k < sz:
                c[i * sz + j] += a[i * sz + k] * b[k * sz + j]
                k += 1
            j += 1
        i += 1
    return(c:arr)

def exp(a:arr, i):
    if i == 1:
        return(a:arr)
    elif i % 2 == 0:
        m = self.exp(a, i / 2, outitems=len(a))
        return(self.mul(m, m, outitems=len(a)):arr)
    elif i % 2 == 1:
        m = self.exp(a, i / 2, outitems=len(a))
        return(self.mul(self.mul(m, m, outitems=len(a)), a, outitems=len(a)):arr)
"""


def test_mul():
    set_level(None, 'info')
    s = t.state()
    c = s.abi_contract(serpent_code)
    assert c.mul([1, 0, 0, 1], [2, 3, 4, 5]) == [2, 3, 4, 5]
    assert c.exp([0, 1, -1, 0], 24) == [1, 0, 0, 1]
    assert c.exp([0, -1, 1, 0], 39) == [0, 1, -1, 0]
    t.gas_limit = 100000000
    x = time.time()
    c.exp([i for i in range(81)], 31415)
    print('Exponentiation done in: %f' % (time.time() - x))

if __name__ == '__main__':
    test_mul()
