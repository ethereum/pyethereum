import logging
import threading

from bottle import run as bottle_run
from dispatch import receiver

from api import app
import signals

logger = logging.getLogger(__name__)


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
        bottle_run(app, server='waitress',
                   host=self.listen_host, port=self.port)

api_server = ApiServer()


@receiver(signals.config_ready)
def config_api_server(sender, **kwargs):
    api_server.configure(sender)

###################################
from marshmallow import Serializer, fields
from hyp.responder import Responder
from bottle import Bottle
from pyethereum.blocks import block_structure
from pyethereum.chainmanager import chain_manager

app = Bottle()
app.config['autojson'] = True


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


@app.get('/blocks/')
def blocks():
    logger.debug('blocks/')
    return BlocksResponder().respond(chain_manager.get_chain(start=0, count=20))


@app.get('/blocks/<blockhash>')
def block(blockhash=None):
    logger.debug('blocks/%s', blockhash)
    blockhash = blockhash.decode('hex')
    if blockhash in chain_manager:
        return BlocksResponder().respond(chain_manager.get(blockhash))
    else:
        return '404 Not Found'  # 404
