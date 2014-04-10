#!/usr/bin/python
import processblock
import transactions
import blocks
import utils
import trie


def sha3(x):
    return utils.sha3(x).encode('hex')


def privtoaddr(x):
    if len(x) == 64:
        x = x.decode('hex')
    return utils.privtoaddr(x)


def mkgenesis(addr, value):
    return blocks.Block.genesis({addr: int(value)}).serialize().encode('hex')


def mktx(nonce, value, to, data):
    return transactions.Transaction(int(nonce), int(value), 10 ** 12, 10000, to, data.decode('hex')).serialize(False).encode('hex')


def mkcontract(nonce, value, code):
    return transactions.Transaction.contract(int(nonce), int(value), 10 ** 12, 10000, code.decode('hex')).serialize(False).encode('hex')


def sign(txdata, key):
    return transactions.Transaction.parse(txdata.decode('hex')).sign(key).serialize(True).encode('hex')


def applytx(blockdata, txdata, debug=0):
    block = blocks.Block(blockdata.decode('hex'))
    tx = transactions.Transaction.parse(txdata.decode('hex'))
    if debug:
        processblock.debug = 1
    o = processblock.apply_tx(block, tx)
    return block.serialize().encode('hex'), ''.join(o).encode('hex')


def getbalance(blockdata, address):
    block = blocks.Block(blockdata.decode('hex'))
    return block.get_balance(address)


def getcode(blockdata, address):
    block = blocks.Block(blockdata.decode('hex'))
    return block.get_code(address)


def getstate(blockdata):
    block = blocks.Block(blockdata.decode('hex'))
    return block.to_dict()


def dbget(x):
    db = trie.DB('statedb')
    print db.get(x.decode('hex'))
