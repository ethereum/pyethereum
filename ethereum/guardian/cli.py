import os
import time
import json
import random
import logging

import click

import serpent

from devp2p import peermanager
from devp2p.service import BaseService
from devp2p.discovery import NodeDiscovery
from devp2p.crypto import (
    privtopub as privtopub_raw,
)
from devp2p.utils import (
    host_port_pubkey_to_uri,
    update_config_with_defaults,
)

from ethereum.utils import (
    big_endian_to_int,
    encode_int,
    sha3,
)
from ethereum.db import LevelDB
from ethereum.config import (
    BLKNUMBER,
    CASPER,
    ETHER,
    NONCE,
    ECRECOVERACCT,
    BASICSENDER,
    RNGSEEDS,
    GENESIS_TIME,
)
from ethereum import ecdsa_accounts
from ethereum import abi
from ethereum.serenity_transactions import Transaction
from ethereum.serenity_blocks import (
    State,
    tx_state_transition,
    mk_contract_address,
    initialize_with_gas_limit,
    get_code,
    put_code,
)
from ethereum.mandatory_account_code import (
    mandatory_account_ct,
    mandatory_account_evm,
)
from ethereum.guardian.utils import (
    call_method,
    casper_ct,
    encode_prob,
)
from ethereum.guardian.network import (
    GuardianService,
    StandaloneGuardianApp,
)
from ethereum.guardian.strategy import (
    defaultBetStrategy,
)


logger = logging.getLogger('guardian')
logger.setLevel(logging.DEBUG)


def get_chaindata_dir(data_dir):
    return os.path.join(data_dir, 'chaindata')


def get_private_key_path(data_dir):
    return os.path.join(data_dir, 'private_key')


def get_genesis_file_path(data_dir):
    return os.path.join(data_dir, 'genesis.json')


@click.group()
@click.option(
    '--data-dir',
    help="Directory that the blockchain database will be stored",
)
@click.option(
    '--genesis',
    help="Path to the genesis json file",
)
@click.option(
    '--private-key',
    help="The private key used by this node.",
)
@click.option(
    '--config',
    help="Path to json config file",
)
@click.option(
    '--log-level',
    help="The logging level",
    default=logging.INFO,
)
@click.pass_context
def cli(ctx, data_dir, genesis, private_key, config, log_level):
    configuration = {}

    if config is not None:
        if not os.path.exists(config):
            raise click.ClickException("Config file not found at {0}".format(config))
        with open(config) as f:
            configuration.update(json.load(f))

    # logging
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(
        logging.Formatter('%(levelname)s: %(asctime)s %(message)s')
    )
    logger.addHandler(stream_handler)

    if data_dir is not None:
        if 'data_dir' in configuration:
            click.echo("Overwriting configuration 'data_dir' value `{0}` with command line option value `{1}`.".format(configuration['data_dir'], data_dir), err=True)
        configuration['data_dir'] = data_dir
    else:
        configuration['data_dir'] = os.path.expanduser(os.path.join('~', '.guardian'))

    if private_key is not None:
        if 'private_key' in configuration:
            click.echo("Overwriting configuration 'private_key' value `{0}` with command line option value `{1}`.".format(configuration['private_key'], private_key), err=True)
        configuration['private_key'] = private_key
    else:
        private_key_file_path = get_private_key_path(configuration['data_dir'])
        if os.path.exists(private_key_file_path):
            private_key = open(private_key_file_path).read()
            if len(private_key) != 32:
                raise click.ClickException("Private key must be 32 bytes long.")
            configuration['private_key'] = private_key
        else:
            click.echo("No private key file found at `{0}`".format(private_key_file_path), err=True)

    if genesis is not None:
        if 'genesis' in configuration:
            click.echo("Overwriting configuration 'genesis' value `{0}` with command line option value `{1}`.".format(configuration['genesis'], genesis), err=True)
        configuration['genesis'] = genesis
    else:
        configuration['genesis'] = get_genesis_file_path(configuration['data_dir'])

    ctx.obj.update(configuration)


