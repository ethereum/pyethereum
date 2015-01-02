import codecs
from functools import wraps
import json
from urlparse import urljoin, urlunsplit

from bitcoin import decode_privkey, encode_privkey
import click
import requests
from requests.exceptions import ConnectionError, HTTPError

from blocks import TransientBlock, block_structure
import rlp
from transactions import Transaction, contract
import utils
from . import __version__
from . config import read_config


DEFAULT_GASPRICE = 10**12
DEFAULT_STARTGAS = 10000


class APIClient(object):
    """A client sending HTTP request to an :class:`APIServer`.

    :param host: the hostname of the server
    :param port: the server port to use
    :param path: the api path prefix
    """

    def __init__(self, host, port, path=''):
        self.base_url = urlunsplit((
            'http', '{0}:{1}'.format(host, port), path, '', ''))

    def request(self, path, method='GET', data=None):
        """Send a request to the server.

        :param path: path specifying the api command
        :param method: the HTTP method to use ('GET', 'PUT', etc.)
        :param data: the data to attach to the request
        :returns: the server's JSON response deserialized to a python object
        :raises :class:`requests.HTTPError`: if the server reports an error
        :raises :class:`requests.ConnectionError`: if setting up the connection
                                                   to the server failed
        """
        url = urljoin(self.base_url, path)
        response = requests.request(method, url, data=data)
        response.raise_for_status()
        return response.json()

    def getaccount(self, address):
        """Request data associated with an account.

        The returned `dict` will have the following keys:

        - `'nonce'`
        - `'balance'`
        - `'code'`
        - `'storage'`

        :param address: the account's hex-encoded address
        """
        return self.request('/accounts/{0}'.format(address))

    def applytx(self, tx):
        """Send a transaction to the server

        The server will validate the transaction, add it to its list of pending
        transactions and further broadcast it to its peers.

        :param tx: a :class:`Transaction`
        :returns: the response from the server
        :raises :class:`requests.HTTPError`: if the validation on the server
                                             fails, e.g. due to a forged
                                             signature or an invalid nonce
                                             (status code 400).
        """
        txdata = tx.hex_serialize(True)
        return self.request('/transactions/', 'PUT', txdata)['transactions'][0]

    def getblock(self, id):
        """Request a certain block in the server's blockchain.

        :param id: the block hash, the block number, or the hash of an
                   arbitrary transaction in the block
        :raises :class:`requests.HTTPError`: if the server can not find the
                                             requested block (status code 404)
        """
        response = self.request('/blocks/{0}'.format(id))
        return response['blocks'][0]

    def getchildren(self, block_hash):
        """For a given parent block, request the block hashes of its children.

        :param block_hash: the hash of the parent block
        :raises :class:`requests.HTTPError`: if the server can not find a block
                                             with the given hash (status code
                                             404)
        """
        return self.request('/blocks/{0}/children'.format(id))['children']

    def gettx(self, tx_hash):
        """Request a specific transaction.

        :param tx_hash: the hex-encoded transaction hash
        :returns: a :class:`Transaction`
        :raises :class:`requests.HTTPError`: if the server does not know about
                                             the requested transaction (status
                                             code 404)
        """
        response = self.request('/transactions/{0}'.format(tx_hash))
        tx_dict = response['transactions'][0]
        tx = Transaction(int(tx_dict['nonce']),
                         int(tx_dict['gasprice']),
                         int(tx_dict['startgas']),
                         tx_dict['to'],
                         int(tx_dict['value']),
                         tx_dict['data'][2:],
                         int(tx_dict['v']),
                         int(tx_dict['r']),
                         int(tx_dict['s']))
        return tx

    def getpending(self):
        """Request a list of pending transactions."""
        return self.request('/pending/')['transactions']

    def trace(self, tx_hash):
        """Request the trace left by a transaction during its processing.

        :param tx_hash: the hex-encoded transaction hash
        :raises :class:`requests.HTTPError`: if the server can not find the
                                             transaction (status code 404)
        :returns: a `list` of `dict`s, expressing the single footprints
        """
        res = self.request('/trace/{0}'.format(tx_hash))
        return res['trace']

    def dump(self, id):
        """Request a block including the corresponding world state.

        :param id: either the block hash or the hash of one transaction in the
                   block
        """
        res = self.request('/dump/{0}'.format(id))
        return res


