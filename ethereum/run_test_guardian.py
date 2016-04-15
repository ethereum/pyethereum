import os
import random
import time
import json

import rlp
import serpent
import gevent

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

from serenity_blocks import (
    State,
    tx_state_transition,
    mk_contract_address,
    initialize_with_gas_limit,
    get_code,
    put_code,
)
from serenity_transactions import Transaction
from db import LevelDB, EphemDB, OverlayDB
from config import (
    BLKNUMBER,
    CASPER,
    ETHER,
    NONCE,
    ECRECOVERACCT,
    BASICSENDER,
    RNGSEEDS,
    GENESIS_TIME,
)
from utils import (
    zpad,
    encode_int,
    big_endian_to_int,
    encode_int32,
    sha3,
)
import ecdsa_accounts
import abi
import sys
from ethereum.guardian.utils import (
    call_method,
    casper_ct,
    encode_prob,
)
from ethereum.guardian.strategy import (
    defaultBetStrategy,
)
from ethereum.mandatory_account_code import mandatory_account_ct, mandatory_account_evm

from ethereum.guardian.network import (
    NetworkMessage,
    GuardianService,
    GuardianProtocol,
    GuardianApp,
)


# Maybe add logging
# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace'
# configure_logging(config_string=config_string)

# Listener; prints out logs in json format
def my_listen(sender, topics, data):
    jsondata = casper_ct.listen(sender, topics, data)
    if jsondata and jsondata["_event_type"] in ('BlockLoss', 'StateLoss'):
        if not bets[jsondata['index']].byzantine:
            if jsondata['loss'] < 0:
                if jsondata['odds'] < 10**7 and jsondata["_event_type"] == 'BlockLoss':
                    index = jsondata['index']
                    height = jsondata['height']
                    print 'bettor current probs', bets[index].probs[:height]
                    raise Exception("Odds waaaay too low! %r" % jsondata)
                if jsondata['odds'] > 10**11:
                    index = jsondata['index']
                    height = jsondata['height']
                    print 'bettor stateroots:', bets[index].stateroots
                    print 'bettor opinion:', bets[index].opinions[index].stateroots
                    if len(bets[0].stateroots) < height:
                        print 'in bettor 0 stateroots:', repr(bets[0].stateroots[height])
                    raise Exception("Odds waaaay too high! %r" % jsondata)
    if jsondata and jsondata["_event_type"] == 'ExcessRewardEvent':
        raise Exception("Excess reward event: %r" % jsondata)
    ecdsa_accounts.constructor_ct.listen(sender, topics, data)
    mandatory_account_ct.listen(sender, topics, data)
    jsondata = ringsig_ct.listen(sender, topics, data)


# Get command line parameters
def get_arg(flag, typ, default):
    if flag in sys.argv:
        return typ(sys.argv[sys.argv.index(flag) + 1])
    else:
        return default


DATA_DIR = get_arg('--data-dir', str, None)

if DATA_DIR is None:
    DATA_DIR = os.path.join('.', 'tmp', 'db-{0}'.format(os.getpid()))
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

# Create the genesis
genesis = State('', LevelDB(DATA_DIR))
initialize_with_gas_limit(genesis, 10**9)
gc = genesis.clone()

# Unleash the kraken....err, I mean casper
casper_file = os.path.join(os.path.split(__file__)[0], 'casper.se.py')
casper_hash_file = os.path.join(os.path.split(__file__)[0], '_casper.hash')
casper_evm_file = os.path.join(os.path.split(__file__)[0], '_casper.evm')

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
print 'Casper added'

# Ringsig file and ct
ringsig_file = os.path.join(os.path.split(__file__)[0], 'ringsig.se.py')
ringsig_code = serpent.compile(open(ringsig_file).read())
ringsig_ct = abi.ContractTranslator(serpent.mk_full_signature(open(ringsig_file).read()))

# Get the code for the basic ecrecover account
code2 = ecdsa_accounts.constructor_code
tx_state_transition(gc, Transaction(None, 1000000, data='', code=code2))
put_code(genesis, ECRECOVERACCT, get_code(gc, mk_contract_address(code=code2)))
print 'ECRECOVER account added'

# Get the code for the basic EC sender account
code2 = ecdsa_accounts.runner_code
tx_state_transition(gc, Transaction(None, 1000000, data='', code=code2))
put_code(genesis, BASICSENDER, get_code(gc, mk_contract_address(code=code2)))
print 'Basic sender account added'


def generate_genesis_config_file(path='genesis.json'):
    config = {
        'timestamp': int(time.time()),
        'guardians': [zpad(encode_int(1), 32).encode('hex')],
        'alloc': [
            (zpad(encode_int(i), 32).encode('hex'), 2000 * 10**18)
            for i in range(1, 11)
        ]
    }
    with open(path, 'w') as f:
        f.write(json.dumps(config))
    return config


