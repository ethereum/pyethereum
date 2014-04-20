import socket
import time
import sys
import traceback
import logging

from common import StoppableLoopThread
from signals import connection_accepted

logger = logging.getLogger(__name__)


class TcpServer(StoppableLoopThread):

    def __init__(self, listen_host, port):
        super(TcpServer, self).__init__()
        self.daemon = True
        self.listen_host = listen_host
        self.port = port

        # start server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.listen_host, self.port))
        sock.listen(5)
        self.sock = sock
        self.ip, self.port = sock.getsockname()
        logger.info("TCP server started {0}:{1}".format(self.ip, self.port))

    def loop_body(self):
        logger.debug('in run loop')
        try:
            connection, (ip, port) = self.sock.accept()
        except IOError:
            traceback.print_exc(file=sys.stdout)
            time.sleep(0.1)
            return
        connection_accepted.send(sender=self,
                                 connection=connection,
                                 ip=ip,
                                 port=port)
