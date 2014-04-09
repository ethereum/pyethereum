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
blk = b.Block.genesis({ v: 10**18 })
# Give tx2 some money
tx = t.Transaction(0,10**16,10**14,1000,v2,'').sign(k)
pb.apply_tx(blk,tx)
print "New balance of v1: ", blk.get_balance(v)
print "New balance of v2: ", blk.get_balance(v2)
print blk.to_dict()

print "Starting namecoin tests"
blk = b.Block.genesis({ v: 10**18 })
scode1 = '''
if !contract.storage[msg.data[0]]:
    contract.storage[msg.data[0]] = msg.data[1]
    return(1)
'''
code1 = serpent.compile(scode1)
print "AST", serpent.rewrite(serpent.parse(scode1))
print "Assembly", serpent.compile_to_assembly(scode1)
print "Code", serpent.deserialize(code1)
tx1 = t.Transaction.contract(0,0,10**14,1000,code1).sign(k)
addr = pb.apply_tx(blk,tx1)
snapshot = blk.snapshot()
print "Contract address", addr.encode('hex')
tx2 = t.Transaction(1,0,10**14,1000,addr,serpent.encode_datalist(['george',45]))
tx2.sign(k)
o = pb.apply_tx(blk,tx2)
print "Result of registering george:45: ", o
print blk.to_dict()
tx3 = t.Transaction(2,0,10**14,1000,addr,serpent.encode_datalist(['george',20])).sign(k)
o = pb.apply_tx(blk,tx3)
print "Result of registering george:20: ", o
print blk.to_dict()
tx4 = t.Transaction(3,0,10**14,1000,addr,serpent.encode_datalist(['harry',60])).sign(k)
o = pb.apply_tx(blk,tx4)
print "Result of registering harry:60: ", o
print blk.to_dict()

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
''' % v
code2 = serpent.compile(scode2)
print "AST", serpent.rewrite(serpent.parse(scode2))
print "Assembly", serpent.compile_to_assembly(scode2)
print "Code", serpent.deserialize(code2)
print "Starting currency contract tests"
blk = b.Block.genesis({ v: 10**18 })
tx4 = t.Transaction.contract(0,0,10**14,1000,code2).sign(k)
addr = pb.apply_tx(blk,tx4)
print "Contract address", addr.encode('hex')
tx5 = t.Transaction(1,0,10**14,1000,addr,'').sign(k)
o = pb.apply_tx(blk,tx5)
print "Initialization finished"
print blk.to_dict()
tx6 = t.Transaction(2,0,10**14,1000,addr,serpent.encode_datalist([v2,200])).sign(k)
o = pb.apply_tx(blk,tx6)
print "Result of sending v->v2 200: ", o
print blk.to_dict()
tx7 = t.Transaction(3,0,10**14,1000,addr,serpent.encode_datalist([v2,900])).sign(k)
o = pb.apply_tx(blk,tx7)
print "Result of sending v->v2 900: ", o
print blk.to_dict()
tx8 = t.Transaction(4,0,10**14,1000,addr,serpent.encode_datalist([v])).sign(k)
o = pb.apply_tx(blk,tx8)
print "Result of querying v: ", o
print blk.to_dict()
tx9 = t.Transaction(5,0,10**14,1000,addr,serpent.encode_datalist([v2])).sign(k)
o = pb.apply_tx(blk,tx9)
print "Result of querying v2: ", o
print blk.to_dict()

scode3 = '''
if !contract.storage[1000]:
    contract.storage[1000] = 1
    contract.storage[1001] = msg.sender
elif msg.sender == contract.storage[1001]:
    contract.storage[msg.data[0]] = msg.data[1]
else:
    return(contract.storage[msg.data[0]])
'''
code3 = serpent.compile(scode3)
print "AST", serpent.rewrite(serpent.parse(scode3))
print "Assembly", serpent.compile_to_assembly(scode2)
print "Code", serpent.deserialize(code2)
blk = b.Block.genesis({ v: 10**18 })
tx10 = t.Transaction.contract(0,0,10**14,1000,code3).sign(k)
addr = pb.apply_tx(blk,tx10)
print "Address:", addr.encode('hex')
tx11 = t.Transaction(1,0,10**14,1000,addr,'').sign(k)
o = pb.apply_tx(blk,tx11)
print "Initialization complete"
print blk.to_dict()
tx12 = t.Transaction(2,0,10**14,1000,addr,serpent.encode_datalist([500])).sign(k)
o = pb.apply_tx(blk,tx12)
print o
print blk.to_dict()
tx13 = t.Transaction(3,0,10**14,1000,addr,serpent.encode_datalist([500,726])).sign(k)
o = pb.apply_tx(blk,tx13)
print "Set balance to 500:726", o
print blk.to_dict()
tx14 = t.Transaction(4,0,10**14,1000,addr,serpent.encode_datalist([500])).sign(k)
o = pb.apply_tx(blk,tx14)
print "Balance", o
print blk.to_dict()

scode4 = '''
if !contract.storage[1000]:
    contract.storage[1000] = msg.sender
    contract.storage[1002] = msg.value
    contract.storage[1003] = msg.data[0]
elif !contract.storage[1001]:
    ethvalue = contract.storage[1002]
    if msg.value >= ethvalue:
        contract.storage[1001] = msg.sender
    contract.storage[1004] = ethvalue * msg(%s,0,1000,[contract.storage[1003]],1)
    contract.storage[1005] = block.timestamp + 86400
else:
    othervalue = contract.storage[1004]
    ethvalue = othervalue / msg(%s,0,1000,[contract.storage[1003]],1)
    if ethvalue >= contract.balance: 
        suicide(contract.storage[1000])
    else:
        send(contract.storage[1000],ethvalue,1000)
        suicide(contract.storage[1001])
'''
code4 = serpent.compile(scode4)
#print "AST", serpent.rewrite(serpent.parse(scode3))
#print "Assembly", serpent.compile_to_assembly(scode2)
#print "Code", serpent.deserialize(code2)
