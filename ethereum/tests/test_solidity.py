import pytest
from ethereum import tester
from ethereum import utils
from ethereum._solidity import get_solidity


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


@pytest.mark.skipif(get_solidity() is None, reason="'solc' compiler not available")
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

    function sendCoin(uint _value, address _to) returns (bool _success) {
        if (accounts[msg.sender].balance >= _value && _value < 340282366920938463463374607431768211456) {
            accounts[msg.sender].balance -= _value;
            accounts[_to].balance += _value;
            CoinSent(msg.sender, _value, _to);
            _success = true;
        }
        else _success = false;
    }

    function sendCoinFrom(address _from, uint _value, address _to) returns (bool _success) {
        uint auth = accounts[_from].withdrawers[msg.sender];
        if (accounts[_from].balance >= _value && auth >= _value && _value < 340282366920938463463374607431768211456) {
            accounts[_from].withdrawers[msg.sender] -= _value;
            accounts[_from].balance -= _value;
            accounts[_to].balance += _value;
            CoinSent(_from, _value, _to);
            _success = true;
            _success = true;
        }
        else _success = false;
    }

    function coinBalance() constant returns (uint _r) {
        _r = accounts[msg.sender].balance;
    }

    function coinBalanceOf(address _addr) constant returns (uint _r) {
        _r = accounts[_addr].balance;
    }

    function approve(address _addr) {
        accounts[msg.sender].withdrawers[_addr] = 340282366920938463463374607431768211456;
    }

    function isApproved(address _proxy) returns (bool _r) {
        _r = (accounts[msg.sender].withdrawers[_proxy] > 0);
    }

    function approveOnce(address _addr, uint256 _maxValue) {
        accounts[msg.sender].withdrawers[_addr] += _maxValue;
    }

    function disapprove(address _addr) {
        accounts[msg.sender].withdrawers[_addr] = 0;
    }
}
"""

serpent_currency = """
data accounts[](balance, withdrawers[])

event CoinSent(from:address:indexed, value:uint256, to:address:indexed)

def init():
    self.accounts[msg.sender].balance = 1000000

def sendCoin(_value:uint256, _to:address):
    if self.accounts[msg.sender].balance >= _value and _value >= 0 and _value < 340282366920938463463374607431768211456:
        self.accounts[msg.sender].balance -= _value
        self.accounts[_to].balance += _value
        log(type=CoinSent, msg.sender, _value, _to)
        return(1:bool)
    return(0:bool)

def sendCoinFrom(_from:address, _value:uint256, _to:address):
    auth = self.accounts[_from].withdrawers[msg.sender]
    if self.accounts[_from].balance >= _value and auth >= _value && _value >= 0 and _value < 340282366920938463463374607431768211456:
        self.accounts[_from].withdrawers[msg.sender] -= _value
        self.accounts[_from].balance -= _value
        self.accounts[_to].balance += _value
        log(type=CoinSent, _from, _value, _to)
        return(1:bool)
    return(0:bool)

def coinBalance():
    return(self.accounts[msg.sender].balance)

def coinBalanceOf(_addr:address):
    return(self.accounts[_addr].balance)

def approve(_addr:address):
    self.accounts[msg.sender].withdrawers[_addr] = 340282366920938463463374607431768211456

def isApproved(_proxy:address):
    return(self.accounts[msg.sender].withdrawers[_proxy] > 0)

def approveOnce(_addr:address, _maxValue:uint256):
    self.accounts[msg.sender].withdrawers[_addr] += _maxValue

def disapprove(_addr:address):
    self.accounts[msg.sender].withdrawers[_addr] = 0
"""


@pytest.mark.skipif(get_solidity() is None, reason="'solc' compiler not available")
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

event Changed(name:string:indexed)

def reserve(_name:string):
    if not self.records[sha3(_name:str)].owner:
        self.records[sha3(_name:str)].owner = msg.sender
        log(type=Changed, _name)
        return(1:bool)
    return(0:bool)

def owner(_name:string):
    return(self.records[sha3(_name:str)].owner:address)

def transfer(_name:string, _newOwner:address):
    if self.records[sha3(_name:str)].owner == msg.sender:
        log(type=Changed, _name)
        self.records[sha3(_name:str)].owner = _newOwner

def setAddr(_name:string, _a:address):
    if self.records[sha3(_name:str)].owner == msg.sender:
        log(type=Changed, _name)
        self.records[sha3(_name:str)].address = _a

def addr(_name:string):
    return(self.records[sha3(_name:str)].address:address)

def setContent(_name:string, _content:bytes32):
    if self.records[sha3(_name:str)].owner == msg.sender:
        log(type=Changed, _name)
        self.records[sha3(_name:str)].content = _content

def content(_name:string):
    return(self.records[sha3(_name:str)].content:bytes32)

def setSubRegistrar(_name:string, _subRegistrar:address):
    if self.records[sha3(_name:str)].owner == msg.sender:
        log(type=Changed, _name)
        self.records[sha3(_name:str)].sub = _subRegistrar

def subRegistrar(_name:string):
    return(self.records[sha3(_name:str)].sub:address)

def disown(_name:string):
    if self.records[sha3(_name:str)].owner == msg.sender:
        log(type=Changed, _name)
        self.records[sha3(_name:str)].owner = 0
"""

