from rlp.utils import encode_hex
from ethereum import tester

def needs_solidity(function):
    def decorated(*args, **kwargs):
        if 'solidity' in tester.languages:
            return function(*args, **kwargs)

    return decorated

serpent_contract = """
extern solidity: [sub2:_:i]

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
}
"""

@needs_solidity
def test_interop():
    s = tester.state()
    c1 = s.abi_contract(serpent_contract)
    c2 = s.abi_contract(solidity_contract, language='solidity')  # should be zoo
    assert c1.sub1() == 5
    assert c2.sub2() == 7
    assert c1.main(c2.address) == 14
    assert c2.main(c1.address) == 10

constructor_contract = """
contract gondor {
    address public ruler;

    function gondor(address steward) {
        if (steward == 0x0) {
            ruler = msg.sender;
        } else {
            ruler = steward;
        }
    }
}
"""

@needs_solidity
def test_abi_constructor():
    s = tester.state()
    c1 = s.abi_contract(
        constructor_contract, language='solidity',
        contract_name='gondor'
    )
    c2 = s.abi_contract(
        constructor_contract, constructor_args=[tester.a1],
        language='solidity', contract_name='gondor'
    )
    assert c1.ruler() != c2.ruler()
    assert c2.ruler() == encode_hex(tester.a1)

@needs_solidity
def test_constructor():
    s = tester.state()
    a1 = s.contract(constructor_contract, language='solidity')
    a2 = s.contract(
        constructor_contract, constructor_args=[
            {'type': 'address', 'val': tester.a1
        }], language='solidity'
    )
    _abi = tester.languages['solidity'].mk_full_signature(constructor_contract)
    c1 = tester.ABIContract(s, _abi, a1)
    c2 = tester.ABIContract(s, _abi, a2)
    assert c1.ruler() != c2.ruler()
    assert c2.ruler() == encode_hex(tester.a1)