def get_genesis_config(path='genesis.json'):
    with open(path) as f:
        return json.load(f)


genesis_config_path = get_arg('--genesis-config', str, 'genesis.json')
should_generate_genesis_config = get_arg('--generate-genesis', int, 0)

if should_generate_genesis_config:
    generate_genesis_config_file()

genesis_config = get_genesis_config(genesis_config_path)


# Initialize the pre-alloced accounts for validators that join late.
for key_hex, amount in genesis_config['alloc']:
    key = key_hex.decode('hex')
    addr = ecdsa_accounts.privtoaddr(key)
    # Give them 1600 ether
    genesis.set_storage(ETHER, addr, amount)


# Initialize the first guardians
for i, key_hex in enumerate(genesis_config['guardians']):
    k = key_hex.decode('hex')
    # Generate the address
    a = ecdsa_accounts.privtoaddr(k)
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 0
    # Give them 1600 ether
    #genesis.set_storage(ETHER, a, 1600 * 10**18)
    # Give them A LOT more ether
    genesis.set_storage(ETHER, a, 1000 * 1600 * 10**18)
    # Make their validation code
    vcode = ecdsa_accounts.mk_validation_code(k)
    print 'Length of validation code:', len(vcode)
    # Make the transaction to join as a Casper guardian
    txdata = casper_ct.encode('join', [vcode])
    tx = ecdsa_accounts.mk_transaction(0, 25 * 10**9, 1000000, CASPER, 1500 * 10**18, txdata, k, True)
    print 'Joining'
    v = tx_state_transition(genesis, tx, listeners=[my_listen])
    index = casper_ct.decode('join', ''.join(map(chr, v)))[0]
    print 'Joined with index', index
    print 'Length of account code:', len(get_code(genesis, a))
    # Check that the EVM that each account must have at the end
    # to get transactions included by default is there
    assert mandatory_account_evm == get_code(genesis, a).rstrip('\x00')
    # Check sequence number
    assert big_endian_to_int(genesis.get_storage(a, 2**256 - 1)) == 1
    # Check that we actually joined Casper with the right
    # validation code
    vcode2 = call_method(genesis, CASPER, casper_ct, 'getGuardianValidationCode', [index])
    assert vcode2 == vcode


# Determine the number of nodes that will be run.
#
# TODO: This will need to be reworked so that we can initialize the genesis
# state without needing to know about which other nodes are participating.
#
KEY_IDX = get_arg('--key-idx', int, None)
KEY = get_arg('--key', str, None)

if KEY is None:
    if KEY_IDX is None:
        KEY = zpad(encode_int(random.randint(1e16, 1e32)), 32)
        print "Using KEY=", KEY.encode('hex')
    elif KEY_IDX < len(genesis_config['alloc']):
        KEY = genesis_config['alloc'][KEY_IDX][0].decode('hex')
    else:
        raise Exception("Key index out of range")
elif KEY_IDX is not None:
    raise Exception("Cannot specify both --key and --key-idx")
else:
    KEY = zpad(KEY, 32)


JOIN_AT_BLOCK = get_arg('--join-at-block', int, -1)


GENESIS_TIMESTAMP = genesis_config['timestamp']


# Set the starting RNG seed to equal to the number of casper guardians
# in genesis
genesis.set_storage(RNGSEEDS, encode_int32(2**256 - 1), genesis.get_storage(CASPER, 0))
# Set the genesis timestamp
genesis.set_storage(GENESIS_TIME, encode_int32(0), GENESIS_TIMESTAMP)
print 'genesis time', GENESIS_TIMESTAMP, '\n' * 10
# Create betting strategy objects for every guardian
# TODO: may not need to `clone()` this anymore since it's singular.
bet = defaultBetStrategy(genesis.clone(), KEY, join_at_block=JOIN_AT_BLOCK)
bets = [bet]

# Minimum max finalized height
min_mfh = -1

# Transactions to status report on
check_txs = []


