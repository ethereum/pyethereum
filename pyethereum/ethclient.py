
#!/usr/bin/env python
import sys
import requests
import json
from docopt import docopt
from pyethereum import utils
from pyethereum import transactions
import rlp
from pyethereum import __version__
from pyethereum.config import read_config
from rlp.utils import decode_hex, encode_hex

config = read_config()

api_path = config.get('api', 'api_path')
assert api_path.startswith('/') and not api_path.endswith('/')

DEFAULT_HOST = config.get('api', 'listen_host')
DEFAULT_PORT = config.getint('api', 'listen_port')
DEFAULT_GASPRICE = 10 ** 12
DEFAULT_STARTGAS = 10000


def sha3(x):
    return encode_hex(utils.sha3(x))


def privtoaddr(x):
    if len(x) == 64:
        x = decode_hex(x)
    return utils.privtoaddr(x)


def mktx(nonce, gasprice, startgas, to, value, data):
    return transactions.Transaction(
        int(nonce), gasprice, startgas, to, int(value), decode_hex(data)
    ).hex_serialize(False)


def contract(nonce, gasprice, startgas, value, code):
    return transactions.contract(
        int(nonce), gasprice, startgas, int(value), decode_hex(code)
    ).hex_serialize(False)


def sign(txdata, key):
    return transactions.Transaction.hex_deserialize(txdata).sign(key).hex_serialize(True)


class APIClient(object):

    def __init__(self, host, port):
        self.host = host
        self.port = port
        assert api_path.startswith('/') and not api_path.endswith('/')
        self.base_url = "http://%s:%d%s" % (host, port, api_path)

    def json_get_request(self, path):
        assert path.startswith('/')
        url = self.base_url + path
        # print 'GET', url
        r = requests.get(url)
        # print r.status_code, r.reason, r.url, r.headers
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
        ptxs = self.getpending()['transactions']
        nonce = max([0] + [int(tx['nonce']) for tx in ptxs if tx['sender'] == address])
        if nonce:
            return nonce + 1
        return int(self.account_to_dict(address)['nonce'])

    def getstate(self, address):
        return self.account_to_dict(address)['storage']

    def applytx(self, txdata):
        tx = transactions.Transaction.hex_deserialize(txdata)
        url = self.base_url + '/transactions/'
        # print 'PUT', url, txdata
        r = requests.put(url, txdata)
        return dict(status_code=r.status_code, reason=r.reason, url=r.url)

    def quicktx(self, gasprice, startgas, to, value, data, pkey_hex):
        nonce = self.getnonce(privtoaddr(pkey_hex))
        tx = mktx(nonce, gasprice, startgas, to, value, data)
        return self.applytx(sign(tx, pkey_hex))

    def quickcontract(self, gasprice, startgas, value, code, pkey_hex):
        sender = privtoaddr(pkey_hex)
        nonce = self.getnonce(sender)
        tx = contract(nonce, gasprice, startgas, value, code)
        formatted_rlp = [decode_hex(sender), utils.int_to_big_endian(nonce)]
        addr = encode_hex(utils.sha3(rlp.encode(formatted_rlp))[12:])
        o = self.applytx(sign(tx, pkey_hex))
        o['addr'] = addr
        return o

    def getblock(self, id):
        return self.json_get_request(path='/blocks/%s' % id)

    def getchildren(self, id):
        return self.json_get_request(path='/blocks/%s/children' % id)

    def gettx(self, id):
        return self.json_get_request(path='/transactions/%s' % id)

    def getpending(self):
        return self.json_get_request(path='/pending/')

    def tracejson(self, id):
        res = self.json_get_request(path='/trace/%s' % id)
        return json.dumps(res, indent=2)

    def trace(self, id):
        res = self.json_get_request(path='/trace/%s' % id)
        if 'trace' in res:
            out = []
            for l in res['trace']:
                name, data = list(l.items())[0]
                order = dict(pc=-2, op=-1, stackargs=1, data=2, code=3)
                items = sorted(list(data.items()), key=lambda x: order.get(x[0], 0))
                msg = ", ".join("%s=%s" % (k, v) for k, v in items)
                out.append("%s: %s" % (name.ljust(15), msg))
            return '\n'.join(out)
        return res

    def dump(self, id):
        res = self.json_get_request(path='/dump/%s' % id)
        return json.dumps(res, sort_keys=True, indent=2)


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
  pyethclient quickcontract <value> <code_hex> <pkey_hex>
  pyethclient applytx [options] <tx_hex>
  pyethclient sign <tx_hex> <pkey_hex>
  pyethclient privtoaddr <pkey_hex>
  pyethclient sha3 <data>
  pyethclient getblock [options] <blockid_hex_or_num>
  pyethclient gettx [options] <txid_hex>
  pyethclient getpending [options]
  pyethclient trace [options] <txid_hex>
  pyethclient tracejson [options] <txid_hex>
  pyethclient dump [options] <tx_blk_id_hex>

