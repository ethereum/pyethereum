import pytest
from pyethereum import tester, utils, abi

serpent_contract = """
extern solidity: [sub:_:i]

def main(a):
    return(a.sub() * 2)

def sub():
    return(5)

"""

solidity_contract = """
contract foo {
    function main(address a) returns (int256 y) {
        y = a.sub() * 2;
    }
    function sub() returns (int256 y) {
        y = 7;
    }
}

"""


def test_interop():
    s = tester.state()
    c1 = s.abi_contract(serpent_contract)
    c2 = s.abi_contract(solidity_contract, language='solidity')
    assert c1.sub() == 5
    assert c2.sub() == 7
    assert c1.main(c2.address) == 14
    assert c2.main(c1.address) == 10
