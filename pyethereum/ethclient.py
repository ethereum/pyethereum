import codecs
from functools import wraps
import json

from bitcoin import decode_privkey, encode_privkey
import click
import requests
from requests.exceptions import ConnectionError

import rlp
from transactions import Transaction, contract
import utils
from . import __version__
from . config import read_config


DEFAULT_GASPRICE = 10**12
DEFAULT_STARTGAS = 10000


class APIClient(object):

    def __init__(self, host, port, path):
        self.host = host
        self.port = port
        assert path.startswith('/') and not path.endswith('/')
        self.base_url = "http://%s:%d%s" % (host, port, path)

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
        account = self.account_to_dict(address)
        return int(account['balance'])

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
        url = self.base_url + '/transactions/'
        #print 'PUT', url, txdata
        r = requests.put(url, codecs.encode(txdata, 'hex'))
        return dict(status_code=r.status_code, reason=r.reason, url=r.url)

    def quicktx(self, gasprice, startgas, to, value, data, pkey_hex):
        nonce = self.getnonce(utils.privtoaddr(pkey_hex))
        tx = Transaction(nonce, gasprice, startgas, to, value, str(data))
        tx.sign(pkey_hex)
        return self.applytx(tx.serialize(True))

    def quickcontract(self, gasprice, startgas, value, code, pkey_hex):
        sender = utils.privtoaddr(pkey_hex)
        nonce = self.getnonce(sender)
        tx = contract(nonce, gasprice, startgas, value, str(code))
        tx.sign(pkey_hex)
        formatted_rlp = [sender.decode('hex'), utils.int_to_big_endian(nonce)]
        addr = utils.sha3(rlp.encode(formatted_rlp))[12:].encode('hex')
        o = self.applytx(tx.serialize(True))
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
            name, data = l.items()[0]
            order = dict(pc=-2, op=-1, stackargs=1, data=2, code=3)
            items = sorted(data.items(), key=lambda x: order.get(x[0], 0))
            msg = ", ".join("%s=%s" % (k, v) for k, v in items)
            out.append("%s: %s" % (name.ljust(15), msg))
          return '\n'.join(out)
        return res

    def dump(self, id):
        res = self.json_get_request(path='/dump/%s' % id)
        return json.dumps(res, sort_keys=True, indent=2)