solidity_namereg = """
contract namereg {
    struct RegistryEntry {
        address owner;
        address addr;
        bytes32 content;
        address sub;
    }

    mapping ( string => RegistryEntry ) records;

    event Changed(string name, bytes32 indexed __hash_name);

    function reserve(string _name) returns (bool _success) {
        if (records[_name].owner == 0) {
            records[_name].owner = msg.sender;
            Changed(_name, sha3(_name));
            _success = true;
        }
        else _success = false;
    }

    function owner(string _name) returns (address _r) {
        _r = records[_name].owner;
    }

    function transfer(string _name, address _newOwner) {
        if (records[_name].owner == msg.sender) {
            records[_name].owner = _newOwner;
            Changed(_name, sha3(_name));
        }
    }

    function setAddr(string _name, address _addr) {
        if (records[_name].owner == msg.sender) {
            records[_name].addr = _addr;
            Changed(_name, sha3(_name));
        }
    }

    function addr(string _name) returns (address _r) {
        _r = records[_name].addr;
    }

    function setContent(string _name, bytes32 _content) {
        if (records[_name].owner == msg.sender) {
            records[_name].content = _content;
            Changed(_name, sha3(_name));
        }
    }

    function content(string _name) returns (bytes32 _r) {
        _r = records[_name].content;
    }

    function setSubRegistrar(string _name, address _subRegistrar) {
        if (records[_name].owner == msg.sender) {
            records[_name].sub = _subRegistrar;
            Changed(_name, sha3(_name));
        }
    }

    function subRegistrar(string _name) returns (address _r) {
        _r = records[_name].sub;
    }

    function disown(string _name) {
        if (records[_name].owner == msg.sender) {
            records[_name].owner = 0;
            Changed(_name, sha3(_name));
        }
    }
}
"""


