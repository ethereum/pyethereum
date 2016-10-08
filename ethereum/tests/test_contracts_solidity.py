import os
from os import path
import binascii
import pytest
import bitcoin
from secp256k1 import PrivateKey


from ethereum import tester
from ethereum import abi
from ethereum import utils
from ethereum import _solidity
from ethereum._solidity import get_solidity

solidity = get_solidity()

SOLIDITY_AVAILABLE = get_solidity() is not None
skip_if_no_solidity_compiler = pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')


@skip_if_no_solidity_compiler
def test_bool():
    code = '''
contract testme {
    function main(bool b) returns (bool) {
        return b;
    }
}
'''

    s = tester.state()
    c = s.abi_contract(code, language='solidity')
    assert c.main(True) is True
    assert c.main(False) is False


@skip_if_no_solidity_compiler
def test_evm1():
    code = '''
contract testme {
    function main(uint a, uint b) returns (uint) {
        return a ** b;
    }
}
'''

    translator = abi.ContractTranslator(solidity.mk_full_signature(code))
    s = tester.state()
    c = s.abi_contract(code, language='solidity')
    assert c.main(2, 5) == 32


@skip_if_no_solidity_compiler
def test_constructor():
    contract_code = '''
contract testme {
    uint cnt;

    function testme() {
        cnt = 10;
    }

    function ping() returns (uint) {
        cnt = cnt + 1;
        return cnt;
    }
}
'''

    s = tester.state()
    c = s.abi_contract(contract_code, language='solidity')

    assert c.ping() == 11;
    assert c.ping() == 12;


# Test import mechanism
@skip_if_no_solidity_compiler
def test_returnten():
    mul2_code = '''
contract mul2 {
    function double(uint v) returns (uint) {
        return v * 2;
    }
}
'''
    returnten_code = '''
%s // mul2_code

contract testme {
    function main() returns (uint) {
        mul2 x = new mul2();
        return x.double(5);
    }
}''' % mul2_code
    s = tester.state()
    c = s.abi_contract(returnten_code, language='solidity')
    assert c.main() == 10


# Test inherit
@skip_if_no_solidity_compiler
def test_inherit():
    mul2_code = '''
contract mul2 {
    function double(uint v) returns (uint) {
        return v * 2;
    }
}
'''
    returnten_code = '''
%s // mul2_code

contract testme is mul2 {
    function main() returns (uint) {
        return double(5);
    }
}''' % mul2_code
    s = tester.state()
    c = s.abi_contract(returnten_code, language='solidity')
    assert c.main() == 10


# Test inherit
@skip_if_no_solidity_compiler
def test_external():
    mul2_code = '''
contract mul2 {
    function double(uint v) returns (uint) {
        return v * 2;
    }
}
'''
    returnten_code = '''
%s // mul2_code

contract testme {
    address mymul2;

    function setmul2(address _mul2) {
        mymul2 = _mul2;
    }

    function main() returns (uint) {
        return mul2(mymul2).double(5);
    }
}''' % mul2_code
    s = tester.state()

    c1 = s.abi_contract(mul2_code, language='solidity')
    c = s.abi_contract(returnten_code, language='solidity')

    c.setmul2(c1.address)
    assert c.main() == 10


@skip_if_no_solidity_compiler
def test_this_call():
    """test the difference between `this.fn()` and `fn()`; `this.fn()` should use `CALL`, which costs more gas"""
    returnten_code = '''
contract testme {
    function double(uint v) returns (uint) {
        return v * 2;
    }

    function doubleexternal() returns (uint) {
        return this.double(5);
    }

    function doubleinternal() returns (uint) {
        return double(5);
    }
}'''
    s = tester.state()

    c = s.abi_contract(returnten_code, sender=tester.k1, language='solidity')
    b = s.block.get_balance(tester.a1)
    assert c.doubleinternal(sender=tester.k1) == 10
    s.mine(1, coinbase=tester.a0)
    internal_gascost = b - s.block.get_balance(tester.a1)

    b = s.block.get_balance(tester.a1)
    assert c.doubleexternal(sender=tester.k1) == 10
    s.mine(1, coinbase=tester.a0)
    external_gascost = b - s.block.get_balance(tester.a1)

    assert internal_gascost < external_gascost, "external call should cost more gas"


# Test inherit
@skip_if_no_solidity_compiler
def test_constructor_args():
    mul2_code = '''
contract mul2 {
    function double(uint v) returns (uint) {
        return v * 2;
    }
}
'''
    returnten_code = '''
%s // mul2_code

contract testme {
    address mymul2;

    function testme(address _mul2) {
        mymul2 = _mul2;
    }

    function main() returns (uint) {
        return mul2(mymul2).double(5);
    }
}''' % mul2_code
    s = tester.state()

    c1 = s.abi_contract(mul2_code, language='solidity')
    c = s.abi_contract(returnten_code, constructor_parameters=[c1.address], language='solidity')

    assert c.main() == 10


# Test a simple namecoin implementation
@skip_if_no_solidity_compiler
def test_namecoin():
    namecoin_code = '''
contract namecoin {
    mapping(string => uint) data;

    function set(string k, uint v) returns (uint) {
        if (data[k] == 0) {
            data[k] = v;
            return 1;
        } else {
            return 0;
        }
    }

    function get(string k) returns (uint) {
        return data[k];
    }
}
'''

    s = tester.state()
    c = s.abi_contract(namecoin_code, language='solidity')

    o1 = c.set("george", 45)
    assert o1 == 1
    assert c.get("george")

    o2 = c.set("george", 20)
    assert o2 == 0
    assert c.get("george")

    o3 = c.set("harry", 60)
    assert o3 == 1
    assert c.get("harry")


# Test a simple text return
@skip_if_no_solidity_compiler
def test_simple_text_return():
    simple_text_return_code = '''
contract testme {
    function returntext() returns (string) {
        return "testing123";
    }
}
'''

    s = tester.state()
    c = s.abi_contract(simple_text_return_code, language='solidity')
    assert c.returntext() == utils.to_string("testing123")


# Test a simple send
@skip_if_no_solidity_compiler
def test_send():
    send_code = '''
contract testme {
    function send(uint v) {
        msg.sender.send(v);
    }
}
'''

    s = tester.state()
    c = s.abi_contract(send_code, language='solidity')

    startbalance = s.block.get_balance(tester.a2)
    value = 1000000  # amount send into the contract
    v = 30000  # v= for the contract, amount we get back
    gcost = 28414  # gascost
    c.send(v, value=value, sender=tester.k2)
    assert s.block.get_balance(tester.a2) == startbalance - gcost - value + v