def handle_connection_error(f):
    """Decorator that handles `ConnectionError`s by printing the request error
    message.
    """
    @wraps(f)
    def new_f(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ConnectionError as e:
            msg = ('Could not establish connection to server '
                   '{0}'.format(e.message))
            raise click.ClickException(msg)
    return new_f


def pass_client(f):
    """Decorator that passes an `APIClient` instance to commands and handles
    possible `ConnectionError`s.
    """
    raw_pass_client = click.make_pass_decorator(APIClient)
    return raw_pass_client(handle_connection_error(f))


class PrivateKey(click.ParamType):
    """A parameter type for private keys.

    Inputs are accepted if they are valid private keys in either hex or WIF.
    """
    name = 'private key'

    def convert(self, value, param, ctx):
        """Convert the given private key to its integer representation."""
        try:
            return decode_privkey(value)
        except Exception:
            # unfortunately pybitcointools raises no more specific exception
            self.fail('{} is not a valid private key'.format(value),
                      param, ctx)


class Binary(click.ParamType):
    """A parameter type for binary data encoded as a hexadecimal string.

    Inputs are accepted if they are either bytearrays or contain only
    hexadecimal digits (0-9, a-f).
    """
    name = 'binary'

    def __init__(self, size=None):
        """
        :param size: the expected data size in bytes, or None denoting the lack
                     of a constraint (default).
        """
        super(Binary, self).__init__()
        self.size = size

    def convert(self, value, param, ctx):
        """Convert a hex-string to a bytearray."""
        if not isinstance(value, bytearray):  # value is raw input
            try:
                binary = bytearray(codecs.decode(value, 'hex'))
            except TypeError:
                msg = 'ill hex encoding '
                if len(value) % 2 == 1:
                    msg += '({} is odd length)'
                else:
                    msg += '({} contains non-hexadecimal digits)'
                self.fail(msg.format(value), param, ctx)
            else:
                if self.size and len(binary) != self.size:  # check length
                    msg = 'invalid size (expected {0}, got {1} bytes)'
                    self.fail(msg.format(self.size, len(binary)))
                else:
                    return binary
        else:  # value has been converted before
            # this branch ensures idempotency as required by Click
            return value


class Hash(Binary):
    """A parameter type for hashes, such as addresses, tx hashes, etc.

    Inputs are checked for being well encoded in hex, but not converted to
    bytearrays.

    :param name: the name to use, defaulting to `"n-byte hash"` where `n`
                 denotes the hash's size.
    :param size: the expected length of the hash in bytes (default 32)
    """

    def __init__(self, name=None, size=32):
        if name:
            self.name = name
        else:
            self.name = '{0}-byte hash'.format(size)
        if size <= 0:
            raise ValueError('Hashes must be at least 1 byte long')
        super(Hash, self).__init__(size)

    def convert(self, value, param, ctx):
        value = super(Hash, self).convert(value, param, ctx)
        return codecs.encode(value, 'hex')


ADDRESS = Hash(size=20)
TXHASH = Hash(size=32)
BLOCKHASH = Hash(size=32)
PRIVKEY = PrivateKey()
NONNEG_INT = click.IntRange(min=0)
NONNEG_INT.name = 'integer'
POS_INT = click.IntRange(min=1)
POS_INT.name = 'integer'


nonce_option = click.option('--nonce', '-n', type=NONNEG_INT, default=0,
                            show_default=True,
                            help='the number of transactions already sent by '
                                 'the sender\'s account')


gasprice_option = click.option('--gasprice', '-p', type=NONNEG_INT,
                               default=DEFAULT_GASPRICE, show_default=True,
                               help='the amount of ether paid for each unit '
                                    'of gas consumed by the transaction')


startgas_option = click.option('--startgas', '-g', type=NONNEG_INT,
                               default=DEFAULT_STARTGAS, show_default=True,
                               help='the maximum number of gas units the '
                                    'transaction is allowed to consume')


receiver_option = click.option('--to', '-t', type=ADDRESS, required=True,
                               help='the receiving address')


value_option = click.option('--value', '-v', type=NONNEG_INT, default=0,
                            show_default=True,
                            help='the amount of ether sent along with the '
                                 'transaction')


data_option = click.option('--data', '-d', type=Binary(), default='',
                           help='additional hex-encoded data packed in the '
                                'transaction [default: empty]')


code_option = click.option('--code', '-c', type=Binary(), default='',
                           help='the EVM code in hex-encoding [default: '
                                'empty]')


privkey_option = click.option('--key', '-k', type=PRIVKEY, required=True,
                              help='the private key to sign with')


def print_version(ctx, param, value):
    """Callback for the version flag.

    If the flag is set, print the version and exit. Otherwise do nothing.
    """
    if not value or ctx.resilient_parsing:
        return
    click.echo('pyethclient {0}'.format(__version__))
    ctx.exit()


@click.group()
@click.pass_context
@click.option('--version', is_flag=True, is_eager=True, expose_value=False,
              callback=print_version)
@click.option('--host', '-H', help='API server host')
@click.option('--port', '-p', type=POS_INT, help='API server host port')
def ethclient(ctx, host, port):
    """pyethclient is collection of commands allowing the interaction with a
    running pyethereum instance.
    """
    config = read_config()
    if not host:
        host = config.get('api', 'listen_host')
    if not port:
        port = int(config.get('api', 'listen_port'))
    path = config.get('api', 'api_path')
    ctx.obj = APIClient(host, port, path)


@ethclient.command()
@click.argument('string')
def sha3(string):
    """Calculate the SHA3-256 hash of some input.

    This command calculates the 256-bit SHA3 hash of STRING and prints the
    result in hex-encoding. STRING is interpreted as a latin-1 encoded byte
    array.
    """
    try:
        byte_array = string.encode('latin1')
    except UnicodeEncodeError:
        raise click.BadParameter('STRING must be encoded in latin-1')
    else:
        click.echo(utils.sha3(byte_array).encode('hex'))


@ethclient.command()
@click.argument('key', type=PRIVKEY)
def privtoaddr(key):
    """Derive an address from a private key.

    KEY must either be a raw private key in hex encoding or a WIF string.

    The resulting address will be printed in hex encoding.
    """
    click.echo(utils.privtoaddr(encode_privkey(key, 'hex')))


@ethclient.command()
@nonce_option
@gasprice_option
@startgas_option
@receiver_option
@value_option
@data_option
def mktx(nonce, gasprice, startgas, to, value, data):
    """Assemble an unsigned transaction.

    The result is the hex representation of the transaction in RLP encoding.
    """
    tx = Transaction(nonce, gasprice, startgas, to, value,
                     str(data))
    click.echo(tx.hex_serialize(False))


@ethclient.command()
@nonce_option
@gasprice_option
@startgas_option
@value_option
@code_option
def mkcontract(nonce, gasprice, startgas, value, code):
    """Assemble a contract creating transaction.

    The result is the hex representation of the transaction in RLP encoding.
    """
    ct = contract(nonce, gasprice, startgas, value, str(code))
    click.echo(ct.hex_serialize(False))


@ethclient.command()
@click.argument('transaction', type=Binary())
@click.argument('key', type=PRIVKEY)
def signtx(transaction, key):
    """Sign a previously created transaction.

    TRANSACTION must be the hex encoded transaction, as for instance created
    using mktx or mkcontract. If it has already been signed before, its
    signature will be replaced.

    KEY must be the private key to sign with, in hexadecimal encoding or WIF.

    The signed transaction will be printed in hex encoding.
    """
    try:
        tx = Transaction.deserialize(str(transaction))
    except AssertionError:
        raise click.BadParameter('Unable to deserialize TRANSACTION.')
    tx.sign(encode_privkey(key, 'hex'))
    click.echo(tx.hex_serialize(True))


@ethclient.command()
@click.argument('transaction', type=Binary())
@pass_client
def applytx(client, transaction):
    """Absorb a transaction into the next block.

    This command sends a transaction to the server, which will presumably
    validate it, include it in its memory pool, and further announce it to the
    network. The server's response will be returned.

    TRANSACTION must a signed transaction in hex-encoding.
    """
    click.echo(client.applytx(str(transaction)))


@ethclient.command()
@gasprice_option
@startgas_option
@receiver_option
@value_option
@data_option
@privkey_option
@pass_client
def quicktx(client, gasprice, startgas, to, value, data, key):
    """Create and finalize a transaction.

    This command is a shortcut that chains getnonce, mktx, signtx, and applytx.
    It returns the server's response.
    """
    click.echo(client.quicktx(gasprice, startgas, to, value, data,
                              encode_privkey(key, 'hex')))


@ethclient.command()
@gasprice_option
@startgas_option
@value_option
@code_option
@privkey_option
@pass_client
def quickcontract(client, gasprice, startgas, value, code, key):
    """Create and finalize a contract.

    This command is a shortcut that chains getnonce, mkcontract, signtx, and
    applytx. In addition to the server's response, it returns the address of
    the newly created contract.
    """
    click.echo(client.quickcontract(gasprice, startgas, value, code,
                                    encode_privkey(key, 'hex')))


@ethclient.command()
@click.argument('address', type=ADDRESS)
@pass_client
def getbalance(client, address):
    """Retrieve the balance of an account."""
    click.echo(client.getbalance(address))


@ethclient.command()
@click.argument('address', type=ADDRESS)
@pass_client
def getcode(client, address):
    """Print the EVM code of an account."""
    click.echo(client.getcode(address))


@ethclient.command()
@click.argument('address', type=ADDRESS)
@pass_client
def getnonce(client, address):
    """Return an account's nonce."""
    click.echo(client.getnonce(address))


@ethclient.command()
@click.argument('address', type=ADDRESS)
@pass_client
def getstate(client, address):
    """Print an account's storage contents.

    The output will be hex encoded. Non-contract accounts have empty storages.
    """
    click.echo(client.account_to_dict(address)['storage'])


@ethclient.command()
@click.option('--txhash', '-t', type=TXHASH, default=None,
              help='the hash of one transaction in the block')
@click.option('--blockhash', '-b', type=BLOCKHASH, default=None,
              help='the hash of the block')
@click.option('--blocknumber', '-n', type=NONNEG_INT, default=None,
              help='the block\'s number in the chain')
@pass_client
def getblock(client, txhash, blockhash, blocknumber):
    """Fetch a block from the block chain.

    The block must either be specified by its block hash, its number in the
    chain, or by a transaction included in the block.
    """
    if sum(map(lambda p: p is None, (txhash, blockhash, blocknumber))) != 2:
        raise click.BadParameter('Exactly one of the options --txhash, '
                                 '--blockhash and --blocknumber must be '
                                 'given.')
    else:
        click.echo(client.getblock(txhash or blockhash or blocknumber))


@ethclient.command()
@click.argument('txhash', type=TXHASH)
@pass_client
def gettx(client, txhash):
    """Show a transaction from the block chain.

    TXHASH must be the hex encoded hash of the transaction.
    """
    click.echo(client.gettx(txhash))


@ethclient.command()
@pass_client
def getpending(client):
    """List all pending transactions."""
    click.echo(client.getpending()['transactions'])


@ethclient.command()
@click.argument('txhash', type=TXHASH)
@click.option('--print/--json', 'print_', is_flag=True, default=True,
              help='Display the trace human readably [default] or in JSON.')
@pass_client
def trace(client, txhash, print_):
    """Read the trace left by a transaction.

    The transaction must be specified by its hash TXHASH.
    """
    if print_:
        click.echo(client.trace(txhash))
    else:
        click.echo(client.tracejson(txhash))


@ethclient.command()
@click.option('--blockhash', '-b', type=BLOCKHASH, default=None,
              help='the hash of the block')
@click.option('--txhash', '-t', type=TXHASH, default=None,
              help='the hash of one transaction in the block')
@pass_client
def dump(client, blockhash, txhash):
    """Dump the state of a block.

    The block must be specified either by its hash or by a transaction included
    into the block.

    In addition to the result of getblock, this command also yields the state
    of every account.
    """
    if sum(map(lambda p: p is not None, (blockhash, txhash))) != 1:
        raise click.BadParameter('Either --blockhash or --txhash must be '
                                 'specified')
    else:
        click.echo(client.dump(blockhash or txhash))
