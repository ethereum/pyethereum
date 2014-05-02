import serpent
import processblock as pb
import blocks as b
import transactions as t
import utils as u
import sys

k = u.sha3('cow')
v = u.privtoaddr(k)

k2 = u.sha3('horse')
v2 = u.privtoaddr(k2)

print("Starting boring transfer test")
blk = b.genesis({v: u.denoms.ether * 1})

assert blk.hex_hash() == \
    b.Block.deserialize(blk.serialize()).hex_hash()


# Give tx2 some money

gasprice = 0
startgas = 10000

# nonce,gasprice,startgas,to,value,data,v,r,s
tx = t.Transaction(0, gasprice, startgas, v2, u.denoms.finney * 10, '').sign(k)

assert blk in set([blk])
assert tx in set([tx])
assert tx.hex_hash() == \
    t.Transaction.deserialize(tx.serialize()).hex_hash()
assert tx.hex_hash() == \
    t.Transaction.hex_deserialize(tx.hex_serialize()).hex_hash()
assert tx in set([tx])

assert not tx in blk.get_transactions()

print("Balance of v1: ", blk.get_balance(v), v)
success, res = pb.apply_tx(blk, tx)
assert tx in blk.get_transactions()
print("applied transaction", success, res)
print("New balance of v1: ", blk.get_balance(v), v)
print("New balance of v2: ", blk.get_balance(v2), v2)
print("New balance of coinbase: ", blk.get_balance(blk.coinbase), blk.coinbase)
print ('Transactions in block', blk, blk.get_transactions())


assert blk.hex_hash() == \
    b.Block.hex_deserialize(blk.hex_serialize()).hex_hash()


assert blk.get_balance(v) == u.denoms.finney * 990
assert blk.get_balance(v2) == u.denoms.finney * 10