@skip_if_no_solidity_compiler
def test_send_arg():
    send_arg_code = '''
contract testme {
    function send(address s, uint v) {
        s.send(v);
    }
}
'''

    s = tester.state()
    c = s.abi_contract(send_arg_code, language='solidity')

    startbalance = s.block.get_balance(tester.a2)
    v = 30000  # v = for the contract, amount we get back
    c.send(tester.a2, v, value=10000000, sender=tester.k1)
    assert s.block.get_balance(tester.a2) == startbalance + v


@skip_if_no_solidity_compiler
def test_send_hardcoded():
    send_hardcoded_code = '''
contract testme {
    function send(uint v) {
        address s = address(%s);
        s.send(v);
    }
}
'''

    s = tester.state()
    c = s.abi_contract(send_hardcoded_code % (utils.big_endian_to_int(tester.a2), ), language='solidity')

    startbalance = s.block.get_balance(tester.a2)
    v = 30000  # v = for the contract, amount we get back
    c.send(v, value=10000000, sender=tester.k1)
    assert s.block.get_balance(tester.a2) == startbalance + v


# Test a simple currency implementation
@skip_if_no_solidity_compiler
def test_currency():
    currency_code = '''
contract testme {
    mapping(address => uint) balances;

    function testme() {
        balances[msg.sender] = 1000;
    }

    function query(address a) returns (uint) {
        return balances[a];
    }

    function send(address to, uint value) returns (uint) {
        address from = msg.sender;

        if (balances[msg.sender] >= value) {
            balances[msg.sender] = balances[msg.sender] - value;
            balances[to] = balances[to] + value;

            return 1;
        } else {
            return 0;
        }
    }
}
'''

    s = tester.state()
    c = s.abi_contract(currency_code, sender=tester.k0, language='solidity')

    o1 = c.query(tester.a0)
    assert o1 == 1000
    o1 = c.send(tester.a2, 200, sender=tester.k0)
    assert o1 == 1
    o2 = c.send(tester.a2, 900, sender=tester.k0)
    assert o2 == 0
    o3 = c.query(tester.a0)
    assert o3 == 800
    o4 = c.query(tester.a2)
    assert o4 == 200


# Test a data feed
data_feed_code = '''
contract datafeedContract {
    address creator;
    mapping(uint => uint) values;

    function datafeedContract() {
        creator = msg.sender;
    }

    function set(uint k, uint v) returns (uint) {
        if (msg.sender == creator) {
            values[k] = v;
            return 1;
        } else {
            return 0;
        }
    }

    function get(uint k) returns (uint) {
        return values[k];
    }
}
'''


@skip_if_no_solidity_compiler
def test_data_feeds():
    s = tester.state()
    c = s.abi_contract(data_feed_code, sender=tester.k0, language='solidity')
    o2 = c.get(500)
    assert o2 == 0
    o3 = c.set(500, 19, sender=tester.k0)
    assert o3 == 1
    o4 = c.get(500)
    assert o4 == 19
    o5 = c.set(500, 726, sender=tester.k1)
    assert o5 == 0
    o6 = c.set(500, 726)
    assert o6 == 1
    return s, c


# Test an example hedging contract, using the data feed.
# This tests contracts calling other contracts
@skip_if_no_solidity_compiler
def test_hedge():
    hedge_code = '''
%s

contract testme {
    address partyone;
    address partytwo;
    uint hedgeValue;
    address datafeed;
    uint index;
    uint fiatValue;
    uint maturity;

    function main(address _datafeed, uint _index) returns (uint) {
        // step 1; setup partyone
        if (partyone == 0x0) {
            partyone = msg.sender;
            hedgeValue = msg.value;
            datafeed = _datafeed;
            index = _index;

            return 1;
        } else if (partytwo == 0x0) {
            if (msg.value >= hedgeValue) {
                partytwo = msg.sender;
            }

            uint c = datafeedContract(datafeed).get(index);
            fiatValue = hedgeValue * c;
            maturity = block.timestamp + 500;

            return fiatValue;
        } else {
            uint otherValue = fiatValue;
            uint ethValue = otherValue / datafeedContract(datafeed).get(index);

            if (ethValue > this.balance) {
                partyone.send(this.balance);
                return 3;
            } else if (block.timestamp > maturity) {
                partytwo.send(this.balance - ethValue);
                partyone.send(ethValue);

                return 4;
            } else {
                return 5;
            }
        }
    }
}
''' % data_feed_code

    # run previous test to setup data feeds
    s, c = test_data_feeds()

    # create contract
    c2 = s.abi_contract(hedge_code, sender=tester.k0, language='solidity')

    # Have the first party register, sending 10000000 XCPtoshi and asking for a hedge using currency code 500
    o1 = c2.main(c.address, 500, value=10000000, sender=tester.k0)
    assert o1 == 1

    # Have the second party register.
    # It should receive the amount of units of the second currency that it is entitled to.
    # Note that from the previous test this is set to 726
    o2 = c2.main(0, 0, value=10000000, sender=tester.k2)
    assert o2 == 7260000000

    # SNAPSHOT
    snapshot = s.snapshot()

    # Set the price of the asset down to 300 wei, through the data feed contract
    o3 = c.set(500, 300)
    assert o3 == 1

    # Finalize the contract. Expect code 3, meaning a margin call
    o4 = c2.main(0, 0)
    assert o4 == 3

    # REVERT TO SNAPSHOT
    s.revert(snapshot)

    # Don't change the price. Finalize, and expect code 5, meaning the time has not expired yet
    o5 = c2.main(0, 0)
    assert o5 == 5

    # Mine 100 blocks
    s.mine(100, tester.a3)

    # Expect code 4, meaning a normal execution where both get their share
    o6 = c2.main(0, 0)
    assert o6 == 4


# Test the LIFO nature of call
@skip_if_no_solidity_compiler
def test_lifo():
    arither_code = '''
contract testme {
    uint r;

    function testme() {
        r = 10;
    }

    function f1() {
        r += 1;
    }

    function f2() {
        r *= 10;
        f1();
        r *= 10;
    }

    function f3() returns (uint) {
        return r;
    }
}
'''

    s = tester.state()
    c = s.abi_contract(arither_code, language='solidity')
    c.f2()
    assert c.f3() == 1010


@skip_if_no_solidity_compiler
def test_oog():
    contract_code = '''
contract testme {
    mapping(uint => uint) data;

    function loop(uint rounds) returns (uint) {
        uint i = 0;
        while (i < rounds) {
            data[i] = i;
            i++;
        }

        return i;
    }
}
'''
    s = tester.state()
    c = s.abi_contract(contract_code, language='solidity')
    assert c.loop(5) == 5

    e = None
    try:
        c.loop(500)
    except tester.TransactionFailed as _e:
        e = _e
    assert e and isinstance(e, tester.TransactionFailed)


