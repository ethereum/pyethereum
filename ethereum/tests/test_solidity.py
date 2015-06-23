from ethereum import tester
from ethereum import utils
serpent_contract = """
extern solidity: [sub2:[]:i]

def main(a):
    return(a.sub2() * 2)

def sub1():
    return(5)

"""

solidity_contract = """
contract serpent { function sub1() returns (int256 y) {} }

contract zoo {
    function main(address a) returns (int256 y) {
        y = serpent(a).sub1() * 2;
    }
    function sub2() returns (int256 y) {
        y = 7;
    }
    function sub3(address a) returns (address b) {
        b = a;
    }
}
"""


def test_interop():
    if 'solidity' not in tester.languages:
        return
    s = tester.state()
    c1 = s.abi_contract(serpent_contract)
    c2 = s.abi_contract(solidity_contract, language='solidity')  # should be zoo
    assert c1.sub1() == 5
    assert c2.sub2() == 7
    assert c2.sub3(utils.encode_hex(c2.address)) == utils.encode_hex(c2.address)
    assert c1.main(c2.address) == 14
    assert c2.main(c1.address) == 10


solidity_currency = """
contract currency {

    struct Account {
        uint balance;
        mapping ( address => uint) withdrawers;
    }

    mapping ( address => Account ) accounts;

    function currency() {
        accounts[msg.sender].balance = 1000000;
    }

    function sendCoin(uint _val, address _to) returns (bool _success) {
        if (accounts[msg.sender].balance >= _val && _val < 340282366920938463463374607431768211456) {
            accounts[msg.sender].balance -= _val;
            accounts[_to].balance += _val;
            _success = true;
        }
        else _success = false;
    }

    function sendCoinFrom(address _from, uint _val, address _to) returns (bool _success) {
        uint auth = accounts[_from].withdrawers[msg.sender];
        if (accounts[_from].balance >= _val && auth >= _val && _val < 340282366920938463463374607431768211456) {
            accounts[_from].withdrawers[msg.sender] -= _val;
            accounts[_from].balance -= _val;
            accounts[_to].balance += _val;
            _success = true;
        }
        else _success = false;
    }

    function coinBalance() constant returns (uint _r) {
        _r = accounts[msg.sender].balance;
    }

    function coinBalanceOf(address _a) constant returns (uint _r) {
        _r = accounts[_a].balance;
    }

    function approve(address _a) {
        accounts[msg.sender].withdrawers[_a] = 340282366920938463463374607431768211456;
    }

    function isApproved(address _a) returns (bool _isapproved) {
        _isapproved = (accounts[msg.sender].withdrawers[_a] > 0);
    }

    function approveOnce(address _a, uint256 _maxval) {
        accounts[msg.sender].withdrawers[_a] += _maxval;
    }

    function disapprove(address _a) {
        accounts[msg.sender].withdrawers[_a] = 0;
    }
}
"""

serpent_currency = """
data accounts[](balance, withdrawers[])

def init():
    self.accounts[msg.sender].balance = 1000000

def sendCoin(_val:uint256, _to:address):
    if self.accounts[msg.sender].balance >= _val and _val >= 0 and _val < 340282366920938463463374607431768211456:
        self.accounts[msg.sender].balance -= _val
        self.accounts[_to].balance += _val
        return(1:bool)
    return(0:bool)

def sendCoinFrom(_from:address, _val:uint256, _to:address):
    auth = self.accounts[_from].withdrawers[msg.sender]
    if self.accounts[_from].balance >= _val and auth >= _val && _val >= 0 and _val < 340282366920938463463374607431768211456:
        self.accounts[_from].withdrawers[msg.sender] -= _val
        self.accounts[_from].balance -= _val
        self.accounts[_to].balance += _val
        return(1:bool)
    return(0:bool)

def coinBalance():
    return(self.accounts[msg.sender].balance)

def coinBalanceOf(_a:address):
    log(_a)
    return(self.accounts[_a].balance)

def approve(_a:address):
    self.accounts[msg.sender].withdrawers[_a] = 340282366920938463463374607431768211456

def isApproved(_a:address):
    return(self.accounts[msg.sender].withdrawers[_a] > 0)

def approveOnce(_a:address, _maxval:uint256):
    self.accounts[msg.sender].withdrawers[_a] += _maxval

def disapprove(_a:address):
    self.accounts[msg.sender].withdrawers[_a] = 0
"""


