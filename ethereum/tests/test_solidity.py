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
def test_compile_from_file(tmpdir):
    contractsdir = tmpdir.mkdir("contracts")
    librarypath = contractsdir.join("Other.sol")
    librarypath.write("""library Other {
    function seven() returns (int256 y) {
        y = 7;
    }
}
""")
    userpath = contractsdir.join("user.sol")
    userpath.write("""import "Other.sol";
contract user {
    function test() returns (int256 seven) {
        seven = Other.seven();
    }
}
""")
    s = tester.state()
    # library calls need CALLCODE opcode:
    s.env.config['HOMESTEAD_FORK_BLKNUM'] = 0
    librarycontract = s.abi_contract(None, path=str(librarypath), language='solidity')
    assert librarycontract.seven() == 7
    libraryuser = s.abi_contract(None, path=str(userpath),
            # libraries still need to be supplied with their address:
            libraries={'Other': librarycontract.address.encode('hex')},
            language='solidity')
    assert libraryuser.test() == 7


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


@pytest.mark.xfail(reason="bytecode in test seems to be wrong")
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
