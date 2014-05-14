import socket
import time
import sys
import traceback
import logging

from dispatch import receiver

from stoppable import StoppableLoopThread
import signals

logger = logging.getLogger(__name__)


def get_public_ip():
    try:
        # for python3
        from urllib.request import urlopen
    except ImportError:
        # for python2
        from urllib import urlopen
    return urlopen('http://icanhazip.com/').read().strip()


def upnp_add(port):
    '''
    :param port: local port
    :return: `None` if failed, `external_ip, external_port` if succeed
    '''
    logger.debug('Setting UPNP')

    import miniupnpc
    upnpc = miniupnpc.UPnP()
    upnpc.discoverdelay = 200
    ndevices = upnpc.discover()
    logger.debug('%d UPNP device(s) detected', ndevices)

    if not ndevices:
        return None

    upnpc.selectigd()
    external_ip = upnpc.externalipaddress()
    logger.debug('external ip: %s', external_ip)
    logger.debug('status: %s, connection type: %s',
                 upnpc.statusinfo(),
                 upnpc.connectiontype())

    # find a free port for the redirection
    external_port = port
    found = False

    while True:
        redirect = upnpc.getspecificportmapping(external_port, 'TCP')
        if redirect is None:
            found = True
            break
        if external_port >= 65535:
            break
        external_port = external_port + 1

    if not found:
        logger.debug('No redirect candidate %s TCP => %s port %u TCP',
                     external_ip, upnpc.lanaddr, port)
        return None

    logger.debug('trying to redirect %s port %u TCP => %s port %u TCP',
                 external_ip, external_port, upnpc.lanaddr, port)

    res = upnpc.addportmapping(external_port, 'TCP',
                               upnpc.lanaddr, port,
                               'pyethereum p2p port %u' % external_port,
                               '')

    if res:
        logger.info('Success to redirect %s port %u TCP => %s port %u TCP',
                    external_ip, external_port, upnpc.lanaddr, port)
    else:
        return None
    return upnpc, external_ip, external_port


def upnp_delete(upnpc, external_port):
    res = upnpc.deleteportmapping(external_port, 'TCP')
    if res:
        logger.debug('Successfully deleted port mapping')
    else:
        logger.debug('Failed to remove port mapping')


class TcpServer(StoppableLoopThread):

    def __init__(self):
        super(TcpServer, self).__init__()
        self.daemon = True

        self.sock = None
        self.ip = '0.0.0.0'
        self.port = 31033

        self.upnpc = None
        self.external_ip = None
        self.external_port = None

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

        # setup upnp
        try:
            upnp_res = upnp_add(self.port)
            if upnp_res:
                self.upnpc, self.external_ip, self.external_port = upnp_res
        except Exception as e:
            logger.debug('upnp failed: %s', e)

        if not self.external_ip:
            try:
                self.external_ip = get_public_ip()
                self.external_port = self.port
            except Exception as e:
                logger.debug('can\'t get public ip')

        if self.external_ip:
            signals.p2p_address_ready.send(sender=None,
                                           ip=self.external_ip,
                                           port=self.external_port)
            logger.info('my public address is %s:%s',
                        self.external_ip, self.external_port)

        super(TcpServer, self).pre_loop()

    def loop_body(self):
        logger.debug('in run loop')
        try:
            connection, (ip, port) = self.sock.accept()
        except IOError:
            traceback.print_exc(file=sys.stdout)
            time.sleep(0.01)
            return
        signals.peer_connection_accepted.send(sender=None,
                                              connection=connection,
                                              ip=ip,
                                              port=port)

    def post_loop(self):
        if self.upnpc:
            upnp_delete(self.upnpc, self.external_port)
        super(TcpServer, self).post_loop()


tcp_server = TcpServer()


@receiver(signals.config_ready)
def config_tcp_server(sender, config, **kwargs):
    tcp_server.configure(config)
