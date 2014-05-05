#!/usr/bin/env python
import sys
import requests
import json
from common import make_pyethereum_avail
make_pyethereum_avail()
import utils
import transactions
from apiserver import base_url
base_url = "http://127.0.0.1:30203" + base_url


k = utils.sha3('heiko')
v = utils.privtoaddr(k)
k2 = utils.sha3('horse')
v2 = utils.privtoaddr(k2)

# Give tx2 some money
# nonce,gasprice,startgas,to,value,data,v,r,s
value = 10 ** 16
print value, 'from', v, 'to', v2

nonce = int(sys.argv[1])

tx = transactions.Transaction(
    nonce, gasprice=10 ** 12, startgas=10000, to=v2, value=10 ** 16, data='').sign(k)

data = tx.hex_serialize()

url = base_url + '/transactions/'
print 'PUT', url, data
r = requests.put(url, data)
print r.status_code, r.reason, r.url