Options:
  -h --help                 Show this screen
  -v --version              Show version
  -H --host=<host>          API server host [default: %s]
  -p --port=<port>          API server port [default: %d]
  -g --gasprice=<gasprice>  maximum gas price [default: %d]
  -G --startgas=<startgas>  gas provided [default: %d]
  -s --stdin                take arguments from stdin
  -n --nonce                by default the next nonce is looked up
""" % (DEFAULT_HOST, DEFAULT_PORT, DEFAULT_GASPRICE, DEFAULT_STARTGAS)


def main():
    # Take arguments from stdin with -s
    if len(sys.argv) > 1 and sys.argv[1] == '-s':
        sys.argv = [sys.argv[0], sys.argv[2]] + \
            sys.stdin.read().strip().split(' ') + sys.argv[3:]
    # Get command line arguments
    arguments = docopt(doc, version='pyethclient %s' % __version__)
    # print(arguments)

    host = arguments.get('--host') or DEFAULT_HOST
    port = int(arguments.get('--port') or DEFAULT_PORT)
    api = APIClient(host, port)

    gasprice = int(arguments.get('--gasprice') or DEFAULT_GASPRICE)
    startgas = int(arguments.get('--startgas') or DEFAULT_STARTGAS)

    cmd_map = dict(getbalance=(api.getbalance, arguments['<address>']),
                   getcode=(api.getcode,  arguments['<address>']),
                   getstate=(api.getstate,  arguments['<address>']),
                   getnonce=(api.getnonce,  arguments['<address>']),
                   applytx=(api.applytx, arguments['<tx_hex>']),
                   sha3=(sha3, arguments['<data>']),
                   privtoaddr=(privtoaddr, arguments['<pkey_hex>']),
                   mkcontract=(contract, arguments['<nonce>'], gasprice, startgas, arguments[
                       '<value>'], arguments['<code_hex>']),
                   mktx=(mktx, arguments['<nonce>'], gasprice, startgas, arguments[
                       '<to>'], arguments['<value>'], arguments['<data_hex>']),
                   quicktx=(api.quicktx, gasprice, startgas, arguments['<to>'], arguments[
                       '<value>'], arguments['<data_hex>'], arguments['<pkey_hex>']),
                   quickcontract=(api.quickcontract, gasprice, startgas, arguments[
                       '<value>'], arguments['<code_hex>'], arguments['<pkey_hex>']),
                   sign=(sign, arguments['<tx_hex>'], arguments['<pkey_hex>']),
                   getblock=(api.getblock, arguments['<blockid_hex_or_num>']),
                   gettx=(api.gettx, arguments['<txid_hex>']),
                   trace=(api.trace, arguments['<txid_hex>']),
                   tracejson=(api.tracejson, arguments['<txid_hex>']),
                   dump=(api.dump, arguments['<tx_blk_id_hex>']),
                   getpending=(api.getpending,)
                   )
    for k in cmd_map:
        if arguments.get(k):
            cmd_args = cmd_map.get(k)
            out = cmd_args[0](*cmd_args[1:])
            print(out)
            break

if __name__ == '__main__':
    main()
