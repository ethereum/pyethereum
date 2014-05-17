#!/usr/bin/python
import processblock
import transactions
import blocks
import utils


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
            args[0]: int(args[1])}).hex_serialize()
    else:
        o = {}
        for a in args:
            o[a[:a.find(':')]] = int(a[a.find(':') + 1:])
        return blocks.genesis(o).hex_serialize()


def mktx(nonce, to, value, data):
    return transactions.Transaction(
        int(nonce), 10 ** 12, 10000, to, int(value), data.decode('hex')
    ).hex_serialize(False)


def mkcontract(*args):
    return contract(*args)


def contract(nonce, value, code):
    return transactions.contract(
        int(nonce), 10 ** 12, 10000, int(value), code.decode('hex')
    ).hex_serialize(False)


def sign(txdata, key):
    return transactions.Transaction.hex_deserialize(txdata).sign(key).hex_serialize(True)

def alloc(blockdata, addr, val):
    val = int(val)
    block = blocks.Block.hex_deserialize(blockdata)
    block.delta_balance(addr, val)
    return block.hex_serialize()


def applytx(blockdata, txdata, debug=0, limit=2 ** 100):
    block = blocks.Block.hex_deserialize(blockdata)
    tx = transactions.Transaction.hex_deserialize(txdata)
    if tx.startgas > limit:
        raise Exception("Transaction is asking for too much gas!")
    if debug:
        processblock.debug = 1
    success, o = processblock.apply_tx(block, tx)
    return {
        "block": block.hex_serialize(),
        "result": ''.join(o).encode('hex') if tx.to else ''.join(o)
    }


def getbalance(blockdata, address):
    block = blocks.Block.hex_deserialize(blockdata)
    return block.get_balance(address)


def getcode(blockdata, address):
    block = blocks.Block.hex_deserialize(blockdata)
    return block.get_code(address).encode('hex')


def getstate(blockdata, address=None):
    block = blocks.Block.hex_deserialize(blockdata)
    if not address:
        return block.to_dict()
    else:
        return block.get_storage(address).to_dict()


def account_to_dict(blockdata, address):
    block = blocks.Block.hex_deserialize(blockdata)
    return block.account_to_dict(address)