def test_currency_apis():
    s = tester.state()
    c1 = s.abi_contract(serpent_currency, sender=tester.k0)
    c2 = s.abi_contract(solidity_currency, language='solidity', sender=tester.k0)
    for c in (c1, c2):
        assert c.coinBalanceOf(tester.a0) == 1000000
        assert c.sendCoin(1000, tester.a2, sender=tester.k0) is True
        assert c.sendCoin(999001, tester.a2, sender=tester.k0) is False
        assert c.sendCoinFrom(tester.a2, 500, tester.a3, sender=tester.k0) is False
        c.approveOnce(tester.a0, 500, sender=tester.k2)
        assert c.sendCoinFrom(tester.a2, 400, tester.a3, sender=tester.k0) is True
        assert c.sendCoinFrom(tester.a2, 400, tester.a3, sender=tester.k0) is False
        assert c.sendCoinFrom(tester.a2, 100, tester.a3, sender=tester.k0) is True
        assert c.sendCoinFrom(tester.a2, 100, tester.a3, sender=tester.k0) is False
        c.approve(tester.a0, sender=tester.k2)
        assert c.sendCoinFrom(tester.a2, 100, tester.a3, sender=tester.k0) is True
        c.disapprove(tester.a0, sender=tester.k2)
        assert c.sendCoinFrom(tester.a2, 100, tester.a3, sender=tester.k0) is False
        assert c.coinBalance(sender=tester.k0) == 999000
        assert c.coinBalanceOf(tester.a2) == 400
        assert c.coinBalanceOf(tester.a3) == 600


serpent_namereg = """
data records[](owner, address, content, sub)

def reserve(_name:bytes32):
    if not self.records[_name].owner:
        self.records[_name].owner = msg.sender
        return(1:bool)
    return(0:bool)

def owner(_name:bytes32):
    return(self.records[_name].owner:address)

def transfer(_name:bytes32, _newOwner:address):
    if self.records[_name].owner == msg.sender:
        self.records[_name].owner = _newOwner

def setAddr(_name:bytes32, _a:address):
    if self.records[_name].owner == msg.sender:
        self.records[_name].address = _a

def addr(_name:bytes32):
    return(self.records[_name].address:address)

def setContent(_name:bytes32, _content:bytes32):
    if self.records[_name].owner == msg.sender:
        self.records[_name].content = _content

def content(_name:bytes32):
    return(self.records[_name].content:bytes32)

def setSubRegistrar(_name:bytes32, _registrar:address):
    if self.records[_name].owner == msg.sender:
        self.records[_name].sub = _registrar

def subRegistrar(_name:bytes32):
    return(self.records[_name].sub:address)

def disown(_name:bytes32):
    if self.records[_name].owner == msg.sender:
        self.records[_name].owner = 0
"""

solidity_namereg = """
contract namereg {
    struct RegistryEntry {
        address owner;
        address addr;
        bytes32 content;
        address sub;
    }

    mapping ( bytes32 => RegistryEntry ) records;

    function reserve(bytes32 _name) returns (bool _success) {
        if (records[_name].owner == 0) {
            records[_name].owner = msg.sender;
            _success = true;
        }
        else _success = false;
    }

    function owner(bytes32 _name) returns (address o_owner) {
        o_owner = records[_name].owner;
    }

    function transfer(bytes32 _name, address _newOwner) {
        if (records[_name].owner == msg.sender) {
            records[_name].owner = _newOwner;
        }
    }

    function setAddr(bytes32 _name, address _a) {
        if (records[_name].owner == msg.sender) {
            records[_name].addr = _a;
        }
    }

    function addr(bytes32 _name) returns (address _a) {
        _a = records[_name].addr;
    }

    function setContent(bytes32 _name, bytes32 _content) {
        if (records[_name].owner == msg.sender) {
            records[_name].content = _content;
        }
    }

    function content(bytes32 _name) returns (bytes32 _content) {
        _content = records[_name].content;
    }

    function setSubRegistrar(bytes32 _name, address _registrar) {
        if (records[_name].owner == msg.sender) {
            records[_name].sub = _registrar;
        }
    }

    function subRegistrar(bytes32 _name) returns (address _registrar) {
        _registrar = records[_name].sub;
    }

    function disown(bytes32 _name) {
        if (records[_name].owner == msg.sender) {
            records[_name].owner = 0;
        }
    }
}
"""


def test_registrar_apis():
    s = tester.state()
    c1 = s.abi_contract(serpent_namereg, sender=tester.k0)
    c2 = s.abi_contract(solidity_namereg, language='solidity', sender=tester.k0)
    for c in (c1, c2):
        assert c.reserve('moose', sender=tester.k0) is True
        assert c.reserve('moose', sender=tester.k0) is False
        assert c.owner('moose') == utils.encode_hex(tester.a0)
        c.setAddr('moose', tester.a5)
        c.setAddr('moose', tester.a6, sender=tester.k1)
        assert c.addr('moose') == utils.encode_hex(tester.a5)
        c.transfer('moose', tester.a1, sender=tester.k0)
        c.transfer('moose', tester.a2, sender=tester.k0)
        assert c.owner('moose') == utils.encode_hex(tester.a1)
        c.setContent('moose', 'antlers', sender=tester.k0)
        c.setContent('moose', 'reindeer', sender=tester.k1)
        assert c.content('moose')[:8] == 'reindeer'
        c.setSubRegistrar('moose', tester.a7, sender=tester.k1)
        c.setSubRegistrar('moose', tester.a8, sender=tester.k2)
        assert c.subRegistrar('moose') == utils.encode_hex(tester.a7)