print("Starting namecoin tests")
blk = b.genesis({v: u.denoms.ether * 1})
scode1 = '''
if !contract.storage[msg.data[0]]:
    contract.storage[msg.data[0]] = msg.data[1]
    return(1)
else:
    return(0)
'''
code1 = serpent.compile(scode1)
# print("AST", serpent.rewrite(serpent.parse(scode1)))
# print("Assembly", serpent.compile_to_assembly(scode1))
tx1 = t.contract(0, gasprice, startgas, 0, code1).sign(k)
s, addr = pb.apply_tx(blk, tx1)
snapshot = blk.snapshot()
print("Contract address", addr)
tx2 = t.Transaction(1, gasprice, startgas, addr, 0, serpent.encode_datalist(['george', 45]))
tx2.sign(k)
s, o = pb.apply_tx(blk, tx2)
print("Result of registering george:45: ", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [1]
tx3 = t.Transaction(2, gasprice, startgas, addr, 0, serpent.encode_datalist(['george', 20])).sign(k)
s, o = pb.apply_tx(blk, tx3)
print("Result of registering george:20: ", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [0]
tx4 = t.Transaction(3, gasprice, startgas, addr, 0, serpent.encode_datalist(['harry', 60])).sign(k)
s, o = pb.apply_tx(blk, tx4)
print("Result of registering harry:60: ", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [1]

scode2 = '''
if !contract.storage[1000]:
    contract.storage[1000] = 1
    contract.storage[0x%s] = 1000
    return(1)
elif msg.datasize == 1:
    addr = msg.data[0]
    return(contract.storage[addr])
else:
    from = msg.sender
    fromvalue = contract.storage[from]
    to = msg.data[0]
    value = msg.data[1]
    if fromvalue >= value:
        contract.storage[from] = fromvalue - value
        contract.storage[to] = contract.storage[to] + value
        return(1)
    else:
        return(0)
''' % v
code2 = serpent.compile(scode2)
# print("AST", serpent.rewrite(serpent.parse(scode2)))
# print("Assembly", serpent.compile_to_assembly(scode2))
print("Starting currency contract tests")
blk = b.genesis({v: 10**18})
tx4 = t.contract(0, gasprice, startgas, 0, code2).sign(k)
s, addr = pb.apply_tx(blk, tx4)
print("Contract address", addr)
tx5 = t.Transaction(1, gasprice, startgas, addr, 0, '').sign(k)
s, o = pb.apply_tx(blk, tx5)
print("Initialization finished: ", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [1]
tx6 = t.Transaction(2, gasprice, startgas, addr, 0, serpent.encode_datalist([v2, 200])).sign(k)
s, o = pb.apply_tx(blk, tx6)
print("Result of sending v->v2 200: ", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [1]
tx7 = t.Transaction(3, gasprice, startgas, addr, 0, serpent.encode_datalist([v2, 900])).sign(k)
s, o = pb.apply_tx(blk, tx7)
print("Result of sending v->v2 900: ", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [0]
tx8 = t.Transaction(4, gasprice, startgas, addr, 0, serpent.encode_datalist([v])).sign(k)
s, o = pb.apply_tx(blk, tx8)
print("Result of querying v: ", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [800]
tx9 = t.Transaction(5, gasprice, startgas, addr, 0, serpent.encode_datalist([v2])).sign(k)
s, o = pb.apply_tx(blk, tx9)
print("Result of querying v2: ", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [200]

scode3 = '''
if !contract.storage[1000]:
    contract.storage[1000] = 1
    contract.storage[1001] = msg.sender
    return(0)
elif msg.sender == contract.storage[1001] and msg.datasize == 2:
    contract.storage[msg.data[0]] = msg.data[1]
    return(1)
else:
    return(contract.storage[msg.data[0]])
'''
code3 = serpent.compile(scode3)
# print("AST", serpent.rewrite(serpent.parse(scode3)))
# print("Assembly", serpent.compile_to_assembly(scode3))
print "Starting data feed tests"
blk = b.genesis({v: 10**18, v2: 10**18})
tx10 = t.contract(0, gasprice, startgas, 0, code3).sign(k)
s, addr = pb.apply_tx(blk, tx10)
print("Address:", addr)
tx11 = t.Transaction(1, gasprice, startgas, addr, 0, '').sign(k)
s, o = pb.apply_tx(blk, tx11)
print("Initialization complete", serpent.decode_datalist(o))
tx12 = t.Transaction(2, gasprice, startgas, addr, 0, serpent.encode_datalist([500])).sign(k)
s, o = pb.apply_tx(blk, tx12)
print("Value at 500", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [0]
tx13 = t.Transaction(3, gasprice, startgas, addr, 0, serpent.encode_datalist([500, 726])).sign(k)
s, o = pb.apply_tx(blk, tx13)
print("Set value at 500 to 726", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [1]
tx14 = t.Transaction(4, gasprice, startgas, addr, 0, serpent.encode_datalist([500])).sign(k)
s, o = pb.apply_tx(blk, tx14)
print("Value at 500", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [726]

scode4 = '''
if !contract.storage[1000]:
    contract.storage[1000] = msg.sender
    contract.storage[1002] = msg.value
    contract.storage[1003] = msg.data[0]
    return(1)
elif !contract.storage[1001]:
    ethvalue = contract.storage[1002]
    if msg.value >= ethvalue:
        contract.storage[1001] = msg.sender
    othervalue = ethvalue * msg(0x%s,0,tx.gas-100,[contract.storage[1003]],1)
    contract.storage[1004] = othervalue
    contract.storage[1005] = block.timestamp + 86400
    return([2,othervalue],2)
else:
    othervalue = contract.storage[1004]
    ethvalue = othervalue / msg(0x%s,0,tx.gas-100,[contract.storage[1003]],1)
    if ethvalue >= contract.balance:
        send(contract.storage[1000],contract.balance,tx.gas-100)
        return(3)
    elif block.timestamp > contract.storage[1005]:
        send(contract.storage[1001],contract.balance - ethvalue,tx.gas-100)
        send(contract.storage[1000],ethvalue,tx.gas-100)
        return(4)
    else:
        return(5)
''' % (addr, addr)
code4 = serpent.compile(scode4)
# print("AST", serpent.rewrite(serpent.parse(scode4)))
# print("Assembly", serpent.compile_to_assembly(scode4))
# important: no new genesis block
print "Starting hedge tests"
tx15 = t.contract(5, gasprice, startgas, 0, code4).sign(k)
s, addr2 = pb.apply_tx(blk, tx15)
print("Address:", addr2)
tx16 = t.Transaction(6, gasprice, startgas, addr2, 10**17, serpent.encode_datalist([500])).sign(k)
s, o = pb.apply_tx(blk, tx16)
print("First participant added", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [1]
tx17 = t.Transaction(0, gasprice, startgas, addr2, 10**17, serpent.encode_datalist([500])).sign(k2)
s, o = pb.apply_tx(blk, tx17)
print("Second participant added, USDvalue settled", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [2, 72600000000000000000L]
snapshot = blk.snapshot()
tx18 = t.Transaction(7, gasprice, startgas, addr2, 0, '').sign(k)
s, o = pb.apply_tx(blk, tx18)
print("Attempting to cash out immediately", o if o == -1 else serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [5]
tx19 = t.Transaction(8, gasprice, startgas, addr, 0, serpent.encode_datalist([500, 300])).sign(k)
s, o = pb.apply_tx(blk, tx19)
print("Changing value to 300", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [1]
tx20 = t.Transaction(9, gasprice, startgas, addr2, 0, '').sign(k)
print("Old balances", blk.get_balance(v), blk.get_balance(v2))
s, o = pb.apply_tx(blk, tx20)
print("Attempting to cash out with value drop", o if o == -1 else serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [3]
print("New balances", blk.get_balance(v), blk.get_balance(v2))
blk.revert(snapshot)
blk.timestamp += 200000
print("Old balances", blk.get_balance(v), blk.get_balance(v2))
tx21 = t.Transaction(7, gasprice, startgas, addr, 0, serpent.encode_datalist([500, 1452])).sign(k)
s, o = pb.apply_tx(blk, tx21)
print("Changing value to 1452", serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [1]
tx22 = t.Transaction(8, gasprice, 2000, addr2, 0, '').sign(k)
s, o = pb.apply_tx(blk, tx22)
print("Attempting to cash out after value increase and expiry", o if o == -1 else serpent.decode_datalist(o))
assert serpent.decode_datalist(o) == [4]
print("New balances", blk.get_balance(v), blk.get_balance(v2))