@skip_if_no_solidity_compiler
def test_subcall_suicider():
    internal_code = '''
contract testmeinternal {
    address creator;
    uint r;

    function testmeinternal() {
        creator = msg.sender;
    }

    function set(uint v) {
        r = v;
    }

    function get() returns (uint) {
        return r;
    }

    function killme() {
        selfdestruct(creator);
    }
}
'''
    external_code = '''
contract testme {
    address subcontract;
    mapping(uint => uint) data;

    function testme(address _subcontract) {
        subcontract = _subcontract;
    }

    function killandloop(uint rounds) returns (uint) {
        testmeinternal(subcontract).killme();
        return loop(rounds);
    }

    function loop(uint rounds) returns (uint) {
        uint i = 0;
        while (i < rounds) {
            i++;
            data[i] = i;
        }

        return i;
    }
}
'''

    s = tester.state()

    # test normal suicide path
    internal = s.abi_contract(internal_code, language='solidity')
    external = s.abi_contract(internal_code + "\n" + external_code, constructor_parameters=[internal.address], language='solidity')
    internal.set(60)
    assert internal.get() == 60
    assert external.killandloop(10) == 10
    assert internal.get() is None

    # test suicide -> oog path, shouldn't suicide
    internal = s.abi_contract(internal_code, language='solidity')
    external = s.abi_contract(internal_code + "\n" + external_code, constructor_parameters=[internal.address], language='solidity')
    internal.set(60)
    assert internal.get() == 60

    e = None
    try:
        external.killandloop(500)
    except tester.TransactionFailed as _e:
        e = _e
    assert e and isinstance(e, tester.TransactionFailed)
    assert internal.get() == 60


@skip_if_no_solidity_compiler
def test_array():
    array_code = '''
contract testme {
    function main() returns (uint[]) {
        uint[] memory a = new uint[](1);
        a[0] = 1;
        return a;
    }
}
'''
    s = tester.state()
    c = s.abi_contract(array_code, language='solidity')
    assert c.main() == [1]



@skip_if_no_solidity_compiler
def test_array2():
    array_code2 = """
contract testme {
    function main() returns (uint[3]) {
        uint[3] memory a;
        return a;
    }
}
"""
    s = tester.state()
    c = s.abi_contract(array_code2, language='solidity')
    assert c.main() == [0, 0, 0]



@skip_if_no_solidity_compiler
def test_array3():
    array_code3 = """
contract testme {
    function main() returns (uint[]) {
        uint[] memory a = new uint[](3);
        return a;
    }
}
"""
    s = tester.state()
    c = s.abi_contract(array_code3, language='solidity')
    assert c.main() == [0, 0, 0]


@skip_if_no_solidity_compiler
def test_calls():
    calltest_code = """
contract testme {
    mapping(uint => uint) data;

    function main() {
        this.first(1, 2, 3, 4, 5);
        this.second( 2, 3, 4, 5, 6);
        this.third(3, 4, 5, 6, 7);
    }

    function first(uint a, uint b, uint c, uint d, uint e) {
        data[1] = a * 10000 + b * 1000 + c * 100 + d * 10 + e;
    }

    function second(uint a, uint b, uint c, uint d, uint e) {
        data[2] = a * 10000 + b * 1000 + c * 100 + d * 10 + e;
    }

    function third(uint a, uint b, uint c, uint d, uint e) {
        data[3] = a * 10000 + b * 1000 + c * 100 + d * 10 + e;
    }

    function get(uint k) returns (uint) {
        return data[k];
    }
}
"""

    s = tester.state()
    c = s.abi_contract(calltest_code, language='solidity')
    c.main()
    assert 12345 == c.get(1)
    assert 23456 == c.get(2)
    assert 34567 == c.get(3)
    c.first(4, 5, 6, 7, 8)
    assert 45678 == c.get(1)
    c.second(5, 6, 7, 8, 9)
    assert 56789 == c.get(2)


@skip_if_no_solidity_compiler
def test_storage_objects():
    storage_object_test_code = """
contract testme {

    struct User {
        uint health;
        uint x;
        uint y;
        uint[5] items;
    }

    struct Arm {
        uint elbow;
        uint[5] fingers;
    }

    struct Person {
        uint head;
        Arm[2] arms;
        uint[2] legs;
    }

    uint[8][8] chessboard;
    User[100] users;
    Person person;

    function ping() {
        chessboard[0][0] = 1;
        chessboard[0][1] = 2;
        chessboard[3][0] = 3;
        users[0].health = 100;
        users[1].x = 15;
        users[1].y = 12;
        users[1].items[2] = 9;
        users[80].health = 10;
        users[80].items[3] = 11;
        person.head = 555;
        person.arms[0].elbow = 556;
        person.arms[0].fingers[0] = 557;
        person.arms[0].fingers[4] = 558;
        person.legs[0] = 559;
        person.arms[1].elbow = 656;
        person.arms[1].fingers[0] = 657;
        person.arms[1].fingers[4] = 658;
        person.legs[1] = 659;
        person.legs[1] += 1000;
    }

    function query_chessboard(uint x, uint y) returns (uint) {
        return chessboard[x][y];
    }

    function query_stats(uint u) returns (uint, uint, uint) {
        return (users[u].health, users[u].x, users[u].y);
    }

    function query_items(uint u, uint i) returns (uint) {
        return users[u].items[i];
    }

    function query_person() returns (uint[15]) {
        uint[15] a;
        a[0] = person.head;
        a[1] = person.arms[0].elbow;
        a[2] = person.arms[1].elbow;
        a[3] = person.legs[0];
        a[4] = person.legs[1];

        uint i = 0;
        while (i < 5) {
            a[5 + i] = person.arms[0].fingers[i];
            a[10 + i] = person.arms[1].fingers[i];
            i += 1;
        }

        return a;
    }
}
"""
    s = tester.state()
    c = s.abi_contract(storage_object_test_code, language='solidity')
    c.ping()
    assert 1 == c.query_chessboard(0, 0)
    assert 2 == c.query_chessboard(0, 1)
    assert 3 == c.query_chessboard(3, 0)
    assert [100, 0, 0] == c.query_stats(0)
    assert [0, 15, 12] == c.query_stats(1)
    assert 0 == c.query_items(1, 3)
    assert 0 == c.query_items(0, 2)
    assert 9 == c.query_items(1, 2)
    assert [555, 556, 656, 559, 1659,
            557, 0, 0, 0, 558,
            657, 0, 0, 0, 658] == c.query_person()


