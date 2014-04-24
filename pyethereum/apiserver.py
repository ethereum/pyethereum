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
        bottle_run(app, host=self.listen_host, port=self.port)

api_server = ApiServer()


@receiver(signals.config_ready)
def config_api_server(sender, **kwargs):
    api_server.configure(sender)
