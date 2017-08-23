# -*- coding: utf8 -*-
import json
from os import path

import pytest

from ethereum.tools.tester import Chain, ABIContract
from ethereum.tools._solidity import (
    get_solidity,
    compile_file,
    solidity_get_contract_data,
)

SOLIDITY_AVAILABLE = get_solidity() is not None
CONTRACTS_DIR = path.join(path.dirname(__file__), 'contracts')


@pytest.mark.skipif(not SOLIDITY_AVAILABLE,
                    reason='solc compiler not available')
def test_abicontract_interface():
    """ Test for issue #370. """
    tester_state = Chain()

    contract_path = path.join(CONTRACTS_DIR, 'simple_contract.sol')
    contract_name = 'Simple'
    simple_compiled = compile_file(contract_path)
    simple_data = solidity_get_contract_data(
        simple_compiled,
        contract_path,
        contract_name,
    )
    simple_address = tester_state.contract(simple_data['bin'])

    # ABIContract class must accept json_abi
    abi_json = json.dumps(simple_data['abi']).encode('utf-8')

    abi = ABIContract(
        _tester=tester_state,
        _abi=abi_json,
        address=simple_address,
    )

    assert abi.test() == 1  # pylint: disable=no-member