@skip_if_no_solidity_compiler
def test_crowdfund():
    """
    test crowdfund smart contract, keep in mind that we create a new block for every contract call
     so we need a generous TTL
    """
    crowdfund_code = """
contract testme {
    struct Contrib {
        address sender;
        uint value;
    }

    struct Campaign {
        address recipient;
        uint goal;
        uint deadline;
        uint contrib_total;
        uint contrib_count;
        mapping(uint => Contrib) contribs;
    }

    mapping(uint => Campaign) campaigns;

    function create_campaign(uint id, address recipient, uint goal, uint timelimit) returns (uint) {
        if (campaigns[id].recipient != 0x0) {
            return 0;
        }

        campaigns[id] = Campaign(recipient, goal, block.timestamp + timelimit, 0, 0);
        return 1;
    }

    function contribute(uint id) returns (uint) {
        // Update contribution total
        uint total_contributed = campaigns[id].contrib_total + msg.value;
        campaigns[id].contrib_total = total_contributed;

        // Record new contribution
        uint sub_index = campaigns[id].contrib_count;
        campaigns[id].contribs[sub_index] = Contrib(msg.sender, msg.value);
        campaigns[id].contrib_count = sub_index + 1;

        // Enough funding?
        if (total_contributed >= campaigns[id].goal) {
            campaigns[id].recipient.send(total_contributed);
            clear(id);
            return 1;
        }

        // Expired?
        if (block.timestamp > campaigns[id].deadline) {
            uint i = 0;
            uint c = campaigns[id].contrib_count;
            while (i < c) {
                campaigns[id].contribs[i].sender.send(campaigns[id].contribs[i].value);
                i += 1;
            }
            clear(id);
            return 2;
        }
    }

    // Progress report [2, id]
    function progress_report(uint id) returns (uint) {
        return campaigns[id].contrib_total;
    }

    // Clearing function for internal use
    function clear(uint id) private {
        delete campaigns[id];
    }
}
"""

    s = tester.state()
    c = s.abi_contract(crowdfund_code, language='solidity')  # tXsNynQTeMkCQVBKMVnHwov1rTjpUYdVSt

    # Create a campaign with id 100, recipient '45', target 100000 and ttl 20 blocks
    assert c.create_campaign(100, 45, 100000, 2) == 1
    # Create a campaign with id 200, recipient '48', target 100000 and ttl 20 blocks
    assert c.create_campaign(200, 48, 100000, 2) == 1

    # Make some contributions to campaign 100
    assert c.contribute(100, value=1, sender=tester.k1) == 0  # mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns
    assert 1 == c.progress_report(100)
    assert c.contribute(100, value=59049, sender=tester.k2) == 0 # mqPCfvqTfYctXMUfmniXeG2nyaN8w6tPmj
    assert 59050 == c.progress_report(100)

    # Make some contributions to campaign 200
    assert c.contribute(200, value=30000, sender=tester.k3) == 0  # myAtcJEHAsDLbTkai6ipWDZeeL7VkxXsiM
    assert 30000 == c.progress_report(200)

    # This contribution should trigger the delivery
    assert c.contribute(200, value=70001, sender=tester.k4) == 1  # munimLLHjPhGeSU5rYB2HN79LJa8bRZr5b

    # Expect the 100001 units to be delivered to the destination account for campaign 2
    assert 100001 == s.block.get_balance(utils.int_to_addr(48))

    # Mine some blocks to test expire the campaign, not sure how many are needed so just do 20
    mida1 = s.block.get_balance(tester.a1)
    mida3 = s.block.get_balance(tester.a2)

    # Mine 5 blocks to expire the campaign
    s.mine(5)

    # Ping the campaign after expiry to trigger the refund
    assert c.contribute(100, value=1, sender=tester.k0) == 2

    # Create the campaign again, should have been deleted
    assert c.create_campaign(100, 45, 100000, 2) == 1

    # Expect refunds
    assert mida1 + 1 == s.block.get_balance(tester.a1)
    assert mida3 + 59049 == s.block.get_balance(tester.a2)


@skip_if_no_solidity_compiler
def test_ints():
    sdiv_code = """
contract testme {
    function addone256(uint256 k) returns (uint256) {
        return k + 1;
    }
    function subone256(uint256 k) returns (uint256) {
        return k - 1;
    }
    function addone8(uint8 k) returns (uint8) {
        return k + 1;
    }
    function subone8(uint8 k) returns (uint8) {
        return k - 1;
    }
}
"""

    s = tester.state()
    c = s.abi_contract(sdiv_code, language='solidity')

    # test uint8
    MAX8 = 255  # 2 ** 8 - 1
    assert c.addone8(1) == 2
    assert c.addone8(MAX8 - 1) == MAX8
    assert c.addone8(MAX8) == 0
    assert c.subone8(1) == 0
    assert c.subone8(0) == MAX8

    # test uint256
    MAX256 = 115792089237316195423570985008687907853269984665640564039457584007913129639935  # 2 ** 256 - 1
    assert c.addone256(1) == 2
    assert c.addone256(MAX8 - 1) == MAX8
    assert c.addone256(MAX8) == MAX8 + 1
    assert c.addone256(MAX256 - 1) == MAX256
    assert c.addone256(MAX256) == 0
    assert c.subone256(1) == 0
    assert c.subone256(0) == MAX256


@skip_if_no_solidity_compiler
def test_sdiv():
    sdiv_code = """
contract testme {
    function kall() returns (uint, uint, uint) {
        return (2 ** 255, 2 ** 255 / 2 ** 253, 2 ** 255 % 3);
    }
}
"""

    s = tester.state()
    c = s.abi_contract(sdiv_code, language='solidity')
    assert [57896044618658097711785492504343953926634992332820282019728792003956564819968, 4, 2] == c.kall()


@skip_if_no_solidity_compiler
def test_argcall():
    basic_argcall_code = """
contract testme {
    function argcall(uint[] args) returns (uint) {
        return args[0] + args[1] * 10 + args[2] * 100;
    }

    function argkall(uint[] args) returns (uint) {
        return this.argcall(args);
    }
}
"""

    s = tester.state()
    c = s.abi_contract(basic_argcall_code, language='solidity')
    assert 375 == c.argcall([5, 7, 3])
    assert 376 == c.argkall([6, 7, 3])


slice_code = """
contract slicer {
    function slice(uint[] arr, uint start, uint len) returns (uint[]) {
        if (len > start + arr.length) {
            len = arr.length - start;
        }

        uint m = start + len;
        if (m > arr.length) {
            m = arr.length;
        }

        uint[] memory r = new uint[](len);

        uint i = 0;
        uint c = 0;
        while (i < m) {
            if (i >= start) {
                r[c] = arr[i];
                c++;
            }

            i++;
        }

        return r;
    }
}
"""


@pytest.mark.timeout(100)
@skip_if_no_solidity_compiler
def test_slice():
    s = tester.state()
    c = s.abi_contract(slice_code, language='solidity')
    assert c.slice([1, 2, 3, 4], 1, 2) == [2, 3]
    assert c.slice([1, 2, 3, 4], 1, 3) == [2, 3, 4]
    assert c.slice([1, 2, 3, 4], 1, 10) == [2, 3, 4]


