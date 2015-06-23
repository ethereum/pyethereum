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

    event CoinSent(address indexed from, uint256 value, address indexed to);

    function currency() {
        accounts[msg.sender].balance = 1000000;
    }

    function sendCoin(uint _val, address _to) returns (bool _success) {
        if (accounts[msg.sender].balance >= _val && _val < 340282366920938463463374607431768211456) {
            accounts[msg.sender].balance -= _val;
            accounts[_to].balance += _val;
            CoinSent(msg.sender, _val, _to);
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
            CoinSent(_from, _val, _to);
            _success = true;
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

event CoinSent(from:address:indexed, value:uint256, to:address:indexed)

def init():
    self.accounts[msg.sender].balance = 1000000

def sendCoin(_val:uint256, _to:address):
    if self.accounts[msg.sender].balance >= _val and _val >= 0 and _val < 340282366920938463463374607431768211456:
        self.accounts[msg.sender].balance -= _val
        self.accounts[_to].balance += _val
        log(type=CoinSent, msg.sender, _val, _to)
        return(1:bool)
    return(0:bool)

def sendCoinFrom(_from:address, _val:uint256, _to:address):
    auth = self.accounts[_from].withdrawers[msg.sender]
    if self.accounts[_from].balance >= _val and auth >= _val && _val >= 0 and _val < 340282366920938463463374607431768211456:
        self.accounts[_from].withdrawers[msg.sender] -= _val
        self.accounts[_from].balance -= _val
        self.accounts[_to].balance += _val
        log(type=CoinSent, _from, _val, _to)
        return(1:bool)
    return(0:bool)

def coinBalance():
    return(self.accounts[msg.sender].balance)

def coinBalanceOf(_a:address):
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
    o = []
    s.block.log_listeners.append(lambda x: o.append(c._translator.listen(x)))
    for c in (c1, c2):
        o = []
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
        print 'barricade', o
        assert o == [{"_event_type": b"CoinSent", "from": utils.encode_hex(tester.a0),
                      "value": 1000, "to": utils.encode_hex(tester.a2)},
                     {"_event_type": b"CoinSent", "from": utils.encode_hex(tester.a2),
                      "value": 400, "to": utils.encode_hex(tester.a3)},
                     {"_event_type": b"CoinSent", "from": utils.encode_hex(tester.a2),
                      "value": 100, "to": utils.encode_hex(tester.a3)},
                     {"_event_type": b"CoinSent", "from": utils.encode_hex(tester.a2),
                      "value": 100, "to": utils.encode_hex(tester.a3)}]


serpent_namereg = """
data records[](owner, address, content, sub)

event Changed(name:bytes32:indexed)

def reserve(_name:bytes32):
    if not self.records[_name].owner:
        self.records[_name].owner = msg.sender
        log(type=Changed, _name)
        return(1:bool)
    return(0:bool)

def owner(_name:bytes32):
    return(self.records[_name].owner:address)

def transfer(_name:bytes32, _newOwner:address):
    if self.records[_name].owner == msg.sender:
        log(type=Changed, _name)
        self.records[_name].owner = _newOwner

def setAddr(_name:bytes32, _a:address):
    if self.records[_name].owner == msg.sender:
        log(type=Changed, _name)
        self.records[_name].address = _a

def addr(_name:bytes32):
    return(self.records[_name].address:address)

def setContent(_name:bytes32, _content:bytes32):
    if self.records[_name].owner == msg.sender:
        log(type=Changed, _name)
        self.records[_name].content = _content

def content(_name:bytes32):
    return(self.records[_name].content:bytes32)

def setSubRegistrar(_name:bytes32, _registrar:address):
    if self.records[_name].owner == msg.sender:
        log(type=Changed, _name)
        self.records[_name].sub = _registrar

def subRegistrar(_name:bytes32):
    return(self.records[_name].sub:address)

def disown(_name:bytes32):
    if self.records[_name].owner == msg.sender:
        log(type=Changed, _name)
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

    event Changed(bytes32 indexed name);

    function reserve(bytes32 _name) returns (bool _success) {
        if (records[_name].owner == 0) {
            records[_name].owner = msg.sender;
            Changed(_name);
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
            Changed(_name);
        }
    }

    function setAddr(bytes32 _name, address _a) {
        if (records[_name].owner == msg.sender) {
            records[_name].addr = _a;
            Changed(_name);
        }
    }

    function addr(bytes32 _name) returns (address _a) {
        _a = records[_name].addr;
    }

    function setContent(bytes32 _name, bytes32 _content) {
        if (records[_name].owner == msg.sender) {
            records[_name].content = _content;
            Changed(_name);
        }
    }

    function content(bytes32 _name) returns (bytes32 _content) {
        _content = records[_name].content;
    }

    function setSubRegistrar(bytes32 _name, address _registrar) {
        if (records[_name].owner == msg.sender) {
            records[_name].sub = _registrar;
            Changed(_name);
        }
    }

    function subRegistrar(bytes32 _name) returns (address _registrar) {
        _registrar = records[_name].sub;
    }

    function disown(bytes32 _name) {
        if (records[_name].owner == msg.sender) {
            records[_name].owner = 0;
            Changed(_name);
        }
    }
}
"""


def test_registrar_apis():
    s = tester.state()
    c1 = s.abi_contract(serpent_namereg, sender=tester.k0)
    c2 = s.abi_contract(solidity_namereg, language='solidity', sender=tester.k0)
    o = []
    s.block.log_listeners.append(lambda x: o.append(c._translator.listen(x)))
    for c in (c1, c2):
        o = []
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
        assert o == [{"_event_type": b"Changed", "name": b'moose' + b'\x00' * 27}] * 5


solidity_exchange = """
contract currency {
    function sendCoinFrom(address _from, uint _val, address _to) returns (bool _success) { } 
    function sendCoin(uint _val, address _to) returns (bool _success) { }
}

contract exchange {
    struct Order {
        address creator;
        address offerCurrency;
        uint256 offerValue;
        address wantCurrency;
        uint256 wantValue;
    }

    event Traded(bytes32 indexed currencyPair, address indexed seller, uint256 offerValue, address indexed buyer, uint256 wantValue);

    mapping ( uint256 => Order ) orders;
    uint256 nextOrderId = 1;

    function placeOrder(address offerCurrency, uint256 offerValue, address wantCurrency, uint256 wantValue) returns (uint256 offer_id) {
        if (currency(offerCurrency).sendCoinFrom(msg.sender, offerValue, this)) {
            offer_id = nextOrderId;
            nextOrderId += 1;
            orders[offer_id].creator = msg.sender;
            orders[offer_id].offerCurrency = offerCurrency;
            orders[offer_id].offerValue = offerValue;
            orders[offer_id].wantCurrency = wantCurrency;
            orders[offer_id].wantValue = wantValue;
        }
        else offer_id = 0;
    }

    function claimOrder(uint256 offer_id) returns (bool _success) {
        if (currency(orders[offer_id].wantCurrency).sendCoinFrom(msg.sender, orders[offer_id].wantValue, orders[offer_id].creator)) {
            currency(orders[offer_id].offerCurrency).sendCoin(orders[offer_id].offerValue, msg.sender);
            bytes32 currencyPair = bytes32(((uint256(orders[offer_id].offerCurrency) / 2**32) * 2**128) + (uint256(orders[offer_id].wantCurrency) / 2**32));
            Traded(currencyPair, orders[offer_id].creator, orders[offer_id].offerValue, msg.sender, orders[offer_id].wantValue);
            orders[offer_id].creator = 0;
            orders[offer_id].offerCurrency = 0;
            orders[offer_id].offerValue = 0;
            orders[offer_id].wantCurrency = 0;
            orders[offer_id].wantValue = 0;
            _success = true;
        }
        else _success = false;
    }

    function deleteOrder(uint256 offer_id) {
        currency(orders[offer_id].offerCurrency).sendCoin(orders[offer_id].offerValue, orders[offer_id].creator);
        orders[offer_id].creator = 0;
        orders[offer_id].offerCurrency = 0;
        orders[offer_id].offerValue = 0;
        orders[offer_id].wantCurrency = 0;
        orders[offer_id].wantValue = 0;
    }
}
"""

serpent_exchange = """
extern currency: [sendCoinFrom:[address,uint256,address]:bool, sendCoin:[uint256,address]:bool]

data orders[](creator, offerCurrency, offerValue, wantCurrency, wantValue)
data nextOrderId

event Traded(currencyPair:bytes32:indexed, seller:address:indexed, offerValue:uint256, buyer:address:indexed, wantValue:uint256)

def init():
    self.nextOrderId = 1

def placeOrder(offerCurrency:address, offerValue:uint256, wantCurrency:address, wantValue:uint256):
    if offerCurrency.sendCoinFrom(msg.sender, offerValue, self):
        offer_id = self.nextOrderId
        self.nextOrderId += 1
        self.orders[offer_id].creator = msg.sender
        self.orders[offer_id].offerCurrency = offerCurrency
        self.orders[offer_id].offerValue = offerValue
        self.orders[offer_id].wantCurrency = wantCurrency
        self.orders[offer_id].wantValue = wantValue
        return(offer_id:uint256)
    return(0:uint256)

def claimOrder(offer_id:uint256):
    if self.orders[offer_id].wantCurrency.sendCoinFrom(msg.sender, self.orders[offer_id].wantValue, self.orders[offer_id].creator):
        self.orders[offer_id].offerCurrency.sendCoin(self.orders[offer_id].offerValue, msg.sender)
        currencyPair = (self.orders[offer_id].offerCurrency / 2**32) * 2**128 + (self.orders[offer_id].wantCurrency / 2**32)
        log(type=Traded, currencyPair, self.orders[offer_id].creator, self.orders[offer_id].offerValue, msg.sender, self.orders[offer_id].wantValue)
        self.orders[offer_id].creator = 0
        self.orders[offer_id].offerCurrency = 0
        self.orders[offer_id].offerValue = 0
        self.orders[offer_id].wantCurrency = 0
        self.orders[offer_id].wantValue = 0
        return(1:bool)
    return(0:bool)

def deleteOrder(offer_id:uint256):
    self.orders[offer_id].offerCurrency.sendCoin(self.orders[offer_id].offerValue, self.orders[offer_id].creator)
    self.orders[offer_id].creator = 0
    self.orders[offer_id].offerCurrency = 0
    self.orders[offer_id].offerValue = 0
    self.orders[offer_id].wantCurrency = 0
    self.orders[offer_id].wantValue = 0
"""


def test_exchange_apis():
    s = tester.state()
    oc1 = s.abi_contract(serpent_currency, sender=tester.k0)
    oc2 = s.abi_contract(solidity_currency, language='solidity', sender=tester.k0)
    wc1 = s.abi_contract(serpent_currency, sender=tester.k1)
    wc2 = s.abi_contract(solidity_currency, language='solidity', sender=tester.k1)
    e1 = s.abi_contract(serpent_exchange, sender=tester.k0)
    e2 = s.abi_contract(solidity_exchange, language='solidity', sender=tester.k0)
    o = []
    s.block.log_listeners.append(lambda x: o.append(e1._translator.listen(x)))
    # Test serpent-solidity, solidity-serpent interop
    for (oc, wc, e) in ((oc1, wc1, e2), (oc2, wc2, e1)):
        o = []
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
        cxor = utils.big_endian_to_int(oc.address) ^ utils.big_endian_to_int(wc.address)
        assert {"_event_type": b"Traded",
                "currencyPair": oc.address[:16] + wc.address[:16],
                "seller": utils.encode_hex(tester.a0), "offerValue": 1000,
                "buyer": utils.encode_hex(tester.a1), "wantValue": 5000} in o


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
