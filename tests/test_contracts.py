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

def test_currency():
    k, v, k2, v2 = accounts()    
    scode2 = '''
if !contract.storage[1000]:
    contract.storage[1000] = 1
    contract.storage[0x%s] = 1000
    return(1)
elif msg.datasize == 1:
    addr = msg.data[0]
    return(contract.storage[addr])
else:
    from = msg.sender
    fromvalue = contract.storage[from]
    to = msg.data[0]
    value = msg.data[1]
    if fromvalue >= value:
        contract.storage[from] = fromvalue - value
        contract.storage[to] = contract.storage[to] + value
        return(1)
    else:
        return(0)
    ''' % v
    code2 = serpent.compile(scode2)
    blk = b.genesis({v: 10**18})
    tx4 = t.contract(0, gasprice, startgas, 0, code2).sign(k)
    s, addr = pb.apply_tx(blk, tx4)
    tx5 = t.Transaction(1, gasprice, startgas, addr, 0, '').sign(k)
    s, o = pb.apply_tx(blk, tx5)
    assert serpent.decode_datalist(o) == [1]
    tx6 = t.Transaction(2, gasprice, startgas, addr, 0, serpent.encode_datalist([v2, 200])).sign(k)
    s, o = pb.apply_tx(blk, tx6)
    assert serpent.decode_datalist(o) == [1]
    tx7 = t.Transaction(3, gasprice, startgas, addr, 0, serpent.encode_datalist([v2, 900])).sign(k)
    s, o = pb.apply_tx(blk, tx7)
    assert serpent.decode_datalist(o) == [0]
    tx8 = t.Transaction(4, gasprice, startgas, addr, 0, serpent.encode_datalist([v])).sign(k)
    s, o = pb.apply_tx(blk, tx8)
    assert serpent.decode_datalist(o) == [800]
    tx9 = t.Transaction(5, gasprice, startgas, addr, 0, serpent.encode_datalist([v2])).sign(k)
    s, o = pb.apply_tx(blk, tx9)
    assert serpent.decode_datalist(o) == [200]


def test_data_feeds():
    k, v, k2, v2 = accounts()    
    scode3 = '''
if !contract.storage[1000]:
    contract.storage[1000] = 1
    contract.storage[1001] = msg.sender
    return(0)
elif msg.sender == contract.storage[1001] and msg.datasize == 2:
    contract.storage[msg.data[0]] = msg.data[1]
    return(1)
else:
    return(contract.storage[msg.data[0]])
'''
    code3 = serpent.compile(scode3)
    # print("AST", serpent.rewrite(serpent.parse(scode3)))
    # print("Assembly", serpent.compile_to_assembly(scode3))
    blk = b.genesis({v: 10**18, v2: 10**18})
    tx10 = t.contract(0, gasprice, startgas, 0, code3).sign(k)
    s, addr = pb.apply_tx(blk, tx10)
    tx11 = t.Transaction(1, gasprice, startgas, addr, 0, '').sign(k)
    s, o = pb.apply_tx(blk, tx11)
    tx12 = t.Transaction(2, gasprice, startgas, addr, 0, serpent.encode_datalist([500])).sign(k)
    s, o = pb.apply_tx(blk, tx12)
    assert serpent.decode_datalist(o) == [0]
    tx13 = t.Transaction(3, gasprice, startgas, addr, 0, serpent.encode_datalist([500, 726])).sign(k)
    s, o = pb.apply_tx(blk, tx13)
    assert serpent.decode_datalist(o) == [1]
    tx14 = t.Transaction(4, gasprice, startgas, addr, 0, serpent.encode_datalist([500])).sign(k)
    s, o = pb.apply_tx(blk, tx14)
    assert serpent.decode_datalist(o) == [726]
    return blk, addr
