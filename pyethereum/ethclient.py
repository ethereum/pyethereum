#!/usr/bin/env python
import sys
import requests
import json
from docopt import docopt
import utils
import transactions
from apiserver import base_url as api_path
from pyethtool import sha3, privtoaddr, mktx, contract

DEFAULT_HOST = 'localhost'
DEFAULT_PORT = 30203

def sha3(x):
    return utils.sha3(x).encode('hex')


def privtoaddr(x):
    if len(x) == 64:
        x = x.decode('hex')
    return utils.privtoaddr(x)

def mktx(nonce, to, value, data):
    return transactions.Transaction(
        int(nonce), gasprice=10 ** 12, startgas=10000, to=to, value=int(value), data=data.decode('hex')
    ).hex_serialize(False)


def mkcontract(*args):
    return contract(*args)


def contract(nonce, value, code):
    return transactions.contract(
        int(nonce), 10 ** 12, 10000, int(value), code.decode('hex')
    ).hex_serialize(False)


def sign(txdata, key):
    return transactions.Transaction.hex_deserialize(txdata).sign(key).hex_serialize(True)


class APIClient(object):

    def __init__(self, host, port):
        self.host = host
        self.port = port
        assert api_path.startswith('/') and not api_path.endswith('/')
        self.base_url = "http://%s:%d%s" %(host, port, api_path)


    def json_get_request(self, path):
        assert path.startswith('/')
        url = self.base_url + path
        #print 'GET', url
        r = requests.get(url)
        #print r.status_code, r.reason, r.url, r.headers
        return r.json()

    def account_to_dict(self, address):
        return self.json_get_request(path='/accounts/%s' % address)

    def getbalance(self, address):
        return int(self.account_to_dict(address)['balance'])

    def getcode(self, address):
        return self.account_to_dict(address)['code']

    def getnonce(self, address):
        return int(self.account_to_dict(address)['nonce'])

    def getstate(self, address):
        return self.account_to_dict(address)['storage']

    def applytx(self, txdata):
        tx = transactions.Transaction.hex_deserialize(txdata)
        url = self.base_url + '/transactions/'
        #print 'PUT', url, txdata
        r = requests.put(url, txdata)
        return dict(status_code=r.status_code, reason=r.reason, url=r.url)


doc = \
"""ethclient

Usage:
  pyethclient getbalance [options] <address>
  pyethclient getcode [options] <address>
  pyethclient getstate [options] <address>
  pyethclient getnonce [options] <address>
  pyethclient applytx [options] <tx_hex>
  pyethclient mktx <nonce> <to> <value> <data_hex>
  pyethclient sign <tx_hex> <pkey_hex>
  pyethclient mkcontract <code_hex>
  pyethclient privtoaddr <pkey_hex>
  pyethclient sha3 <data>

Options:
  -h --help     Show this screen.
  --version     Show version.
  --host=<host> API server host [default: %s]
  --port=<port> API server port [default: %d]
""" % (DEFAULT_HOST, DEFAULT_PORT)



def main():
    arguments = docopt(doc, version='pyethclient 0.1')
    #print(arguments)

    host = arguments.get('--host') or DEFAULT_HOST
    port = int(arguments.get('--port') or DEFAULT_PORT)

    api = APIClient(host, port)
    cmd_map = dict( getbalance=(api.getbalance, arguments['<address>']),
                    getcode=(api.getcode,  arguments['<address>']),
                    getstate=(api.getstate,  arguments['<address>']),
                    getnonce=(api.getnonce,  arguments['<address>']),
                    applytx=(api.applytx, arguments['<tx_hex>']),
                    sha3=(sha3, arguments['<data>']),
                    privtoaddr=(privtoaddr, arguments['<pkey_hex>']),
                    mktx=(mktx, arguments['<nonce>'], arguments['<to>'], arguments['<value>'], arguments['<data_hex>']),
                    sign=(sign, arguments['<tx_hex>'], arguments['<pkey_hex>']),
                    )
    for k in cmd_map:
        if arguments.get(k):
            cmd_args = cmd_map.get(k)
            out = cmd_args[0](*cmd_args[1:])
            print out
            break

if __name__ == '__main__':
    main()