@pytest.mark.skipif(get_solidity() is None, reason="'solc' compiler not available")
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
        assert o == [{"_event_type": b"Changed", "name": b'moose', "__hash_name": utils.sha3(b'moose')}] * 5


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

    function placeOrder(address _offerCurrency, uint256 _offerValue, address _wantCurrency, uint256 _wantValue) returns (uint256 _offerId) {
        if (currency(_offerCurrency).sendCoinFrom(msg.sender, _offerValue, this)) {
            _offerId = nextOrderId;
            nextOrderId += 1;
            orders[_offerId].creator = msg.sender;
            orders[_offerId].offerCurrency = _offerCurrency;
            orders[_offerId].offerValue = _offerValue;
            orders[_offerId].wantCurrency = _wantCurrency;
            orders[_offerId].wantValue = _wantValue;
        }
        else _offerId = 0;
    }

    function claimOrder(uint256 _offerId) returns (bool _success) {
        if (currency(orders[_offerId].wantCurrency).sendCoinFrom(msg.sender, orders[_offerId].wantValue, orders[_offerId].creator)) {
            currency(orders[_offerId].offerCurrency).sendCoin(orders[_offerId].offerValue, msg.sender);
            bytes32 currencyPair = bytes32(((uint256(orders[_offerId].offerCurrency) / 2**32) * 2**128) + (uint256(orders[_offerId].wantCurrency) / 2**32));
            Traded(currencyPair, orders[_offerId].creator, orders[_offerId].offerValue, msg.sender, orders[_offerId].wantValue);
            orders[_offerId].creator = 0;
            orders[_offerId].offerCurrency = 0;
            orders[_offerId].offerValue = 0;
            orders[_offerId].wantCurrency = 0;
            orders[_offerId].wantValue = 0;
            _success = true;
        }
        else _success = false;
    }

    function deleteOrder(uint256 _offerId) {
        currency(orders[_offerId].offerCurrency).sendCoin(orders[_offerId].offerValue, orders[_offerId].creator);
        orders[_offerId].creator = 0;
        orders[_offerId].offerCurrency = 0;
        orders[_offerId].offerValue = 0;
        orders[_offerId].wantCurrency = 0;
        orders[_offerId].wantValue = 0;
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

def placeOrder(_offerCurrency:address, _offerValue:uint256, _wantCurrency:address, _wantValue:uint256):
    if _offerCurrency.sendCoinFrom(msg.sender, _offerValue, self):
        _offerId = self.nextOrderId
        self.nextOrderId += 1
        self.orders[_offerId].creator = msg.sender
        self.orders[_offerId].offerCurrency = _offerCurrency
        self.orders[_offerId].offerValue = _offerValue
        self.orders[_offerId].wantCurrency = _wantCurrency
        self.orders[_offerId].wantValue = _wantValue
        return(_offerId:uint256)
    return(0:uint256)

def claimOrder(_offerId:uint256):
    if self.orders[_offerId].wantCurrency.sendCoinFrom(msg.sender, self.orders[_offerId].wantValue, self.orders[_offerId].creator):
        self.orders[_offerId].offerCurrency.sendCoin(self.orders[_offerId].offerValue, msg.sender)
        currencyPair = (self.orders[_offerId].offerCurrency / 2**32) * 2**128 + (self.orders[_offerId].wantCurrency / 2**32)
        log(type=Traded, currencyPair, self.orders[_offerId].creator, self.orders[_offerId].offerValue, msg.sender, self.orders[_offerId].wantValue)
        self.orders[_offerId].creator = 0
        self.orders[_offerId].offerCurrency = 0
        self.orders[_offerId].offerValue = 0
        self.orders[_offerId].wantCurrency = 0
        self.orders[_offerId].wantValue = 0
        return(1:bool)
    return(0:bool)

def deleteOrder(_offerId:uint256):
    self.orders[_offerId].offerCurrency.sendCoin(self.orders[_offerId].offerValue, self.orders[_offerId].creator)
    self.orders[_offerId].creator = 0
    self.orders[_offerId].offerCurrency = 0
    self.orders[_offerId].offerValue = 0
    self.orders[_offerId].wantCurrency = 0
    self.orders[_offerId].wantValue = 0
"""


@pytest.mark.skipif(get_solidity() is None, reason="'solc' compiler not available")
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
    for (oc, wc, e) in ((oc1, wc1, e2), (oc2, wc2, e1))[1:]:
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

@pytest.mark.skipif(get_solidity() is None, reason="'solc' compiler not available")
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


@pytest.mark.skipif(get_solidity() is None, reason="'solc' compiler not available")
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


compile_rich_contract = """
contract contract_add {
    function add7(uint a) returns(uint d) { return a + 7; }
    function add42(uint a) returns(uint d) { return a + 42; }
}
contract contract_sub {
    function subtract7(uint a) returns(uint d) { return a - 7; }
    function subtract42(uint a) returns(uint d) { return a - 42; }
}
"""


@pytest.mark.skipif(get_solidity() is None, reason="'solc' compiler not available")
def test_solidity_compile_rich():
    contract_info = get_solidity().compile_rich(compile_rich_contract)

    assert len(contract_info) == 2
    assert set(contract_info.keys()) == {'contract_add', 'contract_sub'}
    assert set(contract_info['contract_add'].keys()) == {'info', 'code'}
    assert set(contract_info['contract_add']['info'].keys()) == {
        'language', 'languageVersion', 'abiDefinition', 'source',
        'compilerVersion', 'developerDoc', 'userDoc'
    }
    assert contract_info['contract_add']['code'] == (
        "0x606060405260ad8060116000396000f30060606040526000357c0100000000000000"
        "00000000000000000000000000000000000000000090048063651ae239146041578063"
        "cb02919f14606657603f565b005b6050600480359060200150608b565b604051808281"
        "5260200191505060405180910390f35b6075600480359060200150609c565b60405180"
        "82815260200191505060405180910390f35b60006007820190506097565b919050565b"
        "6000602a8201905060a8565b91905056")
    assert contract_info['contract_sub']['code'] == (
        "0x606060405260ad8060116000396000f30060606040526000357c0100000000000000"
        "0000000000000000000000000000000000000000009004806361752024146041578063"
        "7aaef1a014606657603f565b005b6050600480359060200150608b565b604051808281"
        "5260200191505060405180910390f35b6075600480359060200150609c565b60405180"
        "82815260200191505060405180910390f35b60006007820390506097565b919050565b"
        "6000602a8203905060a8565b91905056")
    assert {
        defn['name']
        for defn
        in contract_info['contract_add']['info']['abiDefinition']
    } == {'add7', 'add42'}
    assert {
        defn['name']
        for defn
        in contract_info['contract_sub']['info']['abiDefinition']
    } == {'subtract7', 'subtract42'}
