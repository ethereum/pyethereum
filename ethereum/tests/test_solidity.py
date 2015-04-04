from ethereum import tester
import pytest
serpent_contract = """
extern solidity: [sub2:_:i]

def main(a):
    return(a.sub2() * 2)

def sub1():
    return(5)

"""

solidity_contract = """
contract serpent { function sub1() returns (int256 y) {} }

contract foo {
    function main(address a) returns (int256 y) {
        y = serpent(a).sub1() * 2;
    }
    function sub2() returns (int256 y) {
        y = 7;
    }
}

"""


@pytest.mark.xfail  # pysol is currently broken
def test_interop():
    s = tester.state()
    c1 = s.abi_contract(serpent_contract)
    c2 = s.abi_contract(solidity_contract, language='solidity')
    # assert c1.sub1() == 5
    # assert c2.sub2() == 7
    # assert c1.main(c2.address) == 14
    # assert c2.main(c1.address) == 10