solidity_exchange = """
contract currency {
    function sendCoinFrom(address _from, uint _val, address _to) returns (bool _success) { } 
    function sendCoin(uint _val, address _to) returns (bool _success) { }
}

contract exchange {
    struct Order {
        address creator;
        address offer_currency;
        uint256 offer_value;
        address want_currency;
        uint256 want_value;
    }

    mapping ( uint256 => Order ) orders;
    uint256 nextOrderId = 1;

    function placeOrder(address offer_currency, uint256 offer_value, address want_currency, uint256 want_value) returns (uint256 offer_id) {
        if (currency(offer_currency).sendCoinFrom(msg.sender, offer_value, this)) {
            offer_id = nextOrderId;
            nextOrderId += 1;
            orders[offer_id].creator = msg.sender;
            orders[offer_id].offer_currency = offer_currency;
            orders[offer_id].offer_value = offer_value;
            orders[offer_id].want_currency = want_currency;
            orders[offer_id].want_value = want_value;
        }
        else offer_id = 0;
    }

    function claimOrder(uint256 offer_id) returns (bool _success) {
        if (currency(orders[offer_id].want_currency).sendCoinFrom(msg.sender, orders[offer_id].want_value, orders[offer_id].creator)) {
            currency(orders[offer_id].offer_currency).sendCoin(orders[offer_id].offer_value, msg.sender);
            orders[offer_id].creator = 0;
            orders[offer_id].offer_currency = 0;
            orders[offer_id].offer_value = 0;
            orders[offer_id].want_currency = 0;
            orders[offer_id].want_value = 0;
            _success = true;
        }
        else _success = false;
    }

    function deleteOrder(uint256 offer_id) {
        currency(orders[offer_id].offer_currency).sendCoin(orders[offer_id].offer_value, orders[offer_id].creator);
        orders[offer_id].creator = 0;
        orders[offer_id].offer_currency = 0;
        orders[offer_id].offer_value = 0;
        orders[offer_id].want_currency = 0;
        orders[offer_id].want_value = 0;
    }
}
"""

serpent_exchange = """
extern currency: [sendCoinFrom:[address,uint256,address]:bool, sendCoin:[uint256,address]:bool]

data orders[](creator, offer_currency, offer_value, want_currency, want_value)
data nextOrderId

def init():
    self.nextOrderId = 1

def placeOrder(offer_currency:address, offer_value:uint256, want_currency:address, want_value:uint256):
    if offer_currency.sendCoinFrom(msg.sender, offer_value, self):
        offer_id = self.nextOrderId
        self.nextOrderId += 1
        self.orders[offer_id].creator = msg.sender
        self.orders[offer_id].offer_currency = offer_currency
        self.orders[offer_id].offer_value = offer_value
        self.orders[offer_id].want_currency = want_currency
        self.orders[offer_id].want_value = want_value
        return(offer_id:uint256)
    return(0:uint256)

def claimOrder(offer_id:uint256):
    if self.orders[offer_id].want_currency.sendCoinFrom(msg.sender, self.orders[offer_id].want_value, self.orders[offer_id].creator):
        self.orders[offer_id].offer_currency.sendCoin(self.orders[offer_id].offer_value, msg.sender)
        self.orders[offer_id].creator = 0
        self.orders[offer_id].offer_currency = 0
        self.orders[offer_id].offer_value = 0
        self.orders[offer_id].want_currency = 0
        self.orders[offer_id].want_value = 0
        return(1:bool)
    return(0:bool)

def deleteOrder(offer_id:uint256):
    self.orders[offer_id].offer_currency.sendCoin(self.orders[offer_id].offer_value, self.orders[offer_id].creator)
    self.orders[offer_id].creator = 0
    self.orders[offer_id].offer_currency = 0
    self.orders[offer_id].offer_value = 0
    self.orders[offer_id].want_currency = 0
    self.orders[offer_id].want_value = 0
"""


