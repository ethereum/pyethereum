import pytest
import serpent
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

    # tx1
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

    # tx2
    tx2 = t.Transaction(1, gasprice, startgas, addr, 0,
                        serpent.encode_datalist(['george', 45]))
    tx2.sign(k)
    s, o = pb.apply_tx(blk, tx2)
    assert serpent.decode_datalist(o) == [1]

    # tx3
    tx3 = t.Transaction(2, gasprice, startgas, addr, 0,
                        serpent.encode_datalist(['george', 20])).sign(k)
    s, o = pb.apply_tx(blk, tx3)
    assert serpent.decode_datalist(o) == [0]

    # tx4
    tx4 = t.Transaction(3, gasprice, startgas, addr, 0,
                        serpent.encode_datalist(['harry', 60])).sign(k)
    s, o = pb.apply_tx(blk, tx4)
    assert serpent.decode_datalist(o) == [1]

    blk.revert(snapshot)

    assert blk.to_dict()
    assert blk.to_dict()['state'][addr]['code']


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
    blk = b.genesis({v: 10 ** 18})
    tx4 = t.contract(0, gasprice, startgas, 0, code2).sign(k)
    s, addr = pb.apply_tx(blk, tx4)
    tx5 = t.Transaction(1, gasprice, startgas, addr, 0, '').sign(k)
    s, o = pb.apply_tx(blk, tx5)
    assert serpent.decode_datalist(o) == [1]
    tx6 = t.Transaction(2, gasprice, startgas, addr, 0,
                        serpent.encode_datalist([v2, 200])).sign(k)
    s, o = pb.apply_tx(blk, tx6)
    assert serpent.decode_datalist(o) == [1]
    tx7 = t.Transaction(3, gasprice, startgas, addr, 0,
                        serpent.encode_datalist([v2, 900])).sign(k)
    s, o = pb.apply_tx(blk, tx7)
    assert serpent.decode_datalist(o) == [0]
    tx8 = t.Transaction(4, gasprice, startgas, addr, 0,
                        serpent.encode_datalist([v])).sign(k)
    s, o = pb.apply_tx(blk, tx8)
    assert serpent.decode_datalist(o) == [800]
    tx9 = t.Transaction(5, gasprice, startgas, addr, 0,
                        serpent.encode_datalist([v2])).sign(k)
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
    blk = b.genesis({v: 10 ** 18, v2: 10 ** 18})
    tx10 = t.contract(0, gasprice, startgas, 0, code3).sign(k)
    s, addr = pb.apply_tx(blk, tx10)
    tx11 = t.Transaction(1, gasprice, startgas, addr, 0, '').sign(k)
    s, o = pb.apply_tx(blk, tx11)
    tx12 = t.Transaction(2, gasprice, startgas, addr, 0,
                         serpent.encode_datalist([500])).sign(k)
    s, o = pb.apply_tx(blk, tx12)
    assert serpent.decode_datalist(o) == [0]
    tx13 = t.Transaction(3, gasprice, startgas, addr, 0,
                         serpent.encode_datalist([500, 726])).sign(k)
    s, o = pb.apply_tx(blk, tx13)
    assert serpent.decode_datalist(o) == [1]
    tx14 = t.Transaction(4, gasprice, startgas, addr, 0,
                         serpent.encode_datalist([500])).sign(k)
    s, o = pb.apply_tx(blk, tx14)
    assert serpent.decode_datalist(o) == [726]
    return blk, addr


def test_hedge():
    k, v, k2, v2 = accounts()
    blk, addr = test_data_feeds()
    scode4 = '''
if !contract.storage[1000]:
    contract.storage[1000] = msg.sender
    contract.storage[1002] = msg.value
    contract.storage[1003] = msg.data[0]
    return(1)
elif !contract.storage[1001]:
    ethvalue = contract.storage[1002]
    if msg.value >= ethvalue:
        contract.storage[1001] = msg.sender
    othervalue = ethvalue * call(0x%s,[contract.storage[1003]],1)
    contract.storage[1004] = othervalue
    contract.storage[1005] = block.timestamp + 86400
    return([2,othervalue],2)
else:
    othervalue = contract.storage[1004]
    ethvalue = othervalue / call(0x%s,contract.storage[1003])
    if ethvalue >= contract.balance:
        send(contract.storage[1000],contract.balance)
        return(3)
    elif block.timestamp > contract.storage[1005]:
        send(contract.storage[1001],contract.balance - ethvalue)
        send(contract.storage[1000],ethvalue)
        return(4)
    else:
        return(5)
''' % (addr, addr)
    code4 = serpent.compile(scode4)
    # print("AST", serpent.rewrite(serpent.parse(scode4)))
    # print("Assembly", serpent.compile_to_assembly(scode4))
    # important: no new genesis block
    tx15 = t.contract(5, gasprice, startgas, 0, code4).sign(k)
    s, addr2 = pb.apply_tx(blk, tx15)
    tx16 = t.Transaction(6, gasprice, startgas, addr2, 10 ** 17,
                         serpent.encode_datalist([500])).sign(k)
    s, o = pb.apply_tx(blk, tx16)
    assert serpent.decode_datalist(o) == [1]
    tx17 = t.Transaction(0, gasprice, startgas, addr2, 10 ** 17,
                         serpent.encode_datalist([500])).sign(k2)
    s, o = pb.apply_tx(blk, tx17)
    assert serpent.decode_datalist(o) == [2, 72600000000000000000L]
    snapshot = blk.snapshot()
    tx18 = t.Transaction(7, gasprice, startgas, addr2, 0, '').sign(k)
    s, o = pb.apply_tx(blk, tx18)
    assert serpent.decode_datalist(o) == [5]
    tx19 = t.Transaction(8, gasprice, startgas, addr, 0,
                         serpent.encode_datalist([500, 300])).sign(k)
    s, o = pb.apply_tx(blk, tx19)
    assert serpent.decode_datalist(o) == [1]
    tx20 = t.Transaction(9, gasprice, startgas, addr2, 0, '').sign(k)
    s, o = pb.apply_tx(blk, tx20)
    assert serpent.decode_datalist(o) == [3]
    blk.revert(snapshot)
    blk.timestamp += 200000
    tx21 = t.Transaction(7, gasprice, startgas, addr, 0,
                         serpent.encode_datalist([500, 1452])).sign(k)
    s, o = pb.apply_tx(blk, tx21)
    assert serpent.decode_datalist(o) == [1]
    tx22 = t.Transaction(8, gasprice, 2000, addr2, 0, '').sign(k)
    s, o = pb.apply_tx(blk, tx22)
    assert serpent.decode_datalist(o) == [4]
