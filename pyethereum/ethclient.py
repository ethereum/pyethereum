#!/usr/bin/env python
import sys
import requests
import json
from docopt import docopt
import utils
import transactions
from apiserver import base_url as api_path

DEFAULT_HOST = 'localhost'
DEFAULT_PORT = 30203
DEFAULT_GASPRICE = 10**12
DEFAULT_STARTGAS = 10000

def sha3(x):
    return utils.sha3(x).encode('hex')


def privtoaddr(x):
    if len(x) == 64:
        x = x.decode('hex')
    return utils.privtoaddr(x)


def mktx(nonce, gasprice, startgas, to, value, data):
    return transactions.Transaction(
        int(nonce), gasprice, startgas, to, int(value), data.decode('hex')
    ).hex_serialize(False)


def contract(nonce, gasprice, startgas, value, code):
    return transactions.contract(
        int(nonce), gasprice, startgas, int(value), code.decode('hex')
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
        if r.status_code in [200, 201]:
          return r.json()
        else:
            return dict((k, getattr(r, k)) for k in ('status_code', 'reason'))

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

    def quicktx(self, gasprice, startgas, to, value, data, pkey_hex):
        nonce = self.getnonce(privtoaddr(pkey_hex))
        tx = mktx(nonce, gasprice, startgas, to, value, data)
        return self.applytx(sign(tx, pkey_hex))

    def getblock(self, id):
        return self.json_get_request(path='/blocks/%s' % id)

    def gettx(self, id):
        return self.json_get_request(path='/transactions/%s' % id)

    def getpending(self):
        return self.json_get_request(path='/pending/')

    def trace(self, id):
        res = self.json_get_request(path='/trace/%s' % id)
        if 'trace' in res:
          return res['trace']
        return res

doc = \
"""ethclient

Usage:
  pyethclient getbalance [options] <address>
  pyethclient getcode [options] <address>
  pyethclient getstate [options] <address>
  pyethclient getnonce [options] <address>
  pyethclient quicktx [options] <to> <value> <data_hex> <pkey_hex>
  pyethclient mktx <nonce> <to> <value> <data_hex>
  pyethclient quicktx <to> <value> <data_hex> <pkey_hex>
  pyethclient mkcontract <nonce> <value> <code_hex>
  pyethclient applytx [options] <tx_hex>
  pyethclient sign <tx_hex> <pkey_hex>
  pyethclient privtoaddr <pkey_hex>
  pyethclient sha3 <data>
  pyethclient getblock [options] <blockid_hex_or_num>
  pyethclient gettx [options] <txid_hex>
  pyethclient getpending [options]
  pyethclient trace [options] <txid_hex>

Options:
  -h --help                 Show this screen
  -v --version              Show version
  -H --host=<host>          API server host [default: %s]
  -p --port=<port>          API server port [default: %d]
  -g --gasprice=<gasprice>  maximum gas price [default: %d]
  -s --startgas=<startgas>  gas provided [default: %d]
  -n --nonce                by default the next nonce is looked up
""" % (DEFAULT_HOST, DEFAULT_PORT, DEFAULT_GASPRICE, DEFAULT_STARTGAS)



def main():
    arguments = docopt(doc, version='pyethclient 0.1')
    #print(arguments)

    host = arguments.get('--host') or DEFAULT_HOST
    port = int(arguments.get('--port') or DEFAULT_PORT)
    api = APIClient(host, port)

    gasprice = int(arguments.get('--gasprice') or DEFAULT_GASPRICE)
    startgas = int(arguments.get('--startgas') or DEFAULT_STARTGAS)


    cmd_map = dict( getbalance=(api.getbalance, arguments['<address>']),
                    getcode=(api.getcode,  arguments['<address>']),
                    getstate=(api.getstate,  arguments['<address>']),
                    getnonce=(api.getnonce,  arguments['<address>']),
                    applytx=(api.applytx, arguments['<tx_hex>']),
                    sha3=(sha3, arguments['<data>']),
                    privtoaddr=(privtoaddr, arguments['<pkey_hex>']),
                    mkcontract=(contract, arguments['<nonce>'], gasprice, startgas, arguments['<value>'], arguments['<code_hex>']),
                    mktx=(mktx, arguments['<nonce>'], gasprice, startgas, arguments['<to>'], arguments['<value>'], arguments['<data_hex>']),
                    quicktx=(api.quicktx, gasprice, startgas, arguments['<to>'], arguments['<value>'], arguments['<data_hex>'], arguments['<pkey_hex>']),
                    sign=(sign, arguments['<tx_hex>'], arguments['<pkey_hex>']),
                    getblock=(api.getblock, arguments['<blockid_hex_or_num>']),
                    gettx=(api.gettx, arguments['<txid_hex>']),
                    trace=(api.trace, arguments['<txid_hex>']),
                    getpending=(api.getpending,)
                    )
    for k in cmd_map:
        if arguments.get(k):
            cmd_args = cmd_map.get(k)
            out = cmd_args[0](*cmd_args[1:])
            print out
            break

if __name__ == '__main__':
    main()

