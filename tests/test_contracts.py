import os
import pytest
from pyethereum import tester, utils
import serpent

# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
tester.set_logging_level(2)

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
    c = '1231231231231234564564564564561231231231'
    s.block.set_code(c, tester.serpent.compile_lll(sixten_code))
    o1 = s.send(tester.k0, c, 0, [])
    assert o1 == [610]

# Test Serpent's import mechanism

mul2_code = \
    '''
def double(v):
    log(v)
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

def send(to, value):
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
    o1 = s.send(tester.k0, c, 0, funid=1, abi=[tester.a2, 200])
    assert o1 == [1]
    o2 = s.send(tester.k0, c, 0, funid=1, abi=[tester.a2, 900])
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
        c = self.datafeed.get(self.index)
        othervalue = ethvalue * c
        self.fiatValue = othervalue
        self.maturity = block.timestamp + 500
        return([2, othervalue]:a)
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
    self.f1()
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
    self.suicide()
    i = 0
    while i < rounds:
        i += 1

def entry(rounds):
    self.storage[15] = 20
    self.mainloop(rounds, gas=tx.gas - 100)

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
    tester.gas_limit = 8000
    # Run normally: suicide processes, so the attempt to ping the
    # contract fails
    s.send(tester.k0, c, 0, funid=0, abi=[1, 10])
    o2 = s.send(tester.k0, c, 0, funid=0, abi=[2])
    assert o2 == []
    c = s.contract(suicider_code)
    # Run the suicider in such a way that it suicides in a sub-call,
    # then runs out of gas, leading to a revert of the suicide and the
    # storage mutation
    s.send(tester.k0, c, 0, funid=1, abi=[8000])
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
    self.non_recurse(gas=1000)
    self.recurse(gas=1000)

def non_recurse():
    send(7, 9)
    self.storage[8080] = 4040
    self.storage[160160] = 2020

def recurse():
    send(8, 9)
    self.storage[8081] = 4039
    self.storage[160161] = 2019
    self.recurse()
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

def second(a, b, c, d, e):
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
    s.send(tester.k0, c, 0, funid=2, abi=[5, 6, 7, 8, 9])
    assert [56789] == s.send(tester.k0, c, 0, funid=4, abi=[2])


storage_object_test_code = """
extern moo: [ping, query_chessboard, query_stats, query_items, query_person, testping, testping2]

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
    return([self.users[u].health, self.users[u].x, self.users[u].y]:a)

def query_items(u, i):
    return(self.users[u].items[i])

def query_person():
    a = array(15)
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
    return(a:a)

def testping(x, y):
    return([self.users[80].health.testping2(x), self.users[80].items[3].testping2(y)]:a)

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
    assert [361, 441] == s.send(tester.k0, c, 0, funid=5, abi=[19, 21])


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
    return([self.users[u].health, self.users[u].x, self.users[u].y]:a)

def query_items(u, i):
    return(self.users[u].items[i])

def query_person():
    a = array(15)
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
    return(a:a)
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

crowdfund_code = """
data campaigns[2^80](recipient, goal, deadline, contrib_total, contrib_count, contribs[2^50](sender, value))

def create_campaign(id, recipient, goal, timelimit):
    if self.campaigns[id].recipient:
        return(0)
    self.campaigns[id].recipient = recipient
    self.campaigns[id].goal = goal
    self.campaigns[id].deadline = block.timestamp + timelimit

def contribute(id):
    # Update contribution total
    total_contributed = self.campaigns[id].contrib_total + msg.value
    self.campaigns[id].contrib_total = total_contributed

    # Record new contribution
    sub_index = self.campaigns[id].contrib_count
    self.campaigns[id].contribs[sub_index].sender = msg.sender
    self.campaigns[id].contribs[sub_index].value = msg.value
    self.campaigns[id].contrib_count = sub_index + 1

    # Enough funding?
    if total_contributed >= self.campaigns[id].goal:
        send(self.campaigns[id].recipient, total_contributed)
        self.clear(id)
        return(1)

    # Expired?
    if block.timestamp > self.campaigns[id].deadline:
        i = 0
        c = self.campaigns[id].contrib_count
        while i < c:
            send(self.campaigns[id].contribs[i].sender, self.campaigns[id].contribs[i].value)
            i += 1
        self.clear(id)
        return(2)

# Progress report [2, id]
def progress_report(id):
    return(self.campaigns[id].contrib_total)

# Clearing function for internal use
def clear(self, id):
    if self == msg.sender:
        self.campaigns[id].recipient = 0
        self.campaigns[id].goal = 0
        self.campaigns[id].deadline = 0
        c = self.campaigns[id].contrib_count
        self.campaigns[id].contrib_count = 0
        self.campaigns[id].contrib_total = 0
        i = 0
        while i < c:
            self.campaigns[id].contribs[i].sender = 0
            self.campaigns[id].contribs[i].value = 0
            i += 1
"""


def test_crowdfund():
    s = tester.state()
    c = s.contract(crowdfund_code)
    s.send(tester.k0, c, 0, funid=0, abi=[100, 45, 100000, 2])
    s.send(tester.k0, c, 0, funid=0, abi=[200, 48, 100000, 2])
    s.send(tester.k1, c, 1, funid=1, abi=[100])
    assert [1] == s.send(tester.k1, c, 2, funid=2, abi=[100])
    s.send(tester.k2, c, 30000, funid=1, abi=[200])
    s.send(tester.k3, c, 59049, funid=1, abi=[100])
    assert [59050] == s.send(tester.k1, c, 2, funid=2, abi=[100])
    s.send(tester.k4, c, 70001, funid=1, abi=[200])
    assert 100001 == s.block.get_balance(utils.int_to_addr(48))
    mida1 = s.block.get_balance(tester.a1)
    mida3 = s.block.get_balance(tester.a3)
    s.mine(5)
    s.send(tester.k5, c, 1, funid=1, abi=[100])
    assert mida1 + 1 == s.block.get_balance(tester.a1)
    assert mida3 + 59049 == s.block.get_balance(tester.a3)

saveload_code = """

data store[1000]

def kall():
    a = text("sir bobalot to the rescue !!1!1!!1!1")
    save(self.store[0], a, chars=60)
    b = load(self.store[0], chars=60)
    c = load(self.store[0], chars=33)
    return([a[0], a[1], b[0], b[1], c[0], c[1]]:a)

"""

import bitcoin


def test_saveload():
    s = tester.state()
    c = s.contract(saveload_code)
    o = s.send(tester.k0, c, 0, funid=0, abi=[])
    assert o[0] == 0x73697220626f62616c6f7420746f207468652072657363756520212131213121, bitcoin.encode(o[0], 16)
    assert o[1] == 0x2131213100000000000000000000000000000000000000000000000000000000, bitcoin.encode(o[1], 16)
    assert o[2] == 0x73697220626f62616c6f7420746f207468652072657363756520212131213121, bitcoin.encode(o[2], 16)
    assert o[3] == 0x2131213100000000000000000000000000000000000000000000000000000000, bitcoin.encode(o[3], 16)
    assert o[4] == 0x73697220626f62616c6f7420746f207468652072657363756520212131213121, bitcoin.encode(o[4], 16)
    assert o[5] == 0x2100000000000000000000000000000000000000000000000000000000000000, bitcoin.encode(o[5], 16)


sdiv_code = """
def kall():
    return([2^255 / 2^253, 2^255 % 3]:a)
"""


def test_sdiv():
    s = tester.state()
    c = s.contract(sdiv_code)
    assert [-4, -2] == s.send(tester.k0, c, 0, funid=0, abi=[])


basic_argcall_code = """
def argcall(args:a):
    return(args[0] + args[1] * 10 + args[2] * 100)

def argkall(args:a):
    return self.argcall(args)
"""


def test_argcall():
    s = tester.state()
    c = s.contract(basic_argcall_code)
    assert [375] == s.send(tester.k0, c, 0, funid=0, abi=[[5, 7, 3]])
    assert [376] == s.send(tester.k0, c, 0, funid=1, abi=[[6, 7, 3]])

more_complex_argcall_code = """
def argcall(args:a):
    args[0] *= 2
    args[1] *= 2
    return(args:a)

def argkall(args:a):
    return(self.argcall(args, outsz=2):a)
"""


def test_argcall2():
    s = tester.state()
    c = s.contract(more_complex_argcall_code)
    assert [4, 8] == s.send(tester.k0, c, 0, funid=0, abi=[[2, 4]])
    assert [6, 10] == s.send(tester.k0, c, 0, funid=1, abi=[[3, 5]])


sort_code = """
def sort(args:a):
    if len(args) < 2:
        return(args:a)
    h = array(len(args))
    hpos = 0
    l = array(len(args))
    lpos = 0
    i = 1
    while i < len(args):
        if args[i] < args[0]:
            l[lpos] = args[i]
            lpos += 1
        else:
            h[hpos] = args[i]
            hpos += 1
        i += 1
    shrink(h, hpos)
    shrink(l, lpos)
    h = self.sort(h, outsz=hpos)
    l = self.sort(l, outsz=lpos)
    o = array(len(args))
    i = 0
    while i < lpos:
        o[i] = l[i]
        i += 1
    o[lpos] = args[0]
    i = 0
    while i < hpos:
        o[lpos + 1 + i] = h[i]
        i += 1
    return(o:a)
"""


def test_sort():
    s = tester.state()
    c = s.contract(sort_code)
    a1 = s.send(tester.k0, c, 0, funid=0, abi=[[9]])
    assert a1 == [9]
    a2 = s.send(tester.k0, c, 0, funid=0, abi=[[9, 5]])
    assert a2 == [5, 9]
    a3 = s.send(tester.k0, c, 0, funid=0, abi=[[9, 3, 5]])
    assert a3 == [3, 5, 9]
    a4 = s.send(tester.k0, c, 0, funid=0, abi=[[80, 24, 234, 112, 112, 29]])
    assert a4 == [24, 29, 80, 112, 112, 234]

filename9 = "mul2_qwertyuioplkjhgfdsabarbar.se"

sort_tester_code = \
    '''
