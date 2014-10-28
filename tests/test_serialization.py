import pytest
from pyethereum import tester, blocks


mul2_code = \
    '''
return(msg.data[0]*2)
'''

filename = "mul2_qwertyuioplkjhgfdsa.se"

returnten_code = \
    '''
x = create("%s")
return(call(x, 5))
''' % filename


def test_returnten():
    s = tester.state()
    open(filename, 'w').write(mul2_code)
    c = s.contract(returnten_code)
    s.send(tester.k0, c, 0, [])
    b2 = blocks.Block.deserialize(s.block.serialize())
    assert b2.serialize() == s.block.serialize()
