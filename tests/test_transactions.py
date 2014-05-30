import pytest
import tempfile
import pyethereum.processblock as processblock
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as utils
import pyethereum.rlp as rlp
import serpent

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

tempdir = tempfile.mktemp()

@pytest.fixture(scope="module")
def accounts():
    k = utils.sha3('cow')
    v = utils.privtoaddr(k)
    k2 = utils.sha3('horse')
    v2 = utils.privtoaddr(k2)
    return k, v, k2, v2


@pytest.fixture(scope="module")
def mkgenesis(initial_alloc={}):
    return blocks.genesis(initial_alloc)


@pytest.fixture(scope="module")
def get_transaction(gasprice=0, nonce=0):
    k, v, k2, v2 = accounts()
    tx = transactions.Transaction(
        nonce, gasprice, startgas=10000,
        to=v2, value=utils.denoms.finney * 10, data='').sign(k)
    return tx

def set_db():
    utils.data_dir.set(tempfile.mktemp())
    
namecoin_code =\
    '''
if !contract.storage[msg.data[0]]:
    contract.storage[msg.data[0]] = msg.data[1]
    return(1)
else:
    return(0)
'''

def test_gas_deduction():
    k, v, k2, v2 = accounts()
    blk = blocks.genesis({v: utils.denoms.ether * 1})
    v_old_balance = blk.get_balance(v)
    assert blk.get_balance(blk.coinbase) == 0
    gasprice = 1
    startgas = 10000
    code1 = serpent.compile(namecoin_code)
    tx1 = transactions.contract(0, gasprice, startgas, 0, code1).sign(k)
    success, addr = processblock.apply_transaction(blk, tx1)
    assert success
    assert blk.coinbase != v
    assert v_old_balance  > blk.get_balance(v)
    assert v_old_balance  == blk.get_balance(v) + blk.get_balance(blk.coinbase) 
    intrinsic_gas_used = processblock.GTXCOST + processblock.GTXDATA * len(tx1.data)
    assert v_old_balance  - blk.get_balance(v) >= intrinsic_gas_used * gasprice



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
    
    genesis = mkgenesis({'a70abb9ed4b5d82ed1d82194943349bcde036812':100000000000000000000L})
    hex_rlp_data = \
        """f9016df8d3a00df28c56b0cc32ceb55299934fca74ff63956ede0ffd430367ebcb1bb94d42fea01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d4934794a70abb9ed4b5d82ed1d82194943349bcde036812a0203838e6ea7b03bce4b806ab4e5c069d5cd98ca2ba27a2d343d809cc6365e1cea078aaa0f3b726f8d9273ba145e0efd4a6b21183412582449cc9457f713422b5ae834142bd308609184e72a000830e8f328201f484537ca7c680a00000000000000000000000000000000000000000000000007d117303138a74e0f895f893f86d808609184e72a0008201f494e559de5527492bcb42ec68d07df0742a98ec3f1e888ac7230489e80000801ba018d646b8c4f7a804fdf7ba8da4d5dd049983e7d2b652ab902f7d4eaebee3e33ba0229ad485ef078d6e5f252db58dd2cce99e18af02028949896248aa01baf48b77a06e957f0f99502ad60a66a016f72957eff0f3a5bf791ad4a0606a44f35a6e09288201f4c0"""
    header_args, transaction_list, uncles = rlp.decode(
        hex_rlp_data.decode('hex'))
    for tx_data, _state_root, _gas_used_encoded in transaction_list:
        tx = transactions.Transaction.create(tx_data)
        logger.debug('Block #48 failing tx %r',tx.to_dict())
        processblock.apply_transaction(genesis, tx)



def deserialize_child(parent, rlpdata):
    """
    deserialization w/ replaying transactions
    """
    header_args, transaction_list, uncles = rlp.decode(rlpdata)
    assert len(header_args) == len(blocks.block_structure)
    kargs = dict(transaction_list=transaction_list, uncles=uncles)
    # Deserialize all properties
    for i, (name, typ, default) in enumerate(blocks.block_structure):
        kargs[name] = utils.decoders[typ](header_args[i])

    block = blocks.Block.init_from_parent(parent, kargs['coinbase'],
                                   extra_data=kargs['extra_data'],
                                   timestamp=kargs['timestamp'])
    block.finalize()  # this is the first potential state change
    # replay transactions
    for tx_lst_serialized, _state_root, _gas_used_encoded in transaction_list:

        tx = transactions.Transaction.create(tx_lst_serialized)
        logger.debug('applying %r', tx)
        logger.debug('applying %r', tx.to_dict())
        success, output = processblock.apply_transaction(block, tx)
        logger.debug('success: %r', success)
        assert utils.decode_int(_gas_used_encoded) == block.gas_used
        assert _state_root == block.state.root_hash


    # checks
    assert block.prevhash == parent.hash
    assert block.tx_list_root == kargs['tx_list_root']
    assert block.gas_used == kargs['gas_used']
    assert block.gas_limit == kargs['gas_limit']
    assert block.timestamp == kargs['timestamp']
    assert block.difficulty == kargs['difficulty']
    assert block.number == kargs['number']
    assert block.extra_data == kargs['extra_data']
    assert utils.sha3(rlp.encode(block.uncles)) == kargs['uncles_hash']
    assert block.state.root_hash == kargs['state_root']

    block.uncles_hash = kargs['uncles_hash']
    block.nonce = kargs['nonce']
    block.min_gas_price = kargs['min_gas_price']

    return block



