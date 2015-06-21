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
