# -*- coding: utf8 -*-
from os import path

import pytest

from rlp.utils import encode_hex

from ethereum import tester
from ethereum import utils
from ethereum import _solidity
from ethereum._solidity import get_solidity

SOLIDITY_AVAILABLE = get_solidity() is not None
CONTRACTS_DIR = path.join(path.dirname(__file__), 'contracts')


def bytecode_is_generated(cinfo, cname):
    return 'code' in cinfo[cname] and len(cinfo[cname]['code']) > 10

@pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')
def test_library_from_file():
    state = tester.state()
    state.env.config['HOMESTEAD_FORK_BLKNUM'] = 0  # enable CALLCODE opcode

    library = state.abi_contract(
        None,
        path=path.join(CONTRACTS_DIR, 'seven_library.sol'),
        language='solidity',
    )

    libraries = {
        'SevenLibrary': encode_hex(library.address),
    }
    contract = state.abi_contract(
        None,
        path=path.join(CONTRACTS_DIR, 'seven_contract.sol'),
        libraries=libraries,
        language='solidity',
    )

    # pylint: disable=no-member
    assert library.seven() == 7
    assert contract.test() == 7


@pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')
def test_library_from_code():
    with open(path.join(CONTRACTS_DIR, 'seven_library.sol')) as handler:
        library_code = handler.read()

    with open(path.join(CONTRACTS_DIR, 'seven_contract_without_import.sol')) as handler:
        contract_code = handler.read()

    state = tester.state()
    state.env.config['HOMESTEAD_FORK_BLKNUM'] = 0  # enable CALLCODE opcode

    library = state.abi_contract(
        library_code,
        path=None,
        language='solidity',
    )

    libraries = {
        'SevenLibrary': encode_hex(library.address),
    }
    contract = state.abi_contract(
        contract_code,
        path=None,
        libraries=libraries,
        language='solidity',
    )

    # pylint: disable=no-member
    assert library.seven() == 7
    assert contract.test() == 7


def test_names():
    with open(path.join(CONTRACTS_DIR, 'contract_names.sol')) as handler:
        code = handler.read()

    names_in_order = _solidity.solidity_names(code)

    assert ('library', 'InComment') not in names_in_order
    assert ('contract', 'InComment') not in names_in_order

    assert ('contract', 'WithSpace') in names_in_order
    assert ('contract', 'WithLineBreak') in names_in_order

    assert names_in_order == [
        ('contract', 'AContract'),
        ('library', 'ALibrary'),
        ('contract', 'WithSpace'),
        ('contract', 'WithLineBreak'),
    ]


def test_symbols():
    assert _solidity.solidity_library_symbol('a') == '__a_____________________________________'
    assert _solidity.solidity_library_symbol('aaa') == '__aaa___________________________________'
    assert _solidity.solidity_library_symbol('a' * 40) == '__aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa__'

    # the address should be sanitized when it's given to the function
    with pytest.raises(Exception):
        _solidity.solidity_resolve_address(
            'beef__a_____________________________________cafe',
            '__a_____________________________________',
            '0x1111111111111111111111111111111111111111'
        )

    # the address needs to be hex encoded
    with pytest.raises(Exception):
        _solidity.solidity_resolve_address(
            'beef__a_____________________________________cafe',
            '__a_____________________________________',
            '111111111111111111111111111111111111111_'
        )

    assert _solidity.solidity_resolve_address(
        'beef__a_____________________________________cafe',
        '__a_____________________________________',
        '1111111111111111111111111111111111111111'
    ) == 'beef1111111111111111111111111111111111111111cafe'


@pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')
def test_interop():
    serpent_contract = """\
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

    state = tester.state()
    serpent_abi = state.abi_contract(serpent_contract)
    solidity_abi = state.abi_contract(solidity_contract, language='solidity')  # should be zoo
    solidity_address = utils.encode_hex(solidity_abi.address)

    # pylint: disable=no-member
    assert serpent_abi.sub1() == 5
    assert serpent_abi.main(solidity_abi.address) == 14

    assert solidity_abi.sub2() == 7
    assert solidity_abi.sub3(utils.encode_hex(solidity_abi.address)) == solidity_address
    assert solidity_abi.main(serpent_abi.address) == 10


@pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')
def test_constructor():
    constructor_contract = '''
    contract testme {
        uint value;
        function testme(uint a) {
            value = a;
        }
        function getValue() returns (uint) {
            return value;
        }
    }
    '''

    state = tester.state()
    contract = state.abi_contract(
        constructor_contract,
        language='solidity',
        constructor_parameters=(2, ),
    )

    # pylint: disable=no-member
    assert contract.getValue() == 2


@pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')
def test_solidity_compile_rich():
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

    contract_info = get_solidity().compile_rich(compile_rich_contract)

    assert len(contract_info) == 2
    assert set(contract_info.keys()) == {'contract_add', 'contract_sub'}
    assert set(contract_info['contract_add'].keys()) == {'info', 'code'}
    assert set(contract_info['contract_add']['info'].keys()) == {
        'language', 'languageVersion', 'abiDefinition', 'source',
        'compilerVersion', 'developerDoc', 'userDoc'
    }
    assert bytecode_is_generated(contract_info, 'contract_add')
    assert bytecode_is_generated(contract_info, 'contract_sub')

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


@pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')
def test_abi_contract():
    one_contract = """
    contract foo {
        function seven() returns (int256 y) {
            y = 7;
        }
        function mul2(int256 x) returns (int256 y) {
            y = x * 2;
        }
    }
    """

    state = tester.state()
    contract = state.abi_contract(one_contract, language='solidity')

    # pylint: disable=no-member
    assert contract.seven() == 7
    assert contract.mul2(2) == 4
    assert contract.mul2(-2) == -4

@pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')
def test_extra_args():
    src = """
    contract foo {
        function add7(uint a) returns(uint d) { return a + 7; }
        function add42(uint a) returns(uint d) { return a + 42; }
    }
    """

    contract_info = get_solidity().compile_rich(
        src,
        extra_args="--optimize-runs 100"
    )
    assert bytecode_is_generated(contract_info, 'foo')

    contract_info = get_solidity().compile_rich(
        src,
        extra_args=["--optimize-runs", "100"]
    )
    assert bytecode_is_generated(contract_info, 'foo')