sort_code = """
%s // slice_code

contract sorter is slicer {
    function sort(uint[] args) returns (uint[]) {
        if (args.length < 2) {
            return args;
        }

        uint[] memory h = new uint[](args.length);
        uint hpos = 0;
        uint[] memory l = new uint[](args.length);
        uint lpos = 0;

        uint i = 1;
        while (i < args.length) {
            if (args[i] < args[0]) {
                l[lpos] = args[i];
                lpos += 1;
            } else {
                h[hpos] = args[i];
                hpos += 1;
            }

            i += 1;
        }

        uint[] memory x = slice(h, 0, hpos);
        h = sort(x);
        l = sort(slice(l, 0, lpos));

        uint[] memory o = new uint[](args.length);

        i = 0;
        while (i < lpos) {
            o[i] = l[i];
            i += 1;
        }

        o[lpos] = args[0];
        i = 0;
        while (i < hpos) {
            o[lpos + 1 + i] = h[i];
            i += 1;
        }

        return o;
    }
}
""" % slice_code


@pytest.mark.timeout(100)
@skip_if_no_solidity_compiler
def test_sort():
    s = tester.state()
    c = s.abi_contract(sort_code, language='solidity')
    assert c.sort([9]) == [9]
    assert c.sort([9, 5]) == [5, 9]
    assert c.sort([9, 3, 5]) == [3, 5, 9]
    assert c.sort([80, 234, 112, 112, 29]) == [29, 80, 112, 112, 234]


sort_tester_code = \
    '''
%s // sort_code

contract indirect_sorter {
    sorter _sorter;

    function indirect_sorter() {
        _sorter = new sorter();
    }

    function test(uint[] arr) returns (uint[]) {
        return _sorter.sort(arr);
    }
}
''' % sort_code


@pytest.mark.timeout(100)
@pytest.mark.skip(reason="solidity doesn't support calls to dynamic array")
@skip_if_no_solidity_compiler
def test_indirect_sort():
    s = tester.state()
    c = s.abi_contract(sort_tester_code, language='solidity')
    assert c.test([80, 234, 112, 112, 29]) == [29, 80, 112, 112, 234]


@skip_if_no_solidity_compiler
def test_multiarg_code():
    multiarg_code = """
contract testme {
    function kall(uint[] a, uint b, uint[] c, string d, uint e) returns (uint, string, uint) {
        uint x = a[0] + 10 * b + 100 * c[0] + 1000 * a[1] + 10000 * c[1] + 100000 * e;
        return (x, d, bytes(d).length);
    }
}
"""


    s = tester.state()
    c = s.abi_contract(multiarg_code, language='solidity')
    o = c.kall([1, 2, 3], 4, [5, 6, 7], "doge", 8)
    assert o == [862541, b"doge", 4]


@skip_if_no_solidity_compiler
def test_ecrecover():
    ecrecover_code = """
contract testme {
    function test_ecrecover(bytes32 h, uint8 v, bytes32 r, bytes32 s) returns (address) {
        return ecrecover(h, v, r, s);
    }
}
"""

    s = tester.state()
    c = s.abi_contract(ecrecover_code, language='solidity')

    priv = utils.sha3('some big long brainwallet password')
    pub = bitcoin.privtopub(priv)

    msghash = utils.sha3('the quick brown fox jumps over the lazy dog')

    pk = PrivateKey(priv, raw=True)
    signature = pk.ecdsa_recoverable_serialize(
        pk.ecdsa_sign_recoverable(msghash, raw=True)
    )
    signature = signature[0] + chr(signature[1])
    V = ord(signature[64]) + 27
    R = signature[0:32]
    S = signature[32:64]

    assert bitcoin.ecdsa_raw_verify(msghash, (V, utils.big_endian_to_int(R), utils.big_endian_to_int(S)), pub)

    addr = utils.sha3(bitcoin.encode_pubkey(pub, 'bin')[1:])[12:]
    assert utils.privtoaddr(priv) == addr

    result = c.test_ecrecover(msghash, V, R, S)
    assert result == utils.encode_hex(addr)