@pytest.mark.blk1
def test_receive_blk1_cpp_chain():
    hex_rlp_data = """f9072df8d3a077ef4fdaf389dca53236bcf7f72698e154eab2828f86fbc4fc6cd9225d285c89a01dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d493479476f5eabe4b342ee56b8ceba6ab2a770c3e2198e7a0faa0ca43105f667dceb168eb4e0cdc98ef28a9da5c381edef70d843207601719a06785f3860460b2aa29122698e83a5151b270e82532c1663e89e3df8c5445b8ca833ff000018609184e72a000830f3e6f8227d2845387c58f80a000000000000000000000000000000000000000000000000094148d7738f78c04f90654f8c6f8a0808609184e72a00082271094000000000000000000000000000000000000000080b83a33604557602a5160106000396000f200604556330e0f602a59366000530a0f602a596020600053013560005335576040600053016000546009581ca033a6bfa5eb2f4b63f1b98bed9a987d096d32e56deecb050367c84955508f5365a015034e7574ec073f0c448aac1d9f844387610dfef5342834b6825fbc35df5913a0ee258e73d41ada73d8d6071ba7d236fbbe24fcfb9627fbd4310e24ffd87b961a8203e9f90194f9016d018609184e72a00082271094000000000000000000000000000000000000000080b901067f4e616d65526567000000000000000000000000000000000000000000000000003057307f4e616d6552656700000000000000000000000000000000000000000000000000577f436f6e666967000000000000000000000000000000000000000000000000000073ccdeac59d35627b7de09332e819d5159e7bb72505773ccdeac59d35627b7de09332e819d5159e7bb72507f436f6e666967000000000000000000000000000000000000000000000000000057336045576041516100c56000396000f20036602259604556330e0f600f5933ff33560f601e5960003356576000335700604158600035560f602b590033560f603659600033565733600035576000353357001ca0f3c527e484ea5546189979c767b69aa9f1ad5a6f4b6077d4bccf5142723a67c9a069a4a29a2a315102fcd0822d39ad696a6d7988c993bb2b911cc2a78bb8902d91a01ebe4782ea3ed224ccbb777f5de9ee7b5bbb282ac08f7fa0ef95d3d1c1c6d1a1820ef7f8ccf8a6028609184e72a00082271094ccdeac59d35627b7de09332e819d5159e7bb725080b84000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002d0aceee7e5ab874e22ccf8d1a649f59106d74e81ba095ad45bf574c080e4d72da2cfd3dbe06cc814c1c662b5f74561f13e1e75058f2a057745a3db5482bccb5db462922b074f4b79244c4b1fa811ed094d728e7b6da92a08599ea5d6cb6b9ad3311f0d82a3337125e05f4a82b9b0556cb3776a6e1a02f8782132df8abf885038609184e72a000822710942d0aceee7e5ab874e22ccf8d1a649f59106d74e880a047617600000000000000000000000000000000000000000000000000000000001ca09b5fdabd54ebc284249d2d2df6d43875cb86c52bd2bac196d4f064c8ade054f2a07b33f5c8b277a408ec38d2457441d2af32e55681c8ecb28eef3d2a152e8db5a9a0227a67fceb1bf4ddd31a7047e24be93c947ab3b539471555bb3509ed6e393c8e82178df90277f90250048609184e72a0008246dd94000000000000000000000000000000000000000080b901e961010033577f476176436f696e0000000000000000000000000000000000000000000000000060005460006000600760006000732d0aceee7e5ab874e22ccf8d1a649f59106d74e860645c03f150436000576000600157620f424060025761017d5161006c6000396000f2006020360e0f61013f596020600060003743602054600056600054602056602054437f6e00000000000000000000000000000000000000000000000000000000000000560e0f0f61008059437f6e0000000000000000000000000000000000000000000000000000000000000057600060205461040060005304600053036000547f64000000000000000000000000000000000000000000000000000000000000005660016000030460406000200a0f61013e59600160205301602054600a6020530b0f6100f45961040060005304600053017f6400000000000000000000000000000000000000000000000000000000000000576020537f6900000000000000000000000000000000000000000000000000000000000000576000537f640000000000000000000000000000000000000000000000000000000000000057006040360e0f0f61014a59003356604054600035566060546020356080546080536040530a0f610169590060805360405303335760805360605301600035571ba0190fc7ab634dc497fe1656fde523a4c26926d51a93db2ba37af8e83c3741225da066ae0ec1217b0ca698a5369d4881e1c4cbde56af9931ebf9281580a23b659c08a051f947cb2315d0259f55848c630caa10cd91d6e44ff8bad7758c65b25e2191308227d2c0"""
    set_db()
    genesis = blocks.genesis()
    deserialize_child(genesis,  hex_rlp_data.decode('hex'))


# TODO ##########################################
#
# test for remote block with invalid transaction
# test for multiple transactions from same address received
#    in arbitrary order mined in the same block