# Function to check consistency between everything
def check_correctness(bets):
    global min_mfh
    print '#' * 80
    # Max finalized heights for each bettor strategy
    mfhs = [bet.max_finalized_height for bet in bets if not bet.byzantine]
    mchs = [bet.calc_state_roots_from for bet in bets if not bet.byzantine]
    mfchs = [min(bet.max_finalized_height, bet.calc_state_roots_from) for bet in bets if not bet.byzantine]
    new_min_mfh = min(mfchs)
    print 'Max finalized heights: %r' % [bet.max_finalized_height for bet in bets]
    print 'Max calculated stateroots: %r' % [bet.calc_state_roots_from for bet in bets]
    print 'Max height received: %r' % [len(bet.blocks) for bet in bets]
    # Induction heights of each guardian
    print 'Registered induction heights: %r' % [[op.induction_height for op in bet.opinions.values()] for bet in bets]
    # Withdrawn?
    print 'Withdrawn?: %r' % [(bet.withdrawn, bet.seq) for bet in bets]
    # Probabilities
    # print 'Probs: %r' % {i: [bet.probs[i] if i < len(bet.probs) else None for bet in bets] for i in range(new_min_mfh, max([len(bet.blocks) for bet in bets]))}
    # Data about bets from each guardian according to every other guardian
    print 'Now: %.2f' % time.time()
    print 'According to each guardian...'
    for bet in bets:
        print ('(%d) Bets received: %r, blocks received: %s. Last bet made: %.2f.' % (bet.index, [((str(op.seq) + ' (withdrawn)') if op.withdrawn else op.seq) for op in bet.opinions.values()], ''.join(['1' if b else '0' for b in bet.blocks]), bet.last_bet_made))
        print 'Probs (in 0-255 repr, from %d):' % (new_min_mfh + 1), map(lambda x: ord(encode_prob(x)), bet.probs[new_min_mfh + 1:])
    # Indices of guardians
    print 'Indices: %r' % [bet.index for bet in bets]
    # Number of blocks received by each guardian
    print 'Blocks received: %r' % [len(bet.blocks) for bet in bets]
    # Number of blocks received by each guardian
    print 'Blocks missing: %r' % [[h for h in range(len(bet.blocks)) if not bet.blocks[h]] for bet in bets]
    # Makes sure all block hashes for all heights up to the minimum finalized
    # height are the same
    print 'Verifying finalized block hash equivalence'
    for j in range(1, len(bets)):
        if not bets[j].byzantine and not bets[j - 1].byzantine:
            j_hashes = bets[j].finalized_hashes[:(new_min_mfh + 1)]
            jm1_hashes = bets[j - 1].finalized_hashes[:(new_min_mfh + 1)]
            assert j_hashes == jm1_hashes, (j_hashes, jm1_hashes)
    # Checks state roots for finalized heights and makes sure that they are
    # consistent
    print 'Verifying finalized state root correctness'
    state = State(genesis.root if min_mfh < 0 else bets[0].stateroots[min_mfh], OverlayDB(bets[0].db))
    for b in bets:
        if not b.byzantine:
            for i in range(new_min_mfh):
                assert b.stateroots[i] not in ('\x00' * 32, None)
    print 'Executing blocks %d to %d' % (min_mfh + 1, max(min_mfh, new_min_mfh) + 1)
    # TODO: figure out what to do to fix this.
    # This part requires looking at more than 1 bet object which can't be done
    # in this situation.
    #
    #for i in range(min_mfh + 1, max(min_mfh, new_min_mfh) + 1):
    #    assert state.root == bets[0].stateroots[i - 1] if i > 0 else genesis.root
    #    block = bets[j].objects[bets[0].finalized_hashes[i]] if bets[0].finalized_hashes[i] != '\x00' * 32 else None
    #    block0 = bets[0].objects[bets[0].finalized_hashes[i]] if bets[0].finalized_hashes[i] != '\x00' * 32 else None
    #    assert block0 == block
    #    block_state_transition(state, block, listeners=[my_listen])
    #    if state.root != bets[0].stateroots[i] and i != max(min_mfh, new_min_mfh):
    #        print bets[0].calc_state_roots_from, bets[j].calc_state_roots_from
    #        print bets[0].max_finalized_height, bets[j].max_finalized_height
    #        print 'my state', state.to_dict()
    #        print 'given state', State(bets[0].stateroots[i], bets[0].db).to_dict()
    #        import rlp
    #        print 'block', repr(rlp.encode(block))
    #        sys.stderr.write('State root mismatch at block %d!\n' % i)
    #        sys.stderr.write('state.root: %s\n' % state.root.encode('hex'))
    #        sys.stderr.write('bet: %s\n' % bets[0].stateroots[i].encode('hex'))
    #        raise Exception(" ")
    min_mfh = new_min_mfh
    print 'Min common finalized height: %d, integrity checks passed' % new_min_mfh
    # Last and next blocks to propose by each guardian
    print 'Last block created: %r' % [bet.last_block_produced for bet in bets]
    print 'Next blocks to create: %r' % [bet.next_block_to_produce for bet in bets]
    # Assert equivalence of proposer lists
    min_proposer_length = min([len(bet.proposers) for bet in bets])
    for i in range(1, len(bets)):
        assert bets[i].proposers[:min_proposer_length] == bets[0].proposers[:min_proposer_length]
    # Guardian sequence numbers as seen by themselves
    print 'Guardian seqs online: %r' % [bet.seq for bet in bets]
    # Guardian sequence numbers as recorded in the chain
    print 'Guardian seqs on finalized chain (%d): %r' % (new_min_mfh, [call_method(state, CASPER, casper_ct, 'getGuardianSeq', [bet.index if bet.index >= 0 else bet.former_index]) for bet in bets])
    h = 0
    while h < len(bets[0].stateroots) and bets[0].stateroots[h] not in (None, '\x00' * 32):
        h += 1
    speculative_state = State(bets[0].stateroots[h - 1] if h else genesis.root, OverlayDB(bets[0].db))
    print 'Guardian seqs on speculative chain (%d): %r' % (h - 1, [call_method(speculative_state, CASPER, casper_ct, 'getGuardianSeq', [bet.index if bet.index >= 0 else bet.former_index]) for bet in bets])
    # Guardian deposit sizes (over 1500 * 10**18 means profit)
    print 'Guardian deposit sizes: %r' % [call_method(state, CASPER, casper_ct, 'getGuardianDeposit', [bet.index]) for bet in bets if bet.index >= 0]
    print 'Estimated guardian excess gains: %r' % [call_method(state, CASPER, casper_ct, 'getGuardianDeposit', [bet.index]) - 1500 * 10**18 + 47 / 10**9. * 1500 * 10**18 * min_mfh for bet in bets if bet.index >= 0]
    for bet in bets:
        if bet.index >= 0 and big_endian_to_int(state.get_storage(BLKNUMBER, '\x00' * 32)) >= bet.induction_height:
            assert (call_method(state, CASPER, casper_ct, 'getGuardianDeposit', [bet.index]) >= 1499 * 10**18) or bet.byzantine, (bet.double_bet_suicide, bet.byzantine)
    # Account signing nonces
    print 'Account signing nonces: %r' % [big_endian_to_int(state.get_storage(bet.addr, NONCE)) for bet in bets]
    # Transaction status
    print 'Transaction status in unconfirmed_txindex: %r' % [bets[0].unconfirmed_txindex.get(tx.hash, None) for tx in check_txs]
    print 'Transaction status in finalized_txindex: %r' % [bets[0].finalized_txindex.get(tx.hash, None) for tx in check_txs]
    print 'Transaction exceptions: %r' % [bets[0].tx_exceptions.get(tx.hash, 0) for tx in check_txs]

