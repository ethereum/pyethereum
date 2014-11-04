import os
import pytest
from pyethereum import tester
import serpent
import logging
logging.basicConfig(level=logging.DEBUG, format='%(message)s')
logger = logging.getLogger()

# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
pblogger = tester.pb.pblogger
pblogger.log_pre_state = True    # dump storage at account before execution
pblogger.log_post_state = True   # dump storage at account after execution
pblogger.log_block = False       # dump block after TX was applied
pblogger.log_memory = True      # dump memory before each op
pblogger.log_stack = True        # dump stack before each op
pblogger.log_op = True           # log op, gas, stack before each op
pblogger.log_apply_op = True     # log op, gas, stack before each op
pblogger.log_json = False        # generate machine readable output

gasprice = 0
startgas = 10000


# Test EVM contracts
serpent_code = '''
def main(a,b):
    return(a ^ b)
'''

evm_code = serpent.compile(serpent_code)


def test_evm():
    s = tester.state()
    c = s.evm(evm_code)
    o = s.send(tester.k0, c, 0, funid=0, abi=[2, 5])
    assert o == [32]


# Test serpent compilation of variables using _with_, doing a simple
# arithmetic calculation 20 * 30 + 10 = 610
sixten_code =\
    '''
(with 'x 10
    (with 'y 20
        (with 'z 30
            (seq
                (set 'a (add (mul (get 'y) (get 'z)) (get 'x)))
                (return (ref 'a) 32)
            )
        )
    )
)
'''


def test_sixten():
    s = tester.state()
    c = s.contract('')
    s.block.set_code(c, tester.serpent.compile_lll(sixten_code))
    o1 = s.send(tester.k0, c, 0, [])
    assert o1 == [610]

# Test Serpent's import mechanism

mul2_code = \
    '''
def double(v:17):
    return(v*2)
'''

filename = "mul2_qwertyuioplkjhgfdsa.se"

returnten_code = \
    '''
extern mul2: [double]

x = create("%s")
return(x.double(5))
''' % filename


def test_returnten():
    s = tester.state()
    open(filename, 'w').write(mul2_code)
    c = s.contract(returnten_code)
    o1 = s.send(tester.k0, c, 0, [])
    os.remove(filename)
    assert o1 == [10]


# Test a simple namecoin implementation

namecoin_code =\
    '''
def main(k, v):
    if !self.storage[k]:
        self.storage[k] = v
        return(1)
    else:
        return(0)
'''


def test_namecoin():
    s = tester.state()
    c = s.contract(namecoin_code)
    o1 = s.send(tester.k0, c, 0, funid=0, abi=['"george"', 45])
    assert o1 == [1]
    o2 = s.send(tester.k0, c, 0, funid=0, abi=['"george"', 20])
    assert o2 == [0]
    o3 = s.send(tester.k0, c, 0, funid=0, abi=['"harry"', 60])
    assert o3 == [1]

    assert s.block.to_dict()

# Test a simple currency implementation

currency_code = '''
data balances[2^160]

def init():
    self.balances[msg.sender] = 1000

def query(addr):
    return(self.balances[addr])

def send(to:29, value:31):
    from = msg.sender
    fromvalue = self.balances[from]
    if fromvalue >= value:
        self.balances[from] = fromvalue - value
        self.balances[to] = self.balances[to] + value
        log(from, to, value)
        return(1)
    else:
        return(0)
'''


def test_currency():
    s = tester.state()
    c = s.contract(currency_code, sender=tester.k0)
    o1 = s.send(tester.k0, c, 0, funid=1, abi=[tester.a2+':29', '200:31'])
    assert o1 == [1]
    o2 = s.send(tester.k0, c, 0, funid=1, abi=[tester.a2+':29', '900:31'])
    assert o2 == [0]
    o3 = s.send(tester.k0, c, 0, funid=0, abi=[tester.a0])
    assert o3 == [800]
    o4 = s.send(tester.k0, c, 0, funid=0, abi=[tester.a2])
    assert o4 == [200]

# Test a data feed

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


def test_hedge():
    s, c = test_data_feeds()
    c2 = s.contract(hedge_code, sender=tester.k0)
    # Have the first party register, sending 10^16 wei and
    # asking for a hedge using currency code 500
    o1 = s.send(tester.k0, c2, 10**16, funid=0, abi=[c, 500])
    assert o1 == [1]
    # Have the second party register. It should receive the
    # amount of units of the second currency that it is
    # entitled to. Note that from the previous test this is
    # set to 726
    o2 = s.send(tester.k2, c2, 10**16)
    assert o2 == [2, 7260000000000000000]
    snapshot = s.snapshot()
    # Set the price of the asset down to 300 wei
    o3 = s.send(tester.k0, c, 0, funid=0, abi=[500, 300])
    assert o3 == [1]
    # Finalize the contract. Expect code 3, meaning a margin call
    o4 = s.send(tester.k0, c2, 0)
    assert o4 == [3]
    s.revert(snapshot)
    # Don't change the price. Finalize, and expect code 5, meaning
    # the time has not expired yet
    o5 = s.send(tester.k0, c2, 0)
    assert o5 == [5]
    s.mine(100, tester.a3)
    # Mine ten blocks, and try. Expect code 4, meaning a normal execution
    # where both get their share
    o6 = s.send(tester.k0, c2, 0)
    assert o6 == [4]


