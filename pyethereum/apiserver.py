import threading
import json

import bottle

from pyethereum.chainmanager import chain_manager
from pyethereum.peermanager import peer_manager
import pyethereum.dispatch as dispatch
from pyethereum.blocks import Block
import pyethereum.signals as signals
from pyethereum.transactions import Transaction
import pyethereum.processblock as processblock
import pyethereum.utils as utils
import rlp
from rlp.utils import decode_hex, encode_hex
from pyethereum.slogging import get_logger, LogRecorder
from pyethereum._version import get_versions
from pyethereum.utils import to_string

chain = chain_manager.chain

log = get_logger('api')

app = bottle.Bottle()
app.config['autojson'] = False
app.install(bottle.JSONPlugin(json_dumps=lambda s: json.dumps(s, sort_keys=True)))


class ApiServer(threading.Thread):

    def __init__(self):
        super(ApiServer, self).__init__()
        self.daemon = True
        self.listen_host = '127.0.0.1'
        self.port = 30203

    def configure(self, config):
        self.listen_host = config.get('api', 'listen_host')
        self.port = config.getint('api', 'listen_port')
        # add api_path to bottle to be used in the middleware
        api_path = config.get('api', 'api_path')
        assert api_path.startswith('/') and not api_path.endswith('/')
        app.api_path = api_path

    def run(self):
        middleware = Middleware(app)
        bottle.run(middleware, server='waitress', host=self.listen_host, port=self.port)

# ###### create server ######

api_server = ApiServer()


@dispatch.receiver(signals.config_ready)
def config_api_server(sender, config, **kwargs):
    api_server.configure(config)


# ####### CORS, LOFFING AND REWRITE MIDDLEWARE ##############
class Middleware:
    HEADERS = [
        ('Access-Control-Allow-Origin', '*'),
        ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
        ('Access-Control-Allow-Headers',
         'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token')
    ]

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # strip api prefix from path
        orig_path = environ['PATH_INFO']
        if orig_path.startswith(self.app.api_path):
            environ['PATH_INFO'] = orig_path.replace(self.app.api_path, '', 1)

        log.debug('%r: %s => %s' % (environ['REQUEST_METHOD'], orig_path, environ['PATH_INFO']))

        if environ["REQUEST_METHOD"] == "OPTIONS":
            start_response('200 OK', self.HEADERS + [('Content-Length', "0")])
            return ""
        else:
            def my_start_response(status, headers, exc_info=None):
                headers.extend(self.HEADERS)
                return start_response(status, headers, exc_info)
            return self.app(environ, my_start_response)


# ######### Utilities ########
def load_json_req():
    json_body = bottle.request.json
    if not json_body:
        json_body = json.load(bottle.request.body)
    return json_body


# ######## Version ###########
@app.get('/version/')
def version():
    log.debug('version')
    v = get_versions()
    v['name'] = 'pyethereum'
    return dict(version=v)


# ######## Blocks ############
def make_blocks_response(blocks):
    res = []
    for b in blocks:
        h = b.to_dict(with_uncles=True)
        h['hash'] = b.hex_hash()
        h['chain_difficulty'] = b.chain_difficulty()
        res.append(h)
    return dict(blocks=res)


@app.get('/blocks/')
def blocks():
    log.debug('blocks/')
    return make_blocks_response(chain.get_chain(start='', count=20))


@app.get('/blocks/<arg>')
def block(arg=None):
    """
    /blocks/            return N last blocks
    /blocks/head        return head
    /blocks/<int>       return block by number
    /blocks/<hex>       return block by hexhash
    """
    log.debug('blocks/%s' % arg)
    try:
        if arg is None:
            return blocks()
        elif arg == 'head':
            blk = chain.head
        elif arg.isdigit():
            blk = chain.get(chain_manager.index.get_block_by_number(int(arg)))
        else:
            try:
                h = decode_hex(arg)
            except TypeError:
                raise KeyError
            blk = chain.get(h)
    except KeyError:
        return bottle.abort(404, 'Unknown Block  %s' % arg)
    return make_blocks_response([blk])


@app.get('/blocks/<arg>/children')
def block_children(arg=None):
    """
    /blocks/<hex>/children       return list of children hashes
    """
    log.debug('blocks/%s/children' % arg)
    try:
        h = decode_hex(arg)
        children = chain.index.get_children(h)
    except (KeyError, TypeError):
        return bottle.abort(404, 'Unknown Block  %s' % arg)
    return dict(children=[encode_hex(c) for c in children])


# ######## Transactions ############
def make_transaction_response(txs):
    return dict(transactions=[tx.to_dict() for tx in txs])


@app.put('/transactions/')
def add_transaction():
    # request.json FIXME / post json encoded data? i.e. the representation of
    # a tx
    hex_data = bottle.request.body.read()
    tx = Transaction.hex_deserialize(hex_data)
    #signals.local_transaction_received.send(sender=None, transaction=tx)
    res = chain_manager.add_transaction(tx)
    if res:
        return bottle.redirect('/transactions/' + tx.hex_hash())
    else:
        bottle.abort(400, 'Invalid Transaction %s' % tx.hex_hash())


def get_transaction_and_block(arg=None):
    try:
        tx_hash = decode_hex(arg)
    except TypeError:
        bottle.abort(500, 'No hex  %s' % arg)
    try:  # index
        tx, blk, i = chain_manager.index.get_transaction(tx_hash)
    except KeyError:
        # try miner
        txs = chain_manager.miner.get_transactions()
        found = [tx for tx in txs if tx.hex_hash() == arg]
        if not found:
            return bottle.abort(404, 'Unknown Transaction  %s' % arg)
        tx, blk = found[0], chain_manager.miner.block
    # response
    return tx, blk