# Gevent config
gevent.get_hub().SYSTEM_ERROR = BaseException


def mk_privkey(seed):
    return sha3(seed)


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

config['node']['privkey_hex'] = mk_privkey(KEY).encode('hex')

config['p2p']['listen_port'] = PORT
config['p2p']['min_peers'] = min(10, MIN_PEERS)
config['p2p']['max_peers'] = MAX_PEERS

config['discovery']['listen_port'] = PORT
config['discovery']['bootstrap_nodes'] = [bootstrap_enode]

config['guardianservice']['agent'] = bet


class StandaloneGuardianApp(GuardianApp):
    def broadcast(self, sender, obj):
        assert isinstance(obj, (str, bytes))
        network_message = rlp.decode(obj, NetworkMessage)
        bcast = self.services.peermanager.broadcast
        bcast(
            GuardianProtocol,
            'network_message',
            args=(network_message,),
            exclude_peers=[],
        )

    def send_to_one(self, sender, obj):
        assert isinstance(obj, (str, bytes))

        peer = random.choice(self.services.peermanager.peers)

        self.direct_send(sender, peer.remote_pubkey, obj)

    @property
    def peers(self):
        return self.services.peermanager.peers

    def direct_send(self, sender, to_id, obj):
        to_peer = None

        for peer in self.services.peermanager.peers:
            if peer.remote_pubkey == to_id:
                to_peer = peer
                break

        if to_peer is None:
            raise ValueError("Not connected to the provided agent")

        proto = to_peer.protocols[GuardianProtocol]
        proto.send_network_message(rlp.decode(obj, NetworkMessage))

    @property
    def now(self):
        return time.time()


# prepare app
app = StandaloneGuardianApp(config)
bet.network = app


# register services
for service in services:
    assert issubclass(service, BaseService)
    if service.name not in app.config['deactivated_services']:
        assert service.name not in app.services
        service.register_with_app(app)
        assert hasattr(app.services, service.name)

# start the app
app.start()

# Keep running until the min finalized height reaches 20
while 1:
    start = time.time()
    while start + 25 > time.time():
        bet.tick()
        gevent.sleep(random.random())
    check_correctness(bets)
    if min_mfh >= 500:
        print 'Reached breakpoint'
        break
    print 'Min mfh:', min_mfh