# Test the LIFO nature of call
arither_code = '''
def init():
    self.storage[0] = 10

def f1():
    self.storage[0] += 1

def f2():
    self.storage[0] *= 10
    call(self, 0)
    self.storage[0] *= 10

def f3():
    return(self.storage[0])
'''


def test_lifo():
    s = tester.state()
    c = s.contract(arither_code)
    s.send(tester.k0, c, 0, funid=1, abi=[])
    o2 = s.send(tester.k0, c, 0, funid=2, abi=[])
    assert o2 == [1010]


# Test suicides and suicide reverts
suicider_code = '''
def mainloop(rounds):
    self.storage[15] = 40
    call(self, 3)
    i = 0
    while i < rounds:
        i += 1

def entry(rounds):
    self.storage[15] = 20
    call(self, 0, rounds, gas=tx.gas - 100)

def ping_ten():
    return(10)

def suicide():
    suicide(0)

def ping_storage15():
    return(self.storage[15])
'''


def test_suicider():
    s = tester.state()
    c = s.contract(suicider_code)
    prev_gas_limit = tester.gas_limit
    tester.gas_limit = 4000
    # Run normally: suicide processes, so the attempt to ping the
    # contract fails
    s.send(tester.k0, c, 0, funid=0, abi=[1, 10])
    o2 = s.send(tester.k0, c, 0, funid=0, abi=[2])
    assert o2 == []
    c = s.contract(suicider_code)
    # Run the suicider in such a way that it suicides in a sub-call,
    # then runs out of gas, leading to a revert of the suicide and the
    # storage mutation
    s.send(tester.k0, c, 0, funid=1, abi=[4000])
    # Check that the suicide got reverted
    o2 = s.send(tester.k0, c, 0, funid=2, abi=[])
    assert o2 == [10]
    # Check that the storage op got reverted
    o3 = s.send(tester.k0, c, 0, funid=4, abi=[])
    assert o3 == [20]
    tester.gas_limit = prev_gas_limit


# Test reverts

reverter_code = '''
def entry():
    call(self, 1, gas=1000)
    call(self, 2, gas=1000)

def non_recurse():
    send(7, 9)
    self.storage[8080] = 4040
    self.storage[160160] = 2020

def recurse():
    send(8, 9)
    self.storage[8081] = 4039
    self.storage[160161] = 2019
    call(self, 2)
    self.storage["waste_some_gas"] = 0
'''


def test_reverter():
    s = tester.state()
    c = s.contract(reverter_code, endowment=10**15)
    s.send(tester.k0, c, 0, funid=0, abi=[0])
    assert s.block.get_storage_data(c, 8080) == 4040
    assert s.block.get_balance('0'*39+'7') == 9
    assert s.block.get_storage_data(c, 8081) == 0
    assert s.block.get_balance('0'*39+'8') == 0

# Test stateless contracts

add1_code = \
    '''
def main(x):
    self.storage[1] += x
'''

filename2 = "stateless_qwertyuioplkjhgfdsa.se"

callcode_test_code = \
    '''
extern add1: [main]

x = create("%s")
x.main(6)
x.main(4, call=code)
x.main(60, call=code)
x.main(40)
return(self.storage[1])
''' % filename2


def test_callcode():
    s = tester.state()
    open(filename2, 'w').write(add1_code)
    c = s.contract(callcode_test_code)
    o1 = s.send(tester.k0, c, 0)
    os.remove(filename2)
    assert o1 == [64]


# https://github.com/ethereum/serpent/issues/8
array_code = '''
a = array(1)
a[0] = 1
return(a, 1)
'''


def test_array():
    s = tester.state()
    c = s.contract(array_code)
    assert [1] == s.send(tester.k0, c, 0, [])

array_code2 = '''
a = array(1)
something = 2
a[0] = 1
return(a, 1)
'''


def test_array2():
    s = tester.state()
    c = s.contract(array_code2)
    assert [1] == s.send(tester.k0, c, 0, [])

array_code3 = """
a = array(3)
return(a, 3)
"""


