import os
import pytest
from pyethereum import tester
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

gasprice = 0
startgas = 10000

namecoin_code =\
    '''
if !contract.storage[msg.data[0]]:
    contract.storage[msg.data[0]] = msg.data[1]
    return(1)
else:
    return(0)
'''


def test_namecoin():
    s = tester.state()
    c = s.contract(namecoin_code)
    o1 = s.send(tester.k0, c, 0, ['"george"', 45])
    assert o1 == [1]
    o2 = s.send(tester.k0, c, 0, ['"george"', 20])
    assert o2 == [0]
    o3 = s.send(tester.k0, c, 0, ['"harry"', 60])
    assert o3 == [1]

    assert s.block.to_dict()


currency_code = '''
init:
    contract.storage[msg.sender] = 1000
code:
    if msg.datasize == 1:
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
'''


def test_currency():
    s = tester.state()
    c = s.contract(currency_code, sender=tester.k0)
    o1 = s.send(tester.k0, c, 0, [tester.a2, 200])
    assert o1 == [1]
    o2 = s.send(tester.k0, c, 0, [tester.a2, 900])
    assert o2 == [0]
    o3 = s.send(tester.k0, c, 0, [tester.a0])
    assert o3 == [800]
    o4 = s.send(tester.k0, c, 0, [tester.a2])
    assert o4 == [200]


data_feed_code = '''
if !contract.storage[1000]:
    contract.storage[1000] = 1
    contract.storage[1001] = msg.sender
    return(20)
elif msg.datasize == 2:
    if msg.sender == contract.storage[1001]:
        contract.storage[msg.data[0]] = msg.data[1]
        return(1)
    else:
        return(0)
else:
    return(contract.storage[msg.data[0]])
'''


def test_data_feeds():
    s = tester.state()
    c = s.contract(data_feed_code, sender=tester.k0)
    o1 = s.send(tester.k0, c, 0)
    assert o1 == [20]
    o2 = s.send(tester.k0, c, 0, [500])
    assert o2 == [0]
    o3 = s.send(tester.k0, c, 0, [500, 19])
    assert o3 == [1]
    o4 = s.send(tester.k0, c, 0, [500])
    assert o4 == [19]
    o5 = s.send(tester.k1, c, 0, [500, 726])
    assert o5 == [0]
    o6 = s.send(tester.k0, c, 0, [500, 726])
    assert o6 == [1]
    return s, c

hedge_code = '''
if !contract.storage[1000]:
    contract.storage[1000] = msg.sender
    contract.storage[1002] = msg.value
    contract.storage[1003] = msg.data[0]
    contract.storage[1004] = msg.data[1]
    return(1)
elif !contract.storage[1001]:
    ethvalue = contract.storage[1002]
    if msg.value >= ethvalue:
        contract.storage[1001] = msg.sender
    c = call(contract.storage[1003],[contract.storage[1004]],1)
    othervalue = ethvalue * c
    contract.storage[1005] = othervalue
    contract.storage[1006] = block.timestamp + 500
    return([2,othervalue],2)
else:
    othervalue = contract.storage[1005]
    ethvalue = othervalue / call(contract.storage[1003],contract.storage[1004])
    if ethvalue >= contract.balance:
        send(contract.storage[1000],contract.balance)
        return(3)
    elif block.timestamp > contract.storage[1006]:
        send(contract.storage[1001],contract.balance - ethvalue)
        send(contract.storage[1000],ethvalue)
        return(4)
    else:
        return(5)
'''


def test_hedge():
    s, c = test_data_feeds()
    c2 = s.contract(hedge_code, sender=tester.k0)
    o1 = s.send(tester.k0, c2, 10**16, [c, 500])
    assert o1 == [1]
    o2 = s.send(tester.k2, c2, 10**16)
    assert o2 == [2, 7260000000000000000]
    snapshot = s.snapshot()
    o3 = s.send(tester.k0, c, 0, [500, 300])
    assert o3 == [1]
    o4 = s.send(tester.k0, c2, 0)
    assert o4 == [3]
    s.revert(snapshot)
    o5 = s.send(tester.k0, c2, 0)
    assert o5 == [5]
    s.mine(10, tester.a3)
    o6 = s.send(tester.k0, c2, 0)
    assert o6 == [4]
