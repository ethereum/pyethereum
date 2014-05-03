import logging
import threading
import bottle
from marshmallow import Serializer, fields
import hyp.responder
from pyethereum.blocks import block_structure
from pyethereum.chainmanager import chain_manager
from pyethereum.peermanager import peer_manager
import pyethereum.dispatch as dispatch
import pyethereum.signals as signals
from pyethereum.transactions import Transaction

logger = logging.getLogger(__name__)
base_url = '/api/v0alpha'

app = bottle.Bottle()
app.config['autojson'] = True


class ApiServer(threading.Thread):

    def __init__(self):
        super(ApiServer, self).__init__()
        self.daemon = True
        self.listen_host = '127.0.0.1'
        self.port = 30203

    def configure(self, config):
        self.listen_host = config.get('api', 'listen_host')
        self.port = config.getint('api', 'listen_port')

    def run(self):
        middleware = CorsMiddleware(app)
        bottle.run(middleware, server='waitress',
                   host=self.listen_host, port=self.port)

# ###### create server ######

api_server = ApiServer()


@dispatch.receiver(signals.config_ready)
def config_api_server(sender, **kwargs):
    api_server.configure(sender)


# #######cors##############
class CorsMiddleware:
    HEADERS = [
        ('Access-Control-Allow-Origin', '*'),
        ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
        ('Access-Control-Allow-Headers',
         'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token')
    ]

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        if environ["REQUEST_METHOD"] == "OPTIONS":
            start_response('200 OK',
                           CorsMiddleware.HEADERS + [('Content-Length', "0")])
            return ""
        else:
            def my_start_response(status, headers, exc_info=None):
                headers.extend(CorsMiddleware.HEADERS)

                return start_response(status, headers, exc_info)
            return self.app(environ, my_start_response)

# ####### ##############

# pretty print patch


class Responder(hyp.responder.Responder):

    def respond(self, instances, meta=None, links=None, linked=None):
        if not isinstance(instances, list):
            instances = [instances]
        if linked is not None:
            links = linked.keys()
        document = {}
        document['meta'] = self.build_meta(meta)
        document['links'] = self.build_links(links)
        document['linked'] = self.build_linked(linked)
        document[self.root] = self.build_resources(instances, links)
        [document.pop(key) for key in document.keys() if document[key] is None]
        return hyp.responder.json.dumps(document, indent=0)

# ############ Blocks ######################


class Binary(fields.Raw):

    def format(self, value):
        return value.encode('hex')


class BlockSerializer(Serializer):
    blockhash = fields.Function(lambda o: o.hex_hash())
    prevhash = Binary()
    uncles_hash = Binary()
    nonce = Binary()
    tx_list_root = Binary()

    class Meta:
        fields = [name for name, typ, _ in block_structure] + ['blockhash']


class BlocksResponder(Responder):
    TYPE = 'blocks'
    SERIALIZER = BlockSerializer


@app.get(base_url + '/blocks/')
def blocks():
    logger.debug('blocks/')
    return BlocksResponder().respond(
        chain_manager.get_chain(start='', count=20))


@app.get(base_url + '/blocks/<blockhash>')
def block(blockhash=None):
    logger.debug('blocks/%s', blockhash)
    blockhash = blockhash.decode('hex')
    if blockhash in chain_manager:
        return BlocksResponder().respond(chain_manager.get(blockhash))
    else:
        return bottle.abort(404, 'No block with id %s' % blockhash)


# ######## Transactions ############
@app.put(base_url + '/transactions/')
def transactions():
    # request.json FIXME / post json encoded data? i.e. the representation of
    # a tx
    hex_data = bottle.request.body.read()
    logger.debug('PUT transactions/ %s', hex_data)
    tx = Transaction.hex_deserialize(hex_data)
    signals.local_transaction_received.send(sender=None, transaction=tx)
    return bottle.redirect(base_url + '/transactions/' + tx.hex_hash())


# ######## Peers ###################


class PeerSerializer(Serializer):
    ip = fields.Function(lambda o: o['ip'])
    port = fields.Function(lambda o: str(o['port']))
    node_id = fields.Function(lambda o: o['node_id'].encode('hex'))


class PeerResponder(Responder):
    TYPE = 'peer'
    SERIALIZER = PeerSerializer


def make_peers_response(peers):
    peers = [dict(ip=ip, port=port, node_id=node_id) for
             (ip, port, node_id) in peers]
    return PeerResponder().respond(peers)


@app.get(base_url + '/connected_peers/')
def connected_peers():
    return make_peers_response(peer_manager.get_connected_peer_addresses())


@app.get(base_url + '/known_peers/')
def known_peers():
    return make_peers_response(peer_manager.get_known_peer_addresses())
