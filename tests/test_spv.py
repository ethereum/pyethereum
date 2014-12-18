import os, sys
import pytest
from pyethereum import tester, rlp


mul2_code = \
    '''
def double(v):
    return(v*2)
'''

filename = "mul2_qwertyuioplkjhgfdsa.se"

returnten_code = \
    '''
extern doubler: [double]

x = create("%s")
return(x.double(5, as=doubler))
''' % filename

@pytest.mark.skipif(sys.platform=='darwin', reason='segfaults on darwin')
def test_returnten():
    s = tester.state()
    open(filename, 'w').write(mul2_code)
    c = s.contract(returnten_code)
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k0, c, 0, [])
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    verify = s.verifyspv(tester.k0, c, 0, [], proof=proof)
    assert verify
    os.remove(filename)

data_feed_code = '''
data creator
data values[]


def init():
    self.creator = msg.sender

def set(k, v):
    if msg.sender == self.creator:
        self.values[k] = v
        return(1)
    else:
        return(0)

def get(k):
    return(self.values[k])
'''

@pytest.mark.skip
def test_data_feeds():
    s = tester.state()
    c = s.contract(data_feed_code, sender=tester.k0)
    o2 = s.send(tester.k0, c, 0, funid=1, abi=[500])
    assert o2 == [0]
    o3 = s.send(tester.k0, c, 0, funid=0, abi=[500, 19])
    assert o3 == [1]
    o4 = s.send(tester.k0, c, 0, funid=1, abi=[500])
    assert o4 == [19]
    o5 = s.send(tester.k1, c, 0, funid=0, abi=[500, 726])
    assert o5 == [0]
    o6 = s.send(tester.k0, c, 0, funid=0, abi=[500, 726])
    assert o6 == [1]
    return s, c

# Test an example hedging contract, using the data feed. This tests
# contracts calling other contracts

hedge_code = '''
extern datafeed: [set, get]

data partyone
data partytwo
data hedgeValue
data datafeed
data index
data fiatValue
data maturity

def main(datafeed, index):
    if !self.partyone:
        self.partyone = msg.sender
        self.hedgeValue = msg.value
        self.datafeed = datafeed
        self.index = index
        return(1)
    elif !self.partytwo:
        ethvalue = self.hedgeValue
        if msg.value >= ethvalue:
            self.partytwo = msg.sender
        c = self.datafeed.get(data=[self.index], datasz=1)
        othervalue = ethvalue * c
        self.fiatValue = othervalue
        self.maturity = block.timestamp + 500
        return([2, othervalue],2)
    else:
        othervalue = self.fiatValue
        ethvalue = othervalue / self.datafeed.get(self.index)
        if ethvalue >= self.balance:
            send(self.partyone, self.balance)
            return(3)
        elif block.timestamp > self.maturity:
            send(self.partytwo, self.balance - ethvalue)
            send(self.partyone, ethvalue)
            return(4)
        else:
            return(5)
'''
@pytest.mark.skip
def test_hedge():
    s, c = test_data_feeds()
    c2 = s.contract(hedge_code, sender=tester.k0)
    # Have the first party register, sending 10^16 wei and
    # asking for a hedge using currency code 500
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k0, c2, 10**16, funid=0, abi=[c, 500])
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    assert s.verifyspv(tester.k0, c2, 10**16, funid=0, abi=[c, 500], proof=proof)

    # Have the second party register. It should receive the
    # amount of units of the second currency that it is
    # entitled to. Note that from the previous test this is
    # set to 726
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k2, c2, 10**16, [])
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    assert s.verifyspv(tester.k2, c2, 10**16, [], proof=proof)

    # Set the price of the asset down to 300 wei
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k0, c, 0, funid=0, abi=[500, 300])
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    assert s.verifyspv(tester.k0, c, 0, funid=0, abi=[500, 300], proof=proof)

    # Finalize the contract. Expect code 3, meaning a margin call
    snapshot = s.snapshot()
    proof = s.mkspv(tester.k0, c2, 0)
    print "Proof length %d" % len(rlp.encode(proof))
    s.revert(snapshot)
    assert s.verifyspv(tester.k0, c2, 0, [], proof=proof)
