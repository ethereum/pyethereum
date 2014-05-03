import sys
import os
import pytest
import tempfile
import pyethereum.processblock as processblock
import pyethereum.blocks as blocks
import pyethereum.transactions as transactions
import pyethereum.utils as utils
import pyethereum.chainmanager as chainmanager

tempdir = tempfile.mktemp()

@pytest.fixture(scope="module")
def f():pass

def set_db(name):
	utils.data_dir.set(os.path.join(tempdir, name))
set_db('default')

def test_serialization():
	u = utils
	blocks.INITIAL_DIFFICULTY = 2 ** 16
	set_db('a')
	k = u.sha3('cow')
	v = u.privtoaddr(k)
	k2 = u.sha3('horse')
	v2 = u.privtoaddr(k2)
	blk = blocks.genesis({v: u.denoms.ether * 1})
	# test deserialization into other db
	set_db('b')
	blk2 = blocks.genesis({v: u.denoms.ether * 1})
	assert blk.hex_hash() == \
	    blocks.Block.deserialize(blk.serialize()).hex_hash()
	set_db('a')
	gasprice = 0
	startgas = 10000
	# nonce,gasprice,startgas,to,value,data,v,r,s
	tx = transactions.Transaction(0, gasprice, startgas, v2, u.denoms.finney * 10, '').sign(k)
	assert blk in set([blk])
	assert tx in set([tx])
	assert tx.hex_hash() == \
	    transactions.Transaction.deserialize(tx.serialize()).hex_hash()
	assert tx.hex_hash() == \
	    transactions.Transaction.hex_deserialize(tx.hex_serialize()).hex_hash()
	assert tx in set([tx])

	assert not tx in blk.get_transactions()
	
	# test deserialization into other db
	set_db('b')
	assert blk.hex_hash() == \
	    blocks.Block.hex_deserialize(blk.hex_serialize()).hex_hash()
	set_db('a')

	# advance one block
	m = chainmanager.Miner(blk, blk.coinbase)
	blk = m.mine(steps=1000**2)
	
	# apply transaction
	success, res = processblock.apply_tx(blk, tx)
	assert tx in blk.get_transactions()
	
	# test deserialization into other db
	assert blk.hex_hash() == \
	    blocks.Block.hex_deserialize(blk.hex_serialize()).hex_hash()

	assert blk.get_balance(v) == u.denoms.finney * 990
	assert blk.get_balance(v2) == u.denoms.finney * 10
