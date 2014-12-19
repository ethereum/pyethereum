import pytest
import pyethereum.processblock as processblock
import pyethereum.opcodes as opcodes
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as utils
import pyethereum.rlp as rlp
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
        nonce, gasprice, startgas=10000,
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
    blk = blocks.genesis(new_db(), {v: utils.denoms.ether * 1})
    v_old_balance = blk.get_balance(v)
    assert blk.get_balance(blk.coinbase) == 0
    gasprice = 1
    startgas = 10000
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


@pytest.mark.blk42
def test_deserialize_cpp_block_42():
    # 54.204.10.41 / NEthereum(++)/ZeroGox/v0.5.9/ncurses/Linux/g++ V:17L
    # E       TypeError: ord() expected a character, but string of length 0 found
    # 00bab55f2e230d4d56c7a2c11e7f3132663cc6734a5d4406f2e4359f4ab56593
    """
    RomanJ dumped the block
    BlockData [
      hash=00bab55f2e230d4d56c7a2c11e7f3132663cc6734a5d4406f2e4359f4ab56593
      parentHash=0df28c56b0cc32ceb55299934fca74ff63956ede0ffd430367ebcb1bb94d42fe
      unclesHash=1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347
      coinbase=a70abb9ed4b5d82ed1d82194943349bcde036812
      stateHash=203838e6ea7b03bce4b806ab4e5c069d5cd98ca2ba27a2d343d809cc6365e1ce
      txTrieHash=78aaa0f3b726f8d9273ba145e0efd4a6b21183412582449cc9457f713422b5ae
      difficulty=4142bd
      number=48
      minGasPrice=10000000000000
      gasLimit=954162
      gasUsed=500
      timestamp=1400678342
      extraData=null
      nonce=0000000000000000000000000000000000000000000000007d117303138a74e0

    TransactionData [
        hash=9003d7211c4b0d123778707fbdcabd93a6184be210390de4f73f89eae847556d
        nonce=null,
        gasPrice=09184e72a000,
        gas=01f4,
        receiveAddress=e559de5527492bcb42ec68d07df0742a98ec3f1e,
        value=8ac7230489e80000,
        data=null,
        signatureV=27,
        signatureR=18d646b8c4f7a804fdf7ba8da4d5dd049983e7d2b652ab902f7d4eaebee3e33b,
        signatureS=229ad485ef078d6e5f252db58dd2cce99e18af02028949896248aa01baf48b77]
        ]
    """

    genesis = mkgenesis(
        {'a70abb9ed4b5d82ed1d82194943349bcde036812': 100000000000000000000L})
    hex_rlp_data = \
        """f9016df8d3a00df28c56b0cc32ceb55299934fca74ff63956ede0ffd430367ebcb1bb94d42fea01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d4934794a70abb9ed4b5d82ed1d82194943349bcde036812a0203838e6ea7b03bce4b806ab4e5c069d5cd98ca2ba27a2d343d809cc6365e1cea078aaa0f3b726f8d9273ba145e0efd4a6b21183412582449cc9457f713422b5ae834142bd308609184e72a000830e8f328201f484537ca7c680a00000000000000000000000000000000000000000000000007d117303138a74e0f895f893f86d808609184e72a0008201f494e559de5527492bcb42ec68d07df0742a98ec3f1e888ac7230489e80000801ba018d646b8c4f7a804fdf7ba8da4d5dd049983e7d2b652ab902f7d4eaebee3e33ba0229ad485ef078d6e5f252db58dd2cce99e18af02028949896248aa01baf48b77a06e957f0f99502ad60a66a016f72957eff0f3a5bf791ad4a0606a44f35a6e09288201f4c0"""
    header_args, transaction_list, uncles = rlp.decode(
        hex_rlp_data.decode('hex'))
    for tx_data, _state_root, _gas_used_encoded in transaction_list:
        tx = transactions.Transaction.create(tx_data)
        logger.debug('Block #48 failing tx %r' % tx.to_dict())
        processblock.apply_transaction(genesis, tx)



# TODO ##########################################
#
# test for remote block with invalid transaction
# test for multiple transactions from same address received
#    in arbitrary order mined in the same block
