import rlp
from ethereum.tools import tester
from ethereum import block
import pytest


mul2_code = """
def double(v):
    return(v*2)
"""

filename = "mul2_qwertyuioplkjhgfdsa.se"

returnten_code = """
extern mul2: [double:i]

x = create("%s")
return(x.double(5))
""" % filename


@pytest.mark.skip()
def test_returnten():
    s = tester.state()
    open(filename, 'w').write(mul2_code)
    c = s.contract(returnten_code)
    s.send(tester.k0, c, 0)
    b2 = rlp.decode(rlp.encode(s.block), block.Block, env=s.env)
    assert rlp.encode(b2) == rlp.encode(s.block)
