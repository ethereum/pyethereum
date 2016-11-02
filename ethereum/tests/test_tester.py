# -*- coding: utf8 -*-
import json
from os import path

import pytest

from ethereum.tester import (state, ABIContract, latest_state,
                             LATEST_APPLIED_FORK_BLKNUM)
from ethereum._solidity import get_solidity, compile_file

SOLIDITY_AVAILABLE = get_solidity() is not None
CONTRACTS_DIR = path.join(path.dirname(__file__), 'contracts')


def test_latest_state():
    assert latest_state().block.number == LATEST_APPLIED_FORK_BLKNUM
    assert latest_state(blknum=42).block.number == 42
    assert latest_state(blknum=0).block.number == 0
    with pytest.raises(ValueError):
        latest_state(blknum=[1])


@pytest.mark.skipif(not SOLIDITY_AVAILABLE, reason='solc compiler not available')
def test_abicontract_interface():
    """ Test for issue #370. """
    tester_state = state()

    contract_path = path.join(CONTRACTS_DIR, 'simple_contract.sol')
    simple_compiled = compile_file(contract_path)
    simple_address = tester_state.evm(simple_compiled['Simple']['bin'])

    # ABIContract class must accept json_abi
    abi_json = json.dumps(simple_compiled['Simple']['abi']).encode('utf-8')

    abi = ABIContract(
        _state=tester_state,
        _abi=abi_json,
        address=simple_address,
        listen=False,
        log_listener=None,
        default_key=None,
    )

    assert abi.test() == 1  # pylint: disable=no-member
