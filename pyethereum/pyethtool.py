#!/usr/bin/python
import processblock
import transactions
import blocks
import rlp
import utils
import sys, re
import trie

def sha3(x):
    return utils.sha3(x).encode('hex')

def privtoaddr(x):
    if len(x) == 64: x = x.decode('hex')
    return utils.privtoaddr(x)

def mkgenesis(addr,value):
    return blocks.Block.genesis({ addr: int(value) }).serialize().encode('hex')

def mktx(nonce,to,value,data):
    return transactions.Transaction(int(nonce),int(value),10**12,10000,to,data.decode('hex')).serialize(False).encode('hex')

def mkcontract(nonce,value,code):
    return transactions.Transaction.contract(int(nonce), int(value),10**12,10000,code.decode('hex')).serialize(False).encode('hex')

def sign(txdata,key):
    return transactions.Transaction.parse(txdata.decode('hex')).sign(key).serialize(True).encode('hex')

def applytx(blockdata,txdata,debug=0):
    block = blocks.Block(blockdata.decode('hex'))
    tx = transactions.Transaction.parse(txdata.decode('hex'))
    if debug: processblock.debug = 1
    o = processblock.apply_tx(block,tx)
    return block.serialize().encode('hex'), ''.join(o).encode('hex')

def getbalance(blockdata,address):
    block = blocks.Block(blockdata.decode('hex'))
    return block.get_balance(address)

def getcode(blockdata,address):
    block = blocks.Block(blockdata.decode('hex'))
    return block.get_code(address)

def dbget(x):
    db = trie.DB('statedb')
    print db.get(x.decode('hex'))
    
if len(sys.argv) == 1:
    print "pyethtool <command> <arg1> <arg2> ..."
else:
    cmd = sys.argv[2] if sys.argv[1][0] == '-' else sys.argv[1]
    if sys.argv[1] == '-s':
        args = re.findall(r'\S\S*',sys.stdin.read())+sys.argv[3:]
    elif sys.argv[1] == '-B':
        args = [sys.stdin.read()]+sys.argv[3:]
    elif sys.argv[1] == '-b':
        args = [sys.stdin.read()[:-1]]+sys.argv[3:] # remove trailing \n
    elif sys.argv[1] == '-j':
        args = [json.loads(sys.stdin.read())]+sys.argv[3:]
    elif sys.argv[1] == '-J':
        args = json.loads(sys.stdin.read())+sys.argv[3:]
    else:
        cmd = sys.argv[1]
        args = sys.argv[2:]
    o = vars()[cmd](*args)
    if isinstance(o,(list,dict)): print json.dumps(o)
    else: print o
