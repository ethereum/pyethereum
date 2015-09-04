import rlp
from ethereum import tester, blocks


mul2_code = \
    '''
def double(v):
    return(v*2)
'''

filename = "mul2_qwertyuioplkjhgfdsa.se"

returnten_code = \
    '''
extern mul2: [double:i]

x = create("%s")
return(x.double(5))
''' % filename


def test_returnten():
    s = tester.state()
    open(filename, 'w').write(mul2_code)
    c = s.contract(returnten_code)
    s.send(tester.k0, c, 0)
    b2 = rlp.decode(rlp.encode(s.block), blocks.Block, env=s.env)
    assert rlp.encode(b2) == rlp.encode(s.block)