@cli.command()
@click.option(
    '--seed',
    help="The seed value that will be used to generate the private key",
)
@click.pass_context
def init(ctx, seed):
    configuration = ctx.obj

    data_dir = configuration['data_dir']

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    if seed is None:
        seed = encode_int(random.randint(1e32, 1e64))

    private_key_file_path = get_private_key_path(data_dir)

    if not os.path.exists(private_key_file_path):
        private_key = sha3(seed)
        with open(private_key_file_path, 'w') as private_key_file:
            private_key_file.write(private_key)

    genesis_path = configuration['genesis']
    if not os.path.exists(genesis_path):
        raise click.ClickException("No genesis file found.  Cannot write initial chain data")

    chaindata_dir = get_chaindata_dir(data_dir)

    if not os.path.exists(chaindata_dir):
        os.makedirs(chaindata_dir)

    with open(genesis_path) as genesis_file:
        genesis_config = json.load(genesis_file)

    db = LevelDB(chaindata_dir)
    initialize_genesis_state(genesis_config, db)


@cli.command()
@click.option(
    '--outfile',
    help="The file path to write the genesis file to",
)
@click.pass_context
def generate_genesis(ctx, outfile):
    configuration = ctx.obj

    if 'private_key' not in configuration:
        raise click.Exception('Cannot generate genesis file without a private key')

    data_dir = configuration['data_dir']

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    if outfile is None:
        outfile = get_genesis_file_path(data_dir)

    if os.path.exists(outfile):
        click.confirm("You are about to overwrite the genesis file at `{0}`.  Are you sure?".format(outfile), abort=True)

    genesis_data = {
        'timestamp': int(time.time()),
        'guardians': [configuration['private_key'].encode('hex')],
        'alloc': []
    }

    with open(outfile, 'w') as f:
        f.write(json.dumps(genesis_data))

    click.echo("Wrote new genesis file to `{0}`".format(outfile))


def initialize_genesis_state(genesis_config, db):
    # Create the genesis
    genesis = State('', db)
    initialize_with_gas_limit(genesis, 10**9)
    gc = genesis.clone()

    import ethereum
    # Unleash the kraken....err, I mean casper
    casper_file = os.path.join(os.path.split(ethereum.__file__)[0], 'casper.se.py')
    casper_hash_file = os.path.join(os.path.split(ethereum.__file__)[0], '_casper.hash')
    casper_evm_file = os.path.join(os.path.split(ethereum.__file__)[0], '_casper.evm')

    # Cache compilation of Casper to save time
    try:
        h = sha3(open(casper_file).read()).encode('hex')
        assert h == open(casper_hash_file).read()
        code = open(casper_evm_file).read()
    except:
        h = sha3(open(casper_file).read()).encode('hex')
        code = serpent.compile(casper_file)
        open(casper_evm_file, 'w').write(code)
        open(casper_hash_file, 'w').write(h)

    # Add Casper contract to blockchain
    tx_state_transition(gc, Transaction(None, 4000000, data='', code=code))
    put_code(genesis, CASPER, get_code(gc, mk_contract_address(code=code)))
    logger.info('Casper added')

    # Ringsig file and ct
    ringsig_file = os.path.join(os.path.split(ethereum.__file__)[0], 'ringsig.se.py')
    abi.ContractTranslator(serpent.mk_full_signature(open(ringsig_file).read()))

    # Get the code for the basic ecrecover account
    code2 = ecdsa_accounts.constructor_code
    tx_state_transition(gc, Transaction(None, 1000000, data='', code=code2))
    put_code(genesis, ECRECOVERACCT, get_code(gc, mk_contract_address(code=code2)))
    logger.info('ECRECOVER account added')

    # Get the code for the basic EC sender account
    code2 = ecdsa_accounts.runner_code
    tx_state_transition(gc, Transaction(None, 1000000, data='', code=code2))
    put_code(genesis, BASICSENDER, get_code(gc, mk_contract_address(code=code2)))
    logger.info('Basic sender account added')

    # Initialize the pre-alloced accounts for validators that join late.
    for key_hex, amount in genesis_config['alloc']:
        key = key_hex.decode('hex')
        addr = ecdsa_accounts.privtoaddr(key)
        # Give them their pre-allocated ether
        genesis.set_storage(ETHER, addr, amount)

    # Initialize the first guardians
    for i, key_hex in enumerate(genesis_config['guardians']):
        logger.info("Initializing Guardian: %s", key_hex)
        k = key_hex.decode('hex')
        # Generate the address
        a = ecdsa_accounts.privtoaddr(k)
        assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 0
        # Give them A bunch of ether
        genesis.set_storage(ETHER, a, 1000 * 1600 * 10**18)
        # Make their validation code
        vcode = ecdsa_accounts.mk_validation_code(k)
        # Make the transaction to join as a Casper guardian
        txdata = casper_ct.encode('join', [vcode])
        tx = ecdsa_accounts.mk_transaction(0, 25 * 10**9, 1000000, CASPER, 1500 * 10**18, txdata, k, True)
        v = tx_state_transition(genesis, tx)
        index = casper_ct.decode('join', ''.join(map(chr, v)))[0]
        logger.info("Guardian Initialized @ index: %s", index)
        # Check that the EVM that each account must have at the end
        # to get transactions included by default is there
        assert mandatory_account_evm == get_code(genesis, a).rstrip('\x00')
        # Check sequence number
        assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 1
        # Check that we actually joined Casper with the right
        # validation code
        vcode2 = call_method(genesis, CASPER, casper_ct, 'getGuardianValidationCode', [index])
        assert vcode2 == vcode
    GENESIS_TIMESTAMP = genesis_config['timestamp']


    # Set the starting RNG seed to equal to the number of casper guardians
    # in genesis
    genesis.set_storage(RNGSEEDS, encode_int32(2**256 - 1), genesis.get_storage(CASPER, 0))
    # Set the genesis timestamp
    genesis.set_storage(GENESIS_TIME, encode_int32(0), genesis_config['timestamp'])

    logger.info('Genesis time: %s', GENESIS_TIMESTAMP)

    return genesis

