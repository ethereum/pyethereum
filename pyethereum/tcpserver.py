import socket
import time
import sys
import traceback
import logging

from dispatch import receiver

from stoppable import StoppableLoopThread
import signals

logger = logging.getLogger(__name__)


class TcpServer(StoppableLoopThread):

    def __init__(self):
        super(TcpServer, self).__init__()
        self.daemon = True

        self.sock = None
        self.ip = '0.0.0.0'
        self.port = 31033

    def configure(self, config):
        self.listen_host = config.get('network', 'listen_host')
        self.port = config.getint('network', 'listen_port')

    def pre_loop(self):
        # start server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.listen_host, self.port))
        sock.listen(5)
        self.sock = sock
        self.ip, self.port = sock.getsockname()
        logger.info("TCP server started {0}:{1}".format(self.ip, self.port))
        super(TcpServer, self).pre_loop()

    def loop_body(self):
        logger.debug('in run loop')
        try:
            connection, (ip, port) = self.sock.accept()
        except IOError:
            traceback.print_exc(file=sys.stdout)
            time.sleep(0.1)
            return
        signals.peer_connection_accepted.send(sender=self,
                                              connection=connection,
                                              ip=ip,
                                              port=port)

tcp_server = TcpServer()


@receiver(signals.config_ready)
def config_tcp_server(sender, **kwargs):
    tcp_server.configure(sender)
