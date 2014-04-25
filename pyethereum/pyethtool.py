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


def mkgenesis(*args):
    return genesis(*args)


def genesis(*args):
    if len(args) == 2 and ':' not in args[0]:
        return blocks.genesis({
            args[0]: int(args[1])}).serialize().encode('hex')
    else:
        o = {}
        for a in args:
            o[a[:a.find(':')]] = int(a[a.find(':') + 1:])
        return blocks.genesis(o).serialize().encode('hex')


def mktx(nonce, to, value, data):
    return transactions.Transaction(
        int(nonce), 10 ** 12, 10000, to, int(value), data.decode('hex')
    ).serialize(False).encode('hex')


def mkcontract(*args):
    return contract(*args)


def contract(nonce, value, code):
    return transactions.contract(
        int(nonce), 10 ** 12, 10000, int(value), code.decode('hex')
    ).serialize(False).encode('hex')


def sign(txdata, key):
    return transactions.Transaction(
        txdata.decode('hex')).sign(key).serialize(True).encode('hex')


def alloc(blockdata, addr, val):
    val = int(val)
    block = blocks.Block(blockdata.decode('hex'))
    block.delta_balance(addr, val)
    return block.serialize().encode('hex')


def applytx(blockdata, txdata, debug=0, limit=2 ** 100):
    block = blocks.Block(blockdata.decode('hex'))
    tx = transactions.Transaction(txdata.decode('hex'))
    if tx.startgas > limit:
        raise Exception("Transaction is asking for too much gas!")
    if debug:
        processblock.debug = 1
    o = processblock.apply_tx(block, tx)
    return {
        "block": block.serialize().encode('hex'),
        "result": ''.join(o).encode('hex') if tx.to else ''.join(o)
    }


def getbalance(blockdata, address):
    block = blocks.Block(blockdata.decode('hex'))
    return block.get_balance(address)


def getcode(blockdata, address):
    block = blocks.Block(blockdata.decode('hex'))
    return block.get_code(address).encode('hex')


def getstate(blockdata, address=None):
    block = blocks.Block(blockdata.decode('hex'))
    if not address:
        return block.to_dict()
    else:
        return block.get_storage(address).to_dict()


def account_to_dict(blockdata, address):
    block = blocks.Block(blockdata.decode('hex'))
    return block.account_to_dict(address)


def dbget(x):
    db = trie.DB(utils.get_db_path())
    return db.get(x.decode('hex'))