def get_network(bet, bootstrap_nodes=None):
    if bootstrap_nodes is None:
        bootstrap_nodes = []
    # setup the bootstrap node (node0) enode
    DEFAULT_PORT = 29870
    DEFAULT_IP_ADDRESS = b'0.0.0.0'

    PORT = get_arg('--port', int, DEFAULT_PORT)
    IP_ADDRESS = get_arg('--ip-address', str, DEFAULT_IP_ADDRESS)

    BOOTSTRAP_NODE_IP = get_arg('--bootstrap-ip', str, DEFAULT_IP_ADDRESS)
    BOOTSTRAP_NODE_PORT = get_arg('--bootstrap-port', int, DEFAULT_PORT)

    bootstrap_node_privkey = mk_privkey(genesis_config['guardians'][0].decode('hex'))
    bootstrap_node_pubkey = privtopub_raw(bootstrap_node_privkey)
    bootstrap_enode = host_port_pubkey_to_uri(BOOTSTRAP_NODE_IP, BOOTSTRAP_NODE_PORT, bootstrap_node_pubkey)

    print "Bootstrap ENODE: {0}".format(bootstrap_enode)

    services = [NodeDiscovery, peermanager.PeerManager, GuardianService]

    # prepare config
    config = dict()
    for s in services:
        update_config_with_defaults(config, s.default_config)

    MIN_PEERS = get_arg('--min-peers', int, 2)
    MAX_PEERS = get_arg('--max-peers', int, 25)

    config['node']['privkey_hex'] = mk_privkey(bet.key).encode('hex')

    config['p2p']['listen_port'] = PORT
    config['p2p']['min_peers'] = min(10, MIN_PEERS)
    config['p2p']['max_peers'] = MAX_PEERS

    config['discovery']['listen_port'] = PORT
    config['discovery']['bootstrap_nodes'] = bootstrap_nodes

    config['guardianservice']['agent'] = bet

    app = StandaloneGuardianApp(config)

    # register services
    for service in services:
        assert issubclass(service, BaseService)
        if service.name not in app.config['deactivated_services']:
            assert service.name not in app.services
            service.register_with_app(app)
            assert hasattr(app.services, service.name)

    import ipdb; ipdb.set_trace()

    return app


@cli.command()
@click.pass_context
def run(ctx):
    """
    Run the guardian node.
    - (maybe) initialize the data-dir
    - (maybe) write the genesis file
    - (maybe) write the initial chaindata state
    - start the guardian app.
    """
    configuration = ctx.obj

    data_dir = configuration['data_dir']
    private_key = configuration['private_key']
    genesis_path = configuration['genesis']
    chaindata_dir = get_chaindata_dir(data_dir)

    with open(genesis_path) as genesis_file:
        genesis_config = json.load(genesis_file)

    db = LevelDB(chaindata_dir)
    genesis_state = State('', db)

    bet = defaultBetStrategy(genesis_state, private_key)
    bet.network = get_network()


if __name__ == '__main__':
    cli(obj={})
