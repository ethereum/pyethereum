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

print "Starting boring transfer test"
blk = b.genesis({ v: 10**18 })

assert blk.hex_hash() == b.Block.hex_deserialize(blk.hex_serialize()).hex_hash()

# Give tx2 some money

gasprice = 10**12
startgas = 1000

# nonce,gasprice,startgas,to,value,data,v,r,s
tx = t.Transaction(0,gasprice,startgas,v2,10**16,'').sign(k)

assert tx.hex_hash() == t.Transaction.deserialize(tx.serialize()).hex_hash()
assert tx.hex_hash() ==  t.Transaction.hex_deserialize(tx.hex_serialize()).hex_hash()

pb.apply_tx(blk,tx)
print "New balance of v1: ", blk.get_balance(v)
print "New balance of v2: ", blk.get_balance(v2)

print "Starting namecoin tests"
blk = b.genesis({ v: 10**18 })
scode1 = '''
if !contract.storage[msg.data[0]]:
    contract.storage[msg.data[0]] = msg.data[1]
    return(1)
else:
    return(0)
'''
code1 = serpent.compile(scode1)
print "AST", serpent.rewrite(serpent.parse(scode1))
print "Assembly", serpent.compile_to_assembly(scode1)
tx1 = t.contract(0,0,gasprice,startgas,code1).sign(k)
s, addr = pb.apply_tx(blk,tx1)
snapshot = blk.snapshot()
print "Contract address", addr.encode('hex')
tx2 = t.Transaction(1,gasprice,startgas,addr,0,serpent.encode_datalist(['george',45]))
tx2.sign(k)
s,o = pb.apply_tx(blk,tx2)
print "Result of registering george:45: ", serpent.decode_datalist(o)
tx3 = t.Transaction(2,gasprice,startgas,addr,0,serpent.encode_datalist(['george',20])).sign(k)
s,o = pb.apply_tx(blk,tx3)
print "Result of registering george:20: ", serpent.decode_datalist(o)
tx4 = t.Transaction(3,gasprice,startgas,addr,0,serpent.encode_datalist(['harry',60])).sign(k)
s,o = pb.apply_tx(blk,tx4)
print "Result of registering harry:60: ", serpent.decode_datalist(o)

scode2 = '''
if !contract.storage[1000]:
    contract.storage[1000] = 1
    contract.storage[0x%s] = 1000
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
print "AST", serpent.rewrite(serpent.parse(scode2))
print "Assembly", serpent.compile_to_assembly(scode2)
print "Starting currency contract tests"
blk = b.genesis({ v: 10**18 })
tx4 = t.contract(0,0,gasprice,startgas,code2).sign(k)
s, addr = pb.apply_tx(blk,tx4)
print "Contract address", addr.encode('hex')
tx5 = t.Transaction(1,gasprice,startgas,addr,0,'').sign(k)
s,o = pb.apply_tx(blk,tx5)
print "Initialization finished"
tx6 = t.Transaction(2,gasprice,startgas,addr,0,serpent.encode_datalist([v2,200])).sign(k)
s,o = pb.apply_tx(blk,tx6)
print "Result of sending v->v2 200: ", serpent.decode_datalist(o)
tx7 = t.Transaction(3,gasprice,startgas,addr,0,serpent.encode_datalist([v2,900])).sign(k)
s,o = pb.apply_tx(blk,tx7)
print "Result of sending v->v2 900: ", serpent.decode_datalist(o)
tx8 = t.Transaction(4,gasprice,startgas,addr,0,serpent.encode_datalist([v])).sign(k)
s,o = pb.apply_tx(blk,tx8)
print "Result of querying v: ", serpent.decode_datalist(o)
tx9 = t.Transaction(5,gasprice,startgas,addr,0,serpent.encode_datalist([v2])).sign(k)
s,o = pb.apply_tx(blk,tx9)
print "Result of querying v2: ", serpent.decode_datalist(o)

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
print "AST", serpent.rewrite(serpent.parse(scode3))
print "Assembly", serpent.compile_to_assembly(scode3)
blk = b.genesis({ v: 10**18, v2: 10**18 })
tx10 = t.contract(0,0,gasprice,startgas,code3).sign(k)
s, addr = pb.apply_tx(blk,tx10)
print "Address:", addr.encode('hex')
tx11 = t.Transaction(1,gasprice,startgas,addr,0,'').sign(k)
s,o = pb.apply_tx(blk,tx11)
print "Initialization complete", serpent.decode_datalist(o)
tx12 = t.Transaction(2,gasprice,startgas,addr,0,serpent.encode_datalist([500])).sign(k)
s,o = pb.apply_tx(blk,tx12)
print "Balance", serpent.decode_datalist(o)
tx13 = t.Transaction(3,gasprice,startgas,addr,0,serpent.encode_datalist([500,726])).sign(k)
s,o = pb.apply_tx(blk,tx13)
print "Set balance to 500:726", serpent.decode_datalist(o)
tx14 = t.Transaction(4,gasprice,startgas,addr,0,serpent.encode_datalist([500])).sign(k)
s,o = pb.apply_tx(blk,tx14)
print "Balance", serpent.decode_datalist(o)

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
''' % (addr.encode('hex'),addr.encode('hex'))
code4 = serpent.compile(scode4)
print "AST", serpent.rewrite(serpent.parse(scode4))
print "Assembly", serpent.compile_to_assembly(scode4)
# important: no new genesis block
tx15 = t.contract(5,0,gasprice,2000,code4).sign(k)
s, addr2 = pb.apply_tx(blk,tx15)
print "Address:", addr.encode('hex')
tx16 = t.Transaction(6,gasprice,2000,addr2,10**17,serpent.encode_datalist([500])).sign(k)
s,o = pb.apply_tx(blk,tx16)
print "First participant added", serpent.decode_datalist(o)
tx17 = t.Transaction(0,gasprice,2000,addr2,10**17,serpent.encode_datalist([500])).sign(k2)
s,o = pb.apply_tx(blk,tx17)
print "Second participant added, USDvalue settled", serpent.decode_datalist(o)
snapshot = blk.snapshot()
tx18 = t.Transaction(7,gasprice,2000,addr2,0,'').sign(k)
s,o = pb.apply_tx(blk,tx18)
print "Attempting to cash out immediately", o if o == -1 else serpent.decode_datalist(o)
tx19 = t.Transaction(8,gasprice,2000,addr,0,serpent.encode_datalist([500,300])).sign(k)
s,o = pb.apply_tx(blk,tx19)
print "Changing value to 300", serpent.decode_datalist(o)
print blk.to_dict()
tx20 = t.Transaction(9,gasprice,2000,addr2,0,'').sign(k)
print "Old balances", blk.get_balance(v), blk.get_balance(v2)
s,o = pb.apply_tx(blk,tx20)
print "Attempting to cash out with value drop", o if o == -1 else serpent.decode_datalist(o)
print "New balances", blk.get_balance(v), blk.get_balance(v2)
blk.revert(snapshot)
blk.timestamp += 200000
tx21 = t.Transaction(7,gasprice,2000,addr2,0,'').sign(k)
print "Old balances", blk.get_balance(v), blk.get_balance(v2)
s,o = pb.apply_tx(blk,tx21)
print "Attempting to cash out after expiry", o if o == -1 else serpent.decode_datalist(o)
print "New balances", blk.get_balance(v), blk.get_balance(v2)
