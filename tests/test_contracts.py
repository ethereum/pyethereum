import sys
import pytest
import pyethereum.serpent as serpent
import pyethereum.processblock as pb
import pyethereum.blocks as b
import pyethereum.transactions as t
import pyethereum.utils as u


gasprice = 0
startgas = 10000

@pytest.fixture(scope="module")
def accounts():
    k = u.sha3('cow')
    v = u.privtoaddr(k)
    k2 = u.sha3('horse')
    v2 = u.privtoaddr(k2)
    return k, v, k2, v2


def test_namecoin():
    k, v, k2, v2 = accounts()    
    blk = b.genesis({v: u.denoms.ether * 1})
    scode1 = '''
if !contract.storage[msg.data[0]]:
    contract.storage[msg.data[0]] = msg.data[1]
    return(1)
else:
    return(0)
    '''
    code1 = serpent.compile(scode1)
    tx1 = t.contract(0, gasprice, startgas, 0, code1).sign(k)
    s, addr = pb.apply_tx(blk, tx1)
    snapshot = blk.snapshot()
    tx2 = t.Transaction(1, gasprice, startgas, addr, 0, serpent.encode_datalist(['george', 45]))
    tx2.sign(k)
    s, o = pb.apply_tx(blk, tx2)
    assert serpent.decode_datalist(o) == [1]
    tx3 = t.Transaction(2, gasprice, startgas, addr, 0, serpent.encode_datalist(['george', 20])).sign(k)
    s, o = pb.apply_tx(blk, tx3)
    assert serpent.decode_datalist(o) == [0]
    tx4 = t.Transaction(3, gasprice, startgas, addr, 0, serpent.encode_datalist(['harry', 60])).sign(k)
    s, o = pb.apply_tx(blk, tx4)
    assert serpent.decode_datalist(o) == [1]
