from ethereum import blocks
from ethereum import processblock
from ethereum import transactions
from ethereum import utils
import rlp
from ethereum import trie


def mk_transaction_spv_proof(block, tx):
    trie.proof.push(trie.RECORDING)
    processblock.apply_transaction(block, tx)
    o = trie.proof.get_nodelist()
    trie.proof.pop()
    o2 = list(map(rlp.decode, list(set(map(rlp.encode, o)))))
    return o2


def verify_transaction_spv_proof(block, tx, proof):
    trie.proof.push(trie.VERIFYING, proof)
    try:
        processblock.apply_transaction(block, tx)
        trie.proof.pop()
        return True
    except Exception as e:
        print(e)
        trie.proof.pop()
        return False


def mk_independent_transaction_spv_proof(block, index):
    block = blocks.Block.init_from_header(block.db, block.list_header())
    tx = transactions.Transaction.create(block.get_transaction(index))
    block.get_receipt(index)
    if index > 0:
        pre_med, pre_gas, _, _ = block.get_receipt(index - 1)
    else:
        pre_med, pre_gas = block.get_parent().state_root, 0
    block.state_root = pre_med
    block.gas_used = pre_gas
    nodes = mk_transaction_spv_proof(block, tx)
    nodes.extend(block.transactions.produce_spv_proof(rlp.encode(utils.encode_int(index))))
    if index > 0:
        nodes.extend(block.transactions.produce_spv_proof(rlp.encode(utils.encode_int(index - 1))))
    nodes = list(map(rlp.decode, list(set(map(rlp.encode, nodes)))))
    print(nodes)
    return rlp.encode([utils.encode_int(64), block.get_parent().list_header(),
                       block.list_header(), utils.encode_int(index), nodes])


def verify_independent_transaction_spv_proof(db, proof):
    _, prevheader, header, index, nodes = rlp.decode(proof)
    index = utils.decode_int(index)
    pb = blocks.Block.deserialize_header(prevheader)
    b = blocks.Block.init_from_header(db, header)
    b.set_proof_mode(blocks.VERIFYING, nodes)
    if index != 0:
        pre_med, pre_gas, _, _ = b.get_receipt(index - 1)
    else:
        pre_med, pre_gas = pb['state_root'], ''
        if utils.sha3(rlp.encode(prevheader)) != b.prevhash:
            return False
    b.state_root = pre_med
    b.gas_used = utils.decode_int(pre_gas)
    tx = b.get_transaction(index)
    post_med, post_gas, bloom, logs = b.get_receipt(index)
    tx = transactions.Transaction.create(tx)
    o = verify_transaction_spv_proof(b, tx, nodes)
    if b.state_root == post_med:
        if b.gas_used == utils.decode_int(post_gas):
            if [x.serialize() for x in b.logs] == logs:
                if b.mk_log_bloom() == bloom:
                    return o
    return False
