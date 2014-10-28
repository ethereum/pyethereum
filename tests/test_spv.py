import os
import pytest
from pyethereum import tester, rlp


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
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k0, c, 0, [])
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    verify = s.verifyspv(tester.k0, c, 0, [], proof)
    assert verify
    os.remove(filename)


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

# Test an example hedging contract, using the data feed. This tests
# contracts calling other contracts

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
    # Have the first party register, sending 10^16 wei and
    # asking for a hedge using currency code 500
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k0, c2, 10**16, [c, 500])
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    assert s.verifyspv(tester.k0, c2, 10**16, [c, 500], proof)

    # Have the second party register. It should receive the
    # amount of units of the second currency that it is
    # entitled to. Note that from the previous test this is
    # set to 726
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k2, c2, 10**16, [])
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    assert s.verifyspv(tester.k2, c2, 10**16, [], proof)

    # Set the price of the asset down to 300 wei
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k0, c, 0, [500, 300])
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    assert s.verifyspv(tester.k0, c, 0, [500, 300], proof)

    # Finalize the contract. Expect code 3, meaning a margin call
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k0, c2, 0)
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    assert s.verifyspv(tester.k0, c2, 0, [], proof)
