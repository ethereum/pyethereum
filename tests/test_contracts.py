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
x = create("%s")
return(call(x, 0, 5))
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
    if !contract.storage[k]:
        contract.storage[k] = v
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
def init():
    contract.storage[msg.sender] = 1000

def query(addr):
    return(contract.storage[addr])

def send(to:29, value:31):
    from = msg.sender
    fromvalue = contract.storage[from]
    if fromvalue >= value:
        contract.storage[from] = fromvalue - value
        contract.storage[to] = contract.storage[to] + value
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
def init():
    contract.storage[1000] = 1
    contract.storage[1001] = msg.sender

def set(k, v):
    if msg.sender == contract.storage[1001]:
        contract.storage[k] = v
        return(1)
    else:
        return(0)

def get(k):
    return(contract.storage[k])
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
def main(datafeed, index):
    if !contract.storage[1000]:
        contract.storage[1000] = msg.sender
        contract.storage[1002] = msg.value
        contract.storage[1003] = datafeed
        contract.storage[1004] = index
        return(1)
    elif !contract.storage[1001]:
        ethvalue = contract.storage[1002]
        if msg.value >= ethvalue:
            contract.storage[1001] = msg.sender
        c = call(contract.storage[1003], 1, data=[contract.storage[1004]], datasz=1)
        othervalue = ethvalue * c
        contract.storage[1005] = othervalue
        contract.storage[1006] = block.timestamp + 500
        return([2,othervalue],2)
    else:
        othervalue = contract.storage[1005]
        ethvalue = othervalue / call(contract.storage[1003], 1, contract.storage[1004])
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
    contract.storage[0] = 10

def f1():
    contract.storage[0] += 1

def f2():
    contract.storage[0] *= 10
    call(contract.address, 0)
    contract.storage[0] *= 10

def f3():
    return(contract.storage[0])
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
    contract.storage[15] = 40
    call(contract.address, 3)
    i = 0
    while i < rounds:
        i += 1

def entry(rounds):
    contract.storage[15] = 20
    call(contract.address, 0, rounds, gas=tx.gas - 100)

def ping_ten():
    return(10)

def suicide():
    suicide(0)

def ping_storage15():
    return(contract.storage[15])
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
    call(contract.address, 1, gas=1000)
    call(contract.address, 2, gas=1000)

def non_recurse():
    send(7, 9)
    contract.storage[8080] = 4040
    contract.storage[160160] = 2020

def recurse():
    send(8, 9)
    contract.storage[8081] = 4039
    contract.storage[160161] = 2019
    call(contract.address, 2)
    contract.storage["waste_some_gas"] = 0
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
    contract.storage[1] += x
'''

filename2 = "stateless_qwertyuioplkjhgfdsa.se"

callcode_test_code = \
    '''
x = create("%s")
call(x, 0, 6)
call_code(x, 0, 4)
call_code(x, 0, 60)
call(x, 0, 40)
return(contract.storage[1])
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
    call(contract.address, 1, 1, 2, 3, 4, 5)
    call(contract.address, 2, 2, 3, 4, 5, 6)
    call(contract.address, 3, 3, 4, 5, 6, 7)

def first(a, b, c, d, e):
    contract.storage[1] = a * 10000 + b * 1000 + c * 100 + d * 10 + e

def second(a:11, b:19, c:32, d, e:20):
    contract.storage[2] = a * 10000 + b * 1000 + c * 100 + d * 10 + e

def third(a, b, c, d, e):
    contract.storage[3] = a * 10000 + b * 1000 + c * 100 + d * 10 + e

def get(k):
    return(contract.storage[k])
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