def test_array3():
    s = tester.state()
    c = s.contract(array_code3)
    assert [0, 0, 0] == s.send(tester.k0, c, 0, [])


calltest_code = """
def main():
    self.first(1, 2, 3, 4, 5)
    self.second(2, 3, 4, 5, 6)
    self.third(3, 4, 5, 6, 7)

def first(a, b, c, d, e):
    self.storage[1] = a * 10000 + b * 1000 + c * 100 + d * 10 + e

def second(a:11, b:19, c:32, d, e:20):
    self.storage[2] = a * 10000 + b * 1000 + c * 100 + d * 10 + e

def third(a, b, c, d, e):
    self.storage[3] = a * 10000 + b * 1000 + c * 100 + d * 10 + e

def get(k):
    return(self.storage[k])
"""


def test_calls():
    s = tester.state()
    c = s.contract(calltest_code)
    s.send(tester.k0, c, 0, funid=0, abi=[])
    assert [12345] == s.send(tester.k0, c, 0, funid=4, abi=[1])
    assert [23456] == s.send(tester.k0, c, 0, funid=4, abi=[2])
    assert [34567] == s.send(tester.k0, c, 0, funid=4, abi=[3])
    s.send(tester.k0, c, 0, funid=1, abi=[4, 5, 6, 7, 8])
    assert [45678] == s.send(tester.k0, c, 0, funid=4, abi=[1])
    s.send(tester.k0, c, 0, funid=2, abi=['5:11', '6:19', '7:32', 8, '9:20'])
    assert [56789] == s.send(tester.k0, c, 0, funid=4, abi=[2])


storage_object_test_code = """
extern moo = [ping, query_chessboard, query_stats, query_items, query_person, testping, testping2]

data chessboard[8][8]
data users[100](health, x, y, items[5])
data person(head, arms[2](elbow, fingers[5]), legs[2])

def ping():
    self.chessboard[0][0] = 1
    self.chessboard[0][1] = 2
    self.chessboard[3][0] = 3
    self.users[0].health = 100
    self.users[1].x = 15
    self.users[1].y = 12
    self.users[1].items[2] = 9
    self.users[80].health = self
    self.users[80].items[3] = self
    self.person.head = 555
    self.person.arms[0].elbow = 556
    self.person.arms[0].fingers[0] = 557
    self.person.arms[0].fingers[4] = 558
    self.person.legs[0] = 559
    self.person.arms[1].elbow = 656
    self.person.arms[1].fingers[0] = 657
    self.person.arms[1].fingers[4] = 658
    self.person.legs[1] = 659
    self.person.legs[1] += 1000

def query_chessboard(x, y):
    return(self.chessboard[x][y])

def query_stats(u):
    return([self.users[u].health, self.users[u].x, self.users[u].y], 3)

def query_items(u, i):
    return(self.users[u].items[i])

def query_person():
    a = array(20)
    a[0] = self.person.head
    a[1] = self.person.arms[0].elbow
    a[2] = self.person.arms[1].elbow
    a[3] = self.person.legs[0]
    a[4] = self.person.legs[1]
    i = 0
    while i < 5:
        a[5 + i] = self.person.arms[0].fingers[i]
        a[10 + i] = self.person.arms[1].fingers[i]
        i += 1
    return(a, 15)

def testping(x:2, y:7):
    return([self.users[80].health.testping2(x), self.users[80].items[3].testping2(y)], 2)

def testping2(x):
    return(x*x)

"""


def test_storage_objects():
    s = tester.state()
    c = s.contract(storage_object_test_code)
    s.send(tester.k0, c, 0, funid=0, abi=[])
    assert [1] == s.send(tester.k0, c, 0, funid=1, abi=[0, 0])
    assert [2] == s.send(tester.k0, c, 0, funid=1, abi=[0, 1])
    assert [3] == s.send(tester.k0, c, 0, funid=1, abi=[3, 0])
    assert [100, 0, 0] == s.send(tester.k0, c, 0, funid=2, abi=[0])
    assert [0, 15, 12] == s.send(tester.k0, c, 0, funid=2, abi=[1])
    assert [0] == s.send(tester.k0, c, 0, funid=3, abi=[1, 3])
    assert [0] == s.send(tester.k0, c, 0, funid=3, abi=[0, 2])
    assert [9] == s.send(tester.k0, c, 0, funid=3, abi=[1, 2])
    assert [555, 556, 656, 559, 1659,
            557, 0,   0,   0,   558,
            657, 0,   0,   0,  658] == s.send(tester.k0, c, 0, funid=4, abi=[])
    assert [361, 441] == s.send(tester.k0, c, 0, funid=5, abi=['19:2', '21:7'])