def handle_connection_errors(f):
    """Decorator that handles `ConnectionError`s and `HTTPError`s by printing
    an appropriate error message and exiting.
    """
    @wraps(f)
    def new_f(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ConnectionError as e:
            msg = ('Could not establish connection to server '
                   '{0}'.format(e.message))
            raise click.ClickException(msg)
        except HTTPError as e:
            res = e.response
            msg = 'HTTP request failed ({0} {1})'.format(res.status_code,
                                                         res.reason)
            raise click.ClickException(msg)
    return new_f


def pass_client(f):
    """Decorator that passes an `APIClient` instance to commands and handles
    possible `ConnectionError`s.
    """
    raw_pass_client = click.make_pass_decorator(APIClient)
    return raw_pass_client(handle_connection_errors(f))


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


def pecho(json_dict):
    """Pretty print a `dict`"""
    click.echo(json.dumps(json_dict, indent=4))


@ethclient.command()
@pass_client
@click.argument('transaction', type=Binary())
def applytx(client, transaction):
    """Absorb a transaction into the next block.

    This command sends a transaction to the server, which will presumably
    validate it, include it in its memory pool, and further announce it to the
    network. The server's response will be returned.

    TRANSACTION must a signed transaction in hex-encoding.
    """
    tx = Transaction.deserialize(str(transaction))
    pecho(client.applytx(tx))


@ethclient.command()
@pass_client
@gasprice_option
@startgas_option
@receiver_option
@value_option
@data_option
@privkey_option
def quicktx(client, gasprice, startgas, to, value, data, key):
    """Create and finalize a transaction.

    This command is a shortcut that chains getnonce, mktx, signtx, and applytx.
    It returns the server's response.
    """
    encoded_key = encode_privkey(key, 'hex')
    nonce = int(client.getaccount(utils.privtoaddr(encoded_key))['nonce'])
    tx = Transaction(nonce, gasprice, startgas, to, value, str(data))
    tx.sign(encode_privkey(key, 'hex'))
    pecho(client.applytx(tx))


@ethclient.command()
@pass_client
@gasprice_option
@startgas_option
@value_option
@code_option
@privkey_option
def quickcontract(client, gasprice, startgas, value, code, key):
    """Create and finalize a contract.

    This command is a shortcut that chains getnonce, mkcontract, signtx, and
    applytx. In addition to the server's response, it returns the address of
    the newly created contract.
    """
    encoded_key = encode_privkey(key, 'hex')
    sender = utils.privtoaddr(encoded_key)
    nonce = int(client.getaccount(sender)['nonce'])
    tx = contract(nonce, gasprice, startgas, value, str(code))
    tx.sign(encoded_key)
    response = client.applytx(tx)
    pecho({
        'address': tx.contract_address(),
        'transaction': response})


@ethclient.command()
@pass_client
@click.argument('address', type=ADDRESS)
def getbalance(client, address):
    """Retrieve the balance of an account."""
    click.echo(client.getaccount(address)['balance'])


@ethclient.command()
@pass_client
@click.argument('address', type=ADDRESS)
def getcode(client, address):
    """Print the EVM code of an account."""
    click.echo(client.getaccount(address)['code'])


@ethclient.command()
@pass_client
@click.argument('address', type=ADDRESS)
def getnonce(client, address):
    """Return an account's nonce."""
    click.echo(client.getaccount(address)['nonce'])


@ethclient.command()
@pass_client
@click.argument('address', type=ADDRESS)
def getstate(client, address):
    """Print an account's storage contents.

    The output will be hex encoded. Non-contract accounts have empty storages.
    """
    click.echo(client.getaccount(address)['storage'])


@ethclient.command()
@pass_client
@click.option('--txhash', '-t', type=TXHASH, default=None,
              help='the hash of one transaction in the block')
@click.option('--blockhash', '-b', type=BLOCKHASH, default=None,
              help='the hash of the block')
@click.option('--blocknumber', '-n', type=NONNEG_INT, default=None,
              help='the block\'s number in the chain')
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
        pecho(client.getblock(txhash or blockhash or blocknumber))


@ethclient.command()
@pass_client
@click.argument('txhash', type=TXHASH)
def gettx(client, txhash):
    """Show a transaction from the block chain.

    TXHASH must be the hex encoded hash of the transaction.
    """
    pecho(client.gettx(txhash).to_dict())


@ethclient.command()
@pass_client
def getpending(client):
    """List all pending transactions."""
    pecho(client.getpending())


@ethclient.command()
@pass_client
@click.argument('txhash', type=TXHASH)
@click.option('--print/--json', 'print_', is_flag=True, default=True,
              help='Display the trace human readably [default] or in JSON.')
def trace(client, txhash, print_):
    """Read the trace left by a transaction.

    The transaction must be specified by its hash TXHASH.
    """
    if print_:
        out = []
        for l in client.trace(txhash):
            name, data = l.items()[0]
            order = dict(pc=-2, op=-1, stackargs=1, data=2, code=3)
            items = sorted(data.items(), key=lambda x: order.get(x[0], 0))
            msg = ", ".join("%s=%s" % (k, v) for k, v in items)
            out.append("%s: %s" % (name.ljust(15), msg))
        click.echo('\n'.join(out))
    else:
        pecho(client.trace(txhash))


@ethclient.command()
@pass_client
@click.option('--blockhash', '-b', type=BLOCKHASH, default=None,
              help='the hash of the block')
@click.option('--txhash', '-t', type=TXHASH, default=None,
              help='the hash of one transaction in the block')
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
        pecho(client.dump(blockhash or txhash))
