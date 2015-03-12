"""
also use json tx tests
https://github.com/ethereum/tests/wiki/Transaction-Tests

"""

import pytest
import pyethereum.processblock as processblock
import pyethereum.opcodes as opcodes
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as utils
import rlp
from tests.utils import new_db
import serpent

from pyethereum.slogging import get_logger, configure_logging
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
configure_logging(':trace')


@pytest.fixture(scope="module")
def accounts():
    k = utils.sha3('cow')
    v = utils.privtoaddr(k)
    k2 = utils.sha3('horse')
    v2 = utils.privtoaddr(k2)
    return k, v, k2, v2


@pytest.fixture(scope="module")
def mkgenesis(initial_alloc={}):
    return blocks.genesis(new_db(), initial_alloc)


@pytest.fixture(scope="module")
def get_transaction(gasprice=0, nonce=0):
    k, v, k2, v2 = accounts()
    tx = transactions.Transaction(
        nonce, gasprice, startgas=55000,
        to=v2, value=utils.denoms.finney * 10, data='').sign(k)
    return tx


namecoin_code =\
    '''
def register(k, v):
    if !self.storage[k]:
        self.storage[k] = v
        return(1)
    else:
        return(0)
'''


def test_gas_deduction():
    k, v, k2, v2 = accounts()
    blk = blocks.genesis(new_db(), {v: {"balance": utils.denoms.ether * 1}})
    v_old_balance = blk.get_balance(v)
    assert blk.get_balance(blk.coinbase) == 0
    gasprice = 1
    startgas = 55000
    code1 = serpent.compile(namecoin_code)
    tx1 = transactions.contract(0, gasprice, startgas, 0, code1).sign(k)
    success, addr = processblock.apply_transaction(blk, tx1)
    assert success
    assert blk.coinbase != v
    assert v_old_balance > blk.get_balance(v)
    assert v_old_balance == blk.get_balance(v) + blk.get_balance(blk.coinbase)
    intrinsic_gas_used = opcodes.GTXCOST
    intrinsic_gas_used += opcodes.GTXDATAZERO * tx1.data.count(chr(0))
    intrinsic_gas_used += opcodes.GTXDATANONZERO * (len(tx1.data) - tx1.data.count(chr(0)))
    assert v_old_balance - blk.get_balance(v) >= intrinsic_gas_used * gasprice


# TODO ##########################################
#
# test for remote block with invalid transaction
# test for multiple transactions from same address received
#    in arbitrary order mined in the same block