def test_exchange_apis():
    s = tester.state()
    oc1 = s.abi_contract(serpent_currency, sender=tester.k0)
    oc2 = s.abi_contract(solidity_currency, language='solidity', sender=tester.k0)
    wc1 = s.abi_contract(serpent_currency, sender=tester.k1)
    wc2 = s.abi_contract(solidity_currency, language='solidity', sender=tester.k1)
    e1 = s.abi_contract(serpent_exchange, sender=tester.k0)
    e2 = s.abi_contract(solidity_exchange, language='solidity', sender=tester.k0)
    # Test serpent-solidity, solidity-serpent interop
    for (oc, wc, e) in ((oc1, wc1, e2), (oc2, wc2, e1)):
        assert oc.coinBalanceOf(tester.a0) == 1000000
        assert oc.coinBalanceOf(tester.a1) == 0
        assert wc.coinBalanceOf(tester.a0) == 0
        assert wc.coinBalanceOf(tester.a1) == 1000000
        # Offer fails because not approved to withdraw
        assert e.placeOrder(oc.address, 1000, wc.address, 5000, sender=tester.k0) == 0
        # Approve to withdraw
        oc.approveOnce(e.address, 1000, sender=tester.k0)
        # Offer succeeds
        oid = e.placeOrder(oc.address, 1000, wc.address, 5000, sender=tester.k0)
        assert oid > 0
        # Offer fails because withdrawal approval was one-time
        assert e.placeOrder(oc.address, 1000, wc.address, 5000, sender=tester.k0) == 0
        # Claim fails because not approved to withdraw
        assert e.claimOrder(oid, sender=tester.k1) is False
        # Approve to withdraw
        wc.approveOnce(e.address, 5000, sender=tester.k1)
        # Claim succeeds
        assert e.claimOrder(oid, sender=tester.k1) is True
        # Check balances
        assert oc.coinBalanceOf(tester.a0) == 999000
        assert oc.coinBalanceOf(tester.a1) == 1000
        assert wc.coinBalanceOf(tester.a0) == 5000
        assert wc.coinBalanceOf(tester.a1) == 995000



serpent_datafeed = """
data data[]
data owner

def init():
    self.owner = msg.sender

def set(k:bytes32, v):
    if msg.sender == self.owner:
        self.data[k] = v

def get(k:bytes32):
    return(self.data[k])
"""


solidity_datafeed = """
contract datafeed {
    mapping ( bytes32 => int256 ) data;
    address owner;

    function datafeed() {
        owner = msg.sender;
    }

    function set(bytes32 k, int256 v) {
        if (owner == msg.sender)
            data[k] = v;
    }

    function get(bytes32 k) returns (int256 v) {
        v = data[k];
    }
}
"""

def test_datafeeds():
    s = tester.state()
    c1 = s.abi_contract(serpent_datafeed, sender=tester.k0)
    c2 = s.abi_contract(solidity_datafeed, language='solidity', sender=tester.k0)
    for c in (c1, c2):
        c.set('moose', 110, sender=tester.k0)
        c.set('moose', 125, sender=tester.k1)
        assert c.get('moose') == 110


serpent_ether_charging_datafeed = """
data data[]
data owner
data fee

def init():
    self.owner = msg.sender

def set(k:bytes32, v):
    if msg.sender == self.owner:
        self.data[k] = v

def setFee(f:uint256):
    if msg.sender == self.owner:
        self.fee = f

def get(k:bytes32):
    if msg.value >= self.fee:
        return(self.data[k])
    else:
        return(0)

def getFee():
    return(self.fee:uint256)
"""


solidity_ether_charging_datafeed = """
contract datafeed {
    mapping ( bytes32 => int256 ) data;
    address owner;
    uint256 fee;

    function datafeed() {
        owner = msg.sender;
    }

    function set(bytes32 k, int256 v) {
        if (owner == msg.sender)
            data[k] = v;
    }

    function setFee(uint256 f) {
        if (owner == msg.sender)
            fee = f;
    }

    function get(bytes32 k) returns (int256 v) {
        if (msg.value >= fee)
            v = data[k];
        else
            v = 0;
    }

    function getFee() returns (uint256 f) {
        f = fee;
    }
}
"""


def test_ether_charging_datafeeds():
    s = tester.state()
    c1 = s.abi_contract(serpent_ether_charging_datafeed, sender=tester.k0)
    c2 = s.abi_contract(solidity_ether_charging_datafeed, language='solidity', sender=tester.k0)
    for c in (c1, c2):
        c.set('moose', 110, sender=tester.k0)
        c.set('moose', 125, sender=tester.k1)
        assert c.get('moose') == 110
        c.setFee(70, sender=tester.k0)
        c.setFee(110, sender=tester.k1)
        assert c.getFee() == 70
        assert c.get('moose') == 0
        assert c.get('moose', value=69) == 0
        assert c.get('moose', value=70) == 110