infinite_storage_object_test_code = """
data chessboard[][8]
data users[100](health, x, y, items[])
data person(head, arms[](elbow, fingers[5]), legs[2])

def ping():
    self.chessboard[0][0] = 1
    self.chessboard[0][1] = 2
    self.chessboard[3][0] = 3
    self.users[0].health = 100
    self.users[1].x = 15
    self.users[1].y = 12
    self.users[1].items[2] = 9
    self.person.head = 555
    self.person.arms[0].elbow = 556
    self.person.arms[0].fingers[0] = 557
    self.person.arms[0].fingers[4] = 558
    self.person.legs[0] = 559
    self.person.arms[1].elbow = 656
    self.person.arms[1].fingers[0] = 657
    self.person.arms[1].fingers[4] = 658
    self.person.legs[1] = 659

def query_chessboard(x, y):
    return(self.chessboard[x][y])

def query_stats(u):
    return([self.users[u].health, self.users[u].x, self.users[u].y], 3)

def query_items(u, i):
    return(self.users[u].items[i])

def query_person():
    a = array(20)
    a[0] = self.person.head
    a[1] = self.person.arms[0].elbow
    a[2] = self.person.arms[1].elbow
    a[3] = self.person.legs[0]
    a[4] = self.person.legs[1]
    i = 0
    while i < 5:
        a[5 + i] = self.person.arms[0].fingers[i]
        a[10 + i] = self.person.arms[1].fingers[i]
        i += 1
    return(a, 15)
"""


def test_infinite_storage_objects():
    s = tester.state()
    c = s.contract(infinite_storage_object_test_code)
    s.send(tester.k0, c, 0, funid=0, abi=[])
    assert [1] == s.send(tester.k0, c, 0, funid=1, abi=[0, 0])
    assert [2] == s.send(tester.k0, c, 0, funid=1, abi=[0, 1])
    assert [3] == s.send(tester.k0, c, 0, funid=1, abi=[3, 0])
    assert [100, 0, 0] == s.send(tester.k0, c, 0, funid=2, abi=[0])
    assert [0, 15, 12] == s.send(tester.k0, c, 0, funid=2, abi=[1])
    assert [0] == s.send(tester.k0, c, 0, funid=3, abi=[1, 3])
    assert [0] == s.send(tester.k0, c, 0, funid=3, abi=[0, 2])
    assert [9] == s.send(tester.k0, c, 0, funid=3, abi=[1, 2])
    assert [555, 556, 656, 559, 659,
            557, 0,   0,   0,   558,
            657, 0,   0,   0,  658] == s.send(tester.k0, c, 0, funid=4, abi=[])


fail1 = """
data person(head, arms[2](elbow, fingers[5]), legs[2])

x = self.person.arms[0]
"""

fail2 = """
data person(head, arms[2](elbow, fingers[5]), legs[2])

x = self.person.arms[0].fingers
"""

fail3 = """
data person(head, arms[2](elbow, fingers[5]), legs[2])

x = self.person.arms[0].fingers[4][3]
"""

fail4 = """
data person(head, arms[2](elbow, fingers[5]), legs[2])

x = self.person.arms.elbow[0].fingers[4]
"""

fail5 = """
data person(head, arms[2](elbow, fingers[5]), legs[2])

x = self.person.arms[0].fingers[4].nail
"""

fail6 = """
data person(head, arms[2](elbow, fingers[5]), legs[2])

x = self.person.arms[0].elbow.skin
"""


def test_storagevar_fails():
    s = tester.state()
    success1, success2, success3, success4, success5, success6 = \
        0, 0, 0, 0, 0, 0
    try:
        s.contract(fail1)
    except Exception, e:
        success1 = "Storage variable access not deep enough" in str(e)
    assert success1, e

    try:
        s.contract(fail2)
    except Exception, e:
        success2 = "Too few array index lookups" in str(e)
    assert success2, e

    try:
        s.contract(fail3)
    except Exception, e:
        success3 = "Too many array index lookups" in str(e)
    assert success3, e

    try:
        s.contract(fail4)
    except Exception, e:
        success4 = "Too few array index lookups" in str(e)
    assert success4, e

    try:
        s.contract(fail5)
    except Exception, e:
        success5 = "Invalid object member" in str(e)
    assert success5, e

    try:
        s.contract(fail6)
    except Exception, e:
        success6 = "Invalid object member" in str(e)
    assert success6, e


# test_evm = None
# test_sixten = None
# test_returnten = None
# test_namecoin = None
# test_currency = None
# test_data_feeds = None
# test_hedge = None
# test_lifo = None
# test_suicider = None
# test_reverter = None
# test_callcode = None
# test_array = None
# test_array2 = None
# test_array3 = None
# test_calls = None
# test_storage_objects = None
# test_infinite_storage_objects = None
# test_storagevar_fails = None