@skip_if_no_solidity_compiler
def test_sha256():
    sha256_code = """
contract testme {
    function main() returns(bytes32, uint, bytes32, uint, bytes32, uint, bytes32, uint, bytes32, uint) {
        return (
            sha256(),
            uint(sha256()),
            sha256(3),
            uint(sha256(3)),
            sha256(uint(3)),
            uint(sha256(uint(3))),
            sha256("dog"),
            uint(sha256("dog")),
            sha256(uint(0), uint(0), uint(0), uint(0), uint(0)),
            uint(sha256(uint(0), uint(0), uint(0), uint(0), uint(0)))
        );
    }
}
"""

    s = tester.state()
    c = s.abi_contract(sha256_code, language='solidity')

    o = c.main()
    assert o[0] == binascii.unhexlify(b'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
    assert o[1] == utils.big_endian_to_int(binascii.unhexlify(b'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'))
    assert o[2] == binascii.unhexlify(b'084fed08b978af4d7d196a7446a86b58009e636b611db16211b65a9aadff29c5')
    assert o[3] == utils.big_endian_to_int(binascii.unhexlify(b'084fed08b978af4d7d196a7446a86b58009e636b611db16211b65a9aadff29c5'))
    assert o[4] == binascii.unhexlify(b'd9147961436944f43cd99d28b2bbddbf452ef872b30c8279e255e7daafc7f946')
    assert o[5] == utils.big_endian_to_int(binascii.unhexlify(b'd9147961436944f43cd99d28b2bbddbf452ef872b30c8279e255e7daafc7f946'))
    assert o[6] == binascii.unhexlify(b'cd6357efdd966de8c0cb2f876cc89ec74ce35f0968e11743987084bd42fb8944')
    assert o[7] == utils.big_endian_to_int(binascii.unhexlify(b'cd6357efdd966de8c0cb2f876cc89ec74ce35f0968e11743987084bd42fb8944'))
    assert o[8] == binascii.unhexlify(b'b393978842a0fa3d3e1470196f098f473f9678e72463cb65ec4ab5581856c2e4')
    assert o[9] == utils.big_endian_to_int(binascii.unhexlify(b'b393978842a0fa3d3e1470196f098f473f9678e72463cb65ec4ab5581856c2e4'))


@skip_if_no_solidity_compiler
def test_ripemd160():
    ripemd160_code = """
contract testme {
    function main() returns(bytes20, uint, bytes20, uint, bytes20, uint, bytes20, uint, bytes20, uint) {
        return (
            ripemd160(),
            uint(ripemd160()),
            ripemd160(3),
            uint(ripemd160(3)),
            ripemd160(uint(3)),
            uint(ripemd160(uint(3))),
            ripemd160("dog"),
            uint(ripemd160("dog")),
            ripemd160(uint(0), uint(0), uint(0), uint(0), uint(0)),
            uint(ripemd160(uint(0), uint(0), uint(0), uint(0), uint(0)))
        );
    }
}
"""

    s = tester.state()
    c = s.abi_contract(ripemd160_code, language='solidity')

    o = c.main()
    assert o[0] == binascii.unhexlify(b'9c1185a5c5e9fc54612808977ee8f548b2258d31')
    assert o[1] == utils.big_endian_to_int(binascii.unhexlify(b'9c1185a5c5e9fc54612808977ee8f548b2258d31'))
    assert o[2] == binascii.unhexlify(b'b2afadd73b9922f395573a52e7032b7597ff8c3e')
    assert o[3] == utils.big_endian_to_int(binascii.unhexlify(b'b2afadd73b9922f395573a52e7032b7597ff8c3e'))
    assert o[4] == binascii.unhexlify(b'44d90e2d3714c8663b632fcf0f9d5f22192cc4c8')
    assert o[5] == utils.big_endian_to_int(binascii.unhexlify(b'44d90e2d3714c8663b632fcf0f9d5f22192cc4c8'))
    assert o[6] == binascii.unhexlify(b'2a5756a3da3bc6e4c66a65028f43d31a1290bb75')
    assert o[7] == utils.big_endian_to_int(binascii.unhexlify(b'2a5756a3da3bc6e4c66a65028f43d31a1290bb75'))
    assert o[8] == binascii.unhexlify(b'9164cab7f680fd7a790080f2e76e049811074349')
    assert o[9] == utils.big_endian_to_int(binascii.unhexlify(b'9164cab7f680fd7a790080f2e76e049811074349'))


@skip_if_no_solidity_compiler
def test_sha3():
    sha3_code = """
contract testme {
    function main() returns(bytes32, uint, bytes32, uint, bytes32, uint, bytes32, uint, bytes32, uint) {
        return (
            sha3(),
            uint(sha3()),
            sha3(3),
            uint(sha3(3)),
            sha3(uint(3)),
            uint(sha3(uint(3))),
            sha3("dog"),
            uint(sha3("dog")),
            sha3(uint(0), uint(0), uint(0), uint(0), uint(0)),
            uint(sha3(uint(0), uint(0), uint(0), uint(0), uint(0)))
        );
    }
}
"""

    s = tester.state()
    c = s.abi_contract(sha3_code, language='solidity')

    o = c.main()
    assert o[0] == binascii.unhexlify(b'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470')
    assert o[1] == utils.big_endian_to_int(binascii.unhexlify(b'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'))
    assert o[2] == binascii.unhexlify(b'69c322e3248a5dfc29d73c5b0553b0185a35cd5bb6386747517ef7e53b15e287')
    assert o[3] == utils.big_endian_to_int(binascii.unhexlify(b'69c322e3248a5dfc29d73c5b0553b0185a35cd5bb6386747517ef7e53b15e287'))
    assert o[4] == binascii.unhexlify(b'c2575a0e9e593c00f959f8c92f12db2869c3395a3b0502d05e2516446f71f85b')
    assert o[5] == utils.big_endian_to_int(binascii.unhexlify(b'c2575a0e9e593c00f959f8c92f12db2869c3395a3b0502d05e2516446f71f85b'))
    assert o[6] == binascii.unhexlify(b'41791102999c339c844880b23950704cc43aa840f3739e365323cda4dfa89e7a')
    assert o[7] == utils.big_endian_to_int(binascii.unhexlify(b'41791102999c339c844880b23950704cc43aa840f3739e365323cda4dfa89e7a'))
    assert o[8] == binascii.unhexlify(b'dfded4ed5ac76ba7379cfe7b3b0f53e768dca8d45a34854e649cfc3c18cbd9cd')
    assert o[9] == utils.big_endian_to_int(binascii.unhexlify(b'dfded4ed5ac76ba7379cfe7b3b0f53e768dca8d45a34854e649cfc3c18cbd9cd'))


@skip_if_no_solidity_compiler
def test_prevhashes():
    prevhashes_code = """
contract testme {

    function get_prevhash(uint k) returns (bytes32) {
        return block.blockhash(block.number - k);
    }

    function get_prevhashes(uint k) returns (bytes32[]) {
        bytes32[] memory o = new bytes32[](k);

        uint i = 0;
        while (i < k) {
            o[i] = block.blockhash(block.number - i);
            i += 1;
        }

        return o;
    }
}
"""
    s = tester.state()
    s.mine(7)
    c = s.abi_contract(prevhashes_code, language='solidity')

    assert binascii.hexlify(c.get_prevhash(0)) == "0000000000000000000000000000000000000000000000000000000000000000"
    assert binascii.hexlify(c.get_prevhash(1)) == utils.encode_hex(s.blocks[-2].hash)
    assert binascii.hexlify(c.get_prevhash(2)) == utils.encode_hex(s.blocks[-3].hash)

    # Hashes of last 14 blocks including existing one
    o1 = [utils.encode_hex(block_hash) for block_hash in c.get_prevhashes(14)]

    t1 = [b'\x00'] + \
         [b.hash for b in s.blocks[-2::-1]] + \
         [b'\x00'] * 6
    t1 = [utils.encode_hex(utils.zpad(block_hash, 32)) for block_hash in t1]

    assert o1 == t1

    s.mine(256)

    # Test 256 limit: only 1 <= g <= 256 generation ancestors get hashes shown
    o2 = [utils.encode_hex(block_hash) for block_hash in c.get_prevhashes(270)]

    t2 = [b'\x00'] + \
         [b.hash for b in s.blocks[-2:-258:-1]] + \
         [b'\x00'] * 13
    t2 = [utils.encode_hex(utils.zpad(block_hash, 32)) for block_hash in t2]

    assert o2 == t2


@skip_if_no_solidity_compiler
def test_string_manipulation():
    string_manipulation_code = """
contract testme {
    function f1(string str) returns (string) {
        bytes(str)[0] = "a";
        bytes(str)[1] = "b";

        return str;
    }
}
"""


    s = tester.state()
    c = s.abi_contract(string_manipulation_code, language='solidity')
    assert c.f1("cde") == b"abe"


@skip_if_no_solidity_compiler
def test_double_array():
    double_array_code = """
contract testme {
    function foo(uint[] a, uint[] b) returns (uint, uint) {
        uint i = 0;
        uint tot = 0;

        while (i < a.length) {
            tot = tot * 10 + a[i];
            i += 1;
        }

        uint j = 0;
        uint tot2 = 0;

        while (j < b.length) {
            tot2 = tot2 * 10 + b[j];
            j += 1;
        }

        return (tot, tot2);
    }

    function bar(uint[] a, string m, uint[] b) returns (uint, uint) {
        return (this.foo(a, b));
    }
}
"""
    s = tester.state()
    c = s.abi_contract(double_array_code, language='solidity')
    assert c.foo([1, 2, 3], [4, 5, 6, 7]) == [123, 4567]
    assert c.bar([1, 2, 3], "moo", [4, 5, 6, 7]) == [123, 4567]


@skip_if_no_solidity_compiler
def test_abi_address_output():
    abi_address_output_test_code = """
contract testme {
    mapping(uint => address) addrs;

    function get_address(uint key) returns (address) {
        return addrs[key];
    }

    function register(uint key, address addr) {
        if (addrs[key] == 0x0) {
            addrs[key] = addr;
        }
    }
}
"""

    s = tester.state()
    c = s.abi_contract(abi_address_output_test_code, language='solidity')
    c.register(123, tester.a0)
    c.register(123, tester.a1)
    c.register(125, tester.a2)
    assert c.get_address(123) == utils.encode_hex(tester.a0)
    assert c.get_address(125) == utils.encode_hex(tester.a2)


@skip_if_no_solidity_compiler
def test_inner_abi_address_output1():
    abi_address_output_test_code = """
contract subtestme {
    mapping(uint => address) addrs;

    function _get_address(uint key) returns (address) {
        return addrs[key];
    }

    function _register(uint key, address addr) {
        if (addrs[key] == 0x0) {
            addrs[key] = addr;
        }
    }
}

contract testme {
    address sub;

    function testme() {
        sub = new subtestme();
    }

    function get_address(uint key) returns (address) {
        return subtestme(sub)._get_address(key);
    }

    function register(uint key, address addr) {
        return subtestme(sub)._register(key, addr);
    }
}
"""

    s = tester.state()
    c = s.abi_contract(abi_address_output_test_code, language='solidity')
    c.register(123, tester.a0)
    c.register(123, tester.a1)
    c.register(125, tester.a2)
    assert c.get_address(123) == utils.encode_hex(tester.a0)
    assert c.get_address(125) == utils.encode_hex(tester.a2)



@skip_if_no_solidity_compiler
def test_inner_abi_address_output2():
    abi_address_output_test_code = """
contract subtestme {
    mapping(uint => address) addrs;

    function _get_address(uint key) returns (address) {
        return addrs[key];
    }

    function _register(uint key, address addr) {
        if (addrs[key] == 0x0) {
            addrs[key] = addr;
        }
    }
}

contract testme {
    subtestme sub;

    function testme() {
        sub = new subtestme();
    }

    function get_address(uint key) returns (address) {
        return subtestme(sub)._get_address(key);
    }

    function register(uint key, address addr) {
        return subtestme(sub)._register(key, addr);
    }
}
"""

    s = tester.state()
    c = s.abi_contract(abi_address_output_test_code, language='solidity')
    c.register(123, tester.a0)
    c.register(123, tester.a1)
    c.register(125, tester.a2)
    assert c.get_address(123) == utils.encode_hex(tester.a0)
    assert c.get_address(125) == utils.encode_hex(tester.a2)


@skip_if_no_solidity_compiler
def test_raw_logging():
    raw_logging_code = """
contract testme {
    function moo() {
        log0("msg1");
        log1("msg2", "t1");
        log2("msg3", "t1", "t2");
    }
}
"""

    s = tester.state()
    c = s.abi_contract(raw_logging_code, language='solidity')
    o = []
    s.block.log_listeners.append(lambda x: o.append(x))

    c.moo()

    assert o[0].data == b'msg1'
    assert o[1].data == b'msg2'
    assert o[2].data == b'msg3'


@skip_if_no_solidity_compiler
def test_event_logging():
    event_logging_code = """
contract testme {
    event foo(
        string x,
        string y
    );

    function moo() {
        foo("bob", "cow");
    }
}
"""

    s = tester.state()
    c = s.abi_contract(event_logging_code, language='solidity')
    o = []
    s.block.log_listeners.append(lambda x: o.append(c.translator.listen(x)))

    c.moo()

    assert o == [{"_event_type": b"foo", "x": b"bob", "y": b"cow"}]


@skip_if_no_solidity_compiler
def test_origin():
    code = """
contract testme {
    function sender() returns (address) {
        return msg.sender;
    }

    function origin() returns (address) {
        return tx.origin;
    }

    function senderisorigin() returns (bool) {
        return msg.sender == tx.origin;
    }
}

contract testmechild is testme {
}

contract testmeparent is testme {
    testmechild child;

    function testmeparent() {
        child = new testmechild();
    }

    function childsender() returns(address) {
        return child.sender();
    }

    function childorigin() returns(address) {
        return child.origin();
    }

    function childsenderisorigin() returns(bool) {
        return child.senderisorigin();
    }
}
    """

    s = tester.state()
    c = s.abi_contract(code, language='solidity')

    assert c.sender() == utils.encode_hex(tester.a0)
    assert c.origin() == utils.encode_hex(tester.a0)
    assert c.senderisorigin() == True

    assert c.childsender() == utils.encode_hex(c.address)
    assert c.childorigin() == utils.encode_hex(tester.a0)
    assert c.childsenderisorigin() == False


@skip_if_no_solidity_compiler
def test_throw():
    code = """
contract testme {
    function main() {
        msg.sender.send(10000000000);
        throw;
    }
}
"""

    s = tester.state()
    c = s.abi_contract(code, endowment=10000000000, language='solidity')

    b = s.block.get_balance(tester.a1)

    with pytest.raises(tester.TransactionFailed):
        assert c.main(sender=tester.k1)

    s.mine(1, coinbase=tester.a0)

    # should have paid for gas and not received the send
    assert s.block.get_balance(tester.a1) < b


@skip_if_no_solidity_compiler
def test_fallback_call_throws():
    code = """
contract testme {
    function() { throw; }
}
"""

    s = tester.state()
    c = s.abi_contract(code, language='solidity')

    with pytest.raises(tester.TransactionFailed):
        s.send(sender=tester.k0, to=c.address, value=100000)


@skip_if_no_solidity_compiler
def test_fallback_count():
    code = """
contract testme {
    uint called = 0;

    function() { called++; }

    function get() returns (uint) {
        return called;
    }
}
"""

    s = tester.state()
    c = s.abi_contract(code, language='solidity')

    s.send(sender=tester.k0, to=c.address, value=100000)
    assert c.get() == 1

    s.send(sender=tester.k0, to=c.address, value=100000)
    assert c.get() == 2


@skip_if_no_solidity_compiler
def test_fallback_call():
    code1 = """
contract testme1 {
    function call(address ping) returns (bool) {
        return ping.call.value(100)();
    }
}
"""
    code2 = """
contract testme2 {
    uint called = 0;

    function() { called++; }

    function get() returns (uint) {
        return called;
    }
}
"""

    s = tester.state()
    c1 = s.abi_contract(code1, language='solidity')
    c2 = s.abi_contract(code2, language='solidity')

    assert c2.get() == 0
    assert c1.call(c2.address, value=100) == True
    assert c2.get() == 1


@skip_if_no_solidity_compiler
def test_fallback_recursive_abuse():
    """
    test the posibility to abuse recursive entry
    """

    code1 = """
contract testme1 {
    uint called = 0;

    function incr(address ping) returns (bool) {
        called++;
        return ping.call.value(100)();
    }

    function get() returns (uint) {
        return called;
    }
}
"""
    code2 = """
%s // testme1

contract testme2 {
    address other = address(%d);

    function() {
        testme1(other).incr(this);
    }
}
"""

    s = tester.state()
    c1 = s.abi_contract(code1, endowment=199, language='solidity')
    c2 = s.abi_contract(code2 % (code1, utils.big_endian_to_int(c1.address)), language='solidity')

    assert s.block.get_balance(c2.address) == 0

    assert c1.incr(c2.address) == True
    assert c1.get() == 2
    assert s.block.get_balance(c2.address) == 100

    c1 = s.abi_contract(code1, endowment=2000, language='solidity')
    c2 = s.abi_contract(code2 % (code1, utils.big_endian_to_int(c1.address)), language='solidity')
    assert c1.incr(c2.address) == True
    assert c1.get() == 21
    assert s.block.get_balance(c2.address) == 2000


@skip_if_no_solidity_compiler
def test_fallback_recursive_mutex():
    """
    test protecting against abuse of recursive entry with a mutex
    """
    code1 = """
contract testme1 {
    uint called = 0;

    mapping(uint => bool) mutex;

    function incr(address ping) returns (bool) {
        if (!mutex[called]) {
            mutex[called] = true; // LOCK IT
            if (ping.call.value(100)()) {
                called++;
                return true;
            }
        }
    }

    function get() returns (uint) {
        return called;
    }
}
"""
    code2 = """
%s // testme1

contract testme2 {
    address other = address(%d);

    function() {
        testme1(other).incr(this);
    }
}
"""

    s = tester.state()
    c1 = s.abi_contract(code1, endowment=199, language='solidity')
    c2 = s.abi_contract(code2 % (code1, utils.big_endian_to_int(c1.address)), language='solidity')

    assert s.block.get_balance(c2.address) == 0

    assert c1.incr(c2.address) == True
    assert c1.get() == 1
    assert s.block.get_balance(c2.address) == 100

    c1 = s.abi_contract(code1, endowment=2000, language='solidity')
    c2 = s.abi_contract(code2 % (code1, utils.big_endian_to_int(c1.address)), language='solidity')
    assert c1.incr(c2.address) == True
    assert c1.get() == 1
    assert s.block.get_balance(c2.address) == 100


@skip_if_no_solidity_compiler
def test_refund_suicide():
    code = """
contract testme {
    function main() {

    }
}
"""

    s = tester.state()
    c = s.abi_contract(code, language='solidity')
    b = s.block.get_balance(tester.a1)
    c.main(sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance

    gascost = b - s.block.get_balance(tester.a1)

    assert gascost == 21362

    code = """
contract testme {
    function main() {
        selfdestruct(msg.sender);
    }
}
"""

    s = tester.state()
    c = s.abi_contract(code, language='solidity')
    b = s.block.get_balance(tester.a1)
    c.main(sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance

    gascost = b - s.block.get_balance(tester.a1)

    assert gascost == 10678  # suicide results in a refund


@skip_if_no_solidity_compiler
def test_refund_clear_array():
    code = """
contract testme {
    uint[] data;

    function main(uint l) {
        for (uint i = 0; i < l; i++) {
            data.push(i);
        }
    }

    function clearall() {
        delete data;
    }
}
"""

    s = tester.state()
    c = s.abi_contract(code, language='solidity')
    b = s.block.get_balance(tester.a1)
    c.main(10, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 274746

    b = s.block.get_balance(tester.a1)
    c.clearall(sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 38494


@skip_if_no_solidity_compiler
def test_refund_clear_mapping():
    code = """
contract testme {
    mapping(uint => bool) data;

    function main(uint l) {
        for (uint i = 0; i < l; i++) {
            data[i] = true;
        }
    }

    function clear(uint l) {
        for (uint i = 0; i < l; i++) {
            delete data[i];
        }
    }
}
"""

    s = tester.state()
    c = s.abi_contract(code, language='solidity')
    b = s.block.get_balance(tester.a1)
    c.main(10, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 223454

    b = s.block.get_balance(tester.a1)
    c.clear(10, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 36708


@skip_if_no_solidity_compiler
def test_refund_maximize_refund():
    code1 = """
contract testme1 {
    mapping(uint => bool) data;

    function main(uint l) {
        for (uint i = 0; i < l; i++) {
            data[i] = true;
        }
    }

    function clear(uint l) {
        for (uint i = 0; i < l; i++) {
            delete data[i];
        }
    }
}
"""
    code2 = """
%s // code1

contract testme2 {
    address other;
    mapping(uint => bool) data;

    function testme2(address _other) {
        other = _other;
    }

    function main(uint l, bool attemptClear) {
        // expend gas
        for (uint i = 0; i < l; i++) {
            data[i] = true;
        }

        if (attemptClear) {
            testme1(other).clear(l);
        }
    }
}
"""

    s = tester.state()
    c1 = s.abi_contract(code1, language='solidity')
    c2 = s.abi_contract(code2 % code1, constructor_parameters=[c1.address], language='solidity')
    b = s.block.get_balance(tester.a1)
    c1.main(10, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 223454

    b = s.block.get_balance(tester.a1)
    c2.main(10, False, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 223640

    # now try to piggyback on the refund of the other contract
    b = s.block.get_balance(tester.a1)
    c2.main(10, True, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 62924

    # again, but with more data
    c1 = s.abi_contract(code1, language='solidity')
    c2 = s.abi_contract(code2 % code1, constructor_parameters=[c1.address], language='solidity')
    b = s.block.get_balance(tester.a1)
    c1.main(20, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 425314

    b = s.block.get_balance(tester.a1)
    c2.main(20, False, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 425530

    # now try to piggyback on the refund of the other contract
    b = s.block.get_balance(tester.a1)
    c2.main(20, True, sender=tester.k1)
    s.mine(coinbase=tester.a0)  # to update balance
    gascost = b - s.block.get_balance(tester.a1)
    assert gascost == 114769