@app.get('/transactions/<arg>')
def get_txdetails(arg=None):
    """
    /transactions/<hex>          return transaction by hexhash
    """
    tx, blk = get_transaction_and_block(arg)
    tx = tx.to_dict()
    tx['block'] = blk.hex_hash()
    if not chain_manager.in_main_branch(blk):
        tx['confirmations'] = 0
    else:
        tx['confirmations'] = chain.head.number - blk.number
    return dict(transactions=[tx])


@app.get('/rawtx/<arg>')
def get_rawtx(arg=None):
    """
    /rawtx/<hex>          return transaction hex by hexhash
    """
    tx, blk = get_transaction_and_block(arg)
    return tx.hex_serialize()


@app.get('/pending/')
def get_pending():
    """
    /pending/       return pending transactions
    """
    return dict(transactions=[tx.to_dict() for tx in chain_manager.miner.get_transactions()])


# ########### Trace ############
def _get_block_before_tx(txhash):
    tx, blk, i = chain_manager.index.get_transaction(decode_hex(txhash))
    # get the state we had before this transaction
    test_blk = Block.init_from_parent(blk.get_parent(),
                                      blk.coinbase,
                                      extra_data=blk.extra_data,
                                      timestamp=blk.timestamp,
                                      uncles=blk.uncles)
    pre_state = test_blk.state_root
    for i in range(blk.transaction_count):
        tx_lst_serialized, sr, _ = blk.get_transaction(i)
        if utils.sha3(rlp.encode(tx_lst_serialized)) == tx.hash:
            break
        else:
            pre_state = sr
    test_blk.state.root_hash = pre_state
    return test_blk, tx, i


def get_trace(txhash):
    try:  # index
        test_blk, tx, i = _get_block_before_tx(txhash)
    except (KeyError, TypeError):
        return bottle.abort(404, 'Unknown Transaction  %s' % txhash)

    # collect debug output
    recorder = LogRecorder()
    # apply tx (thread? we don't want logs from other invocations)
    processblock.apply_transaction(test_blk, tx)

    return dict(tx=txhash, trace=recorder.pop_records())


@app.get('/trace/<txhash>')
def trace(txhash):
    """
    /trace/<hexhash>        return basic trace for transaction
    """
    return get_trace(txhash)


@app.get('/dtrace/<params>/<txhash>')
def dtrace(params, txhash):
    """
    /trace/<params>/<hexhash>  return detailed trace for transaction, params
                               4-char binary string for op, stack, memory,
                               storage (eg. 1011 = op, mem, storage only)
    """
    help = 'Params must be binary string of length 4 /op|stack|memory|storage/'

    if len(params) != 4:
        return bottle.abort(404, help)
    t = get_trace(txhash)

    def _remove(key):
        for l in t['trace']:
            if key in l:
                del l[key]
    #  params[0] log op can not be filtered
    # see vm.py for details
    if not params[1]:
        _remove('stack')
    if not params[2]:
        _remove('memory')
    if not params[2]:
        _remove('storage')
    return t


# SPV proofs

@app.get('/spv/tx/<txhash>')
def spvtrace(txhash):
    try:  # index
        tx, blk, i = chain_manager.index.get_transaction(decode_hex(txhash))
    except (KeyError, TypeError):
        return bottle.abort(404, 'Unknown Transaction  %s' % txhash)

    return encode_hex(processblock.mk_independent_transaction_spv_proof(blk, i))


@app.get('/spv/acct/<addr>')
def spvaddr(addr):
    return chain.head.state.produce_spv_proof(decode_hex(addr))


@app.get('/spv/storage/<addr>/<index>')
def spvstorage(addr, index):
    prf1 = chain.head.state.produce_spv_proof(decode_hex(addr))
    storetree = chain.head.get_storage(addr)
    prf2 = storetree.produce_spv_proof(utils.zpad(utils.encode_int(index), 32))
    return encode_hex(rlp.encode(prf1 + prf2))


# Fetch state data

@app.get('/acct/<addr>')
def getacct(addr):
    """
    /acct/<addr>        return account details
    """
    return chain.head.account_to_dict(addr)


@app.get('/storage/<addr>/<index>')
def getacctdata(addr, index):
    """
    /storage/<addr>/<index>        return storage item
    """
    return to_string(chain.head.get_storage_data(addr, int(index)))


@app.get('/dump/<txblkhash>')
def dump(txblkhash):
    """
    /dump/<hash>        return state dump after transaction or block
    """
    try:
        blk = chain.get(decode_hex(txblkhash))
    except:
        try:  # index
            test_blk, tx, i = _get_block_before_tx(txblkhash)
        except (KeyError, TypeError):
            return bottle.abort(404, 'Unknown Transaction  %s' % txblkhash)
        processblock.apply_transaction(test_blk, tx)
        blk = test_blk
    # format
    return blk.to_dict(with_state=True, with_uncles=True)


# ######## Accounts ############
@app.get('/accounts/<address>')
def account(address=None):
    log.debug('accounts/%s' % address)
    data = chain.head.account_to_dict(address)
    return data


# ######## Peers ###################
def make_peers_response(peers):
    objs = [dict(ip=ip, port=port, node_id=encode_hex(node_id))
            for (ip, port, node_id) in peers]
    return dict(peers=objs)


@app.get('/peers/connected')
def connected_peers():
    return make_peers_response(peer_manager.get_connected_peer_addresses())


@app.get('/peers/known')
def known_peers():
    return make_peers_response(peer_manager.get_known_peer_addresses())