extern sorter: [sort:a]
data sorter

def init():
    self.sorter = create("%s")

def test(args:a):
    return(self.sorter.sort(args, outsz=len(args)):a)
''' % filename9


def test_indirect_sort():
    s = tester.state()
    open(filename9, 'w').write(sort_code)
    c = s.contract(sort_tester_code)
    a1 = s.send(tester.k0, c, 0, funid=0, abi=[[80, 24, 234, 112, 112, 29]])
    assert a1 == [24, 29, 80, 112, 112, 234]


multiarg_code = """
def kall(a:a, b, c:a, d:s, e):
    x = a[0] + 10 * b + 100 * c[0] + 1000 * a[1] + 10000 * c[1] + 100000 * e
    return([x, getch(d, 0) + getch(d, 1) + getch(d, 2), len(d)]:a)
"""


def test_multiarg_code():
    s = tester.state()
    c = s.contract(multiarg_code)
    o = s.send(tester.k0, c, 0, funid=0,
               abi=[[1, 2, 3], 4, [5, 6, 7], "\"doge\"", 8])
    assert o == [862541, ord('d') + ord('o') + ord('g'), 4]

peano_code = """
macro padd($x, psuc($y)):
    psuc(padd($x, $y))

macro padd($x, z()):
    $x

macro dec(psuc($x)):
    dec($x) + 1

macro dec(z()):
    0

macro pmul($x, z()):
    z()

macro pmul($x, psuc($y)):
    padd(pmul($x, $y), $x)

macro pexp($x, z()):
    one()

macro pexp($x, psuc($y)):
    pmul($x, pexp($x, $y))

macro fac(z()):
    one()

macro fac(psuc($x)):
    pmul(psuc($x), fac($x))

macro one():
    psuc(z())

macro two():
    psuc(psuc(z()))

macro three():
    psuc(psuc(psuc(z())))

macro five():
    padd(three(), two())

return([dec(pmul(three(), pmul(three(), three()))), dec(fac(five()))]:a)

"""


def test_macros():
    s = tester.state()
    c = s.contract(peano_code)
    assert s.send(tester.k0, c, 0, []) == [27, 120]


type_code = """
type f: [a, b, c, d, e]

macro f($a) + f($b):
    f(add($a, $b))

macro f($a) - f($b):
    f(sub($a, $b))

macro f($a) * f($b):
    f(mul($a, $b) / 10000)

macro f($a) / f($b):
    f(sdiv($a * 10000, $b))

macro f($a) % f($b):
    f(smod($a, $b))

macro f($v) = f($w):
    $v = $w

macro(10) f($a):
    $a / 10000

macro fify($a):
    f($a * 10000)

a = fify(5)
b = fify(2)
c = a / b
e = c + (a / b)
return(e)
"""


def test_types():
    s = tester.state()
    c = s.contract(type_code)
    assert s.send(tester.k0, c, 0, []) == [5]

sha256_code = """
return([sha256(0, 0), sha256(3), sha256(text("dog"), chars=3)]:a)
"""


def test_sha256():
    s = tester.state()
    c = s.contract(sha256_code)
    assert s.send(tester.k0, c, 0, []) == [
        0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 - 2**256,
        0xd9147961436944f43cd99d28b2bbddbf452ef872b30c8279e255e7daafc7f946 - 2**256,
        0xcd6357efdd966de8c0cb2f876cc89ec74ce35f0968e11743987084bd42fb8944 - 2**256
    ]

types_in_functions_code = """
type fixedp: [a, b]

macro fixedp($x) * fixedp($y):
    fixedp($x * $y / 2^64)

macro fixedp($x) / fixedp($y):
    fixedp($x * 2^64 / $y)

macro raw_unfixedp(fixedp($x)):
    $x / 2^64

macro fixify($x):
    fixedp($x * 2^64)

macro fixedp($x) = fixedp($y):
    $x = $y

def sqrdiv(a, b):
    return(raw_unfixedp((a / b) * (a / b)))
"""


def test_types_in_functions():
    s = tester.state()
    c = s.contract(types_in_functions_code)
    assert s.send(tester.k0, c, 0, funid=0, abi=[25, 2]) == [156]


more_infinites_code = """
data a[](b, c)

def testVerifyTx():

    self.a[0].b = 33

    self.a[0].c = 55

    return(self.a[0].b)
"""


def test_more_infinites():
    s = tester.state()
    c = s.contract(more_infinites_code)
    assert s.send(tester.k0, c, 0, funid=0, abi=[]) == [33]


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
# test_saveload = None
# test_crowdfund = None
# test_sdiv = None
# test_argcall = None
# test_argcall2 = None
# test_sort = None
# test_indirect_sort = None
# test_multiarg_code = None
# test_macros = None
# test_types = None
# test_sha256 = None
# test_types_in_functions = None
# test_more_infinites = None
