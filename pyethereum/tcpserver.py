import socket
import time
import sys
import traceback

from dispatch import receiver

from stoppable import StoppableLoopThread
import signals
from pyethereum.slogging import get_logger
log_net = get_logger('net')


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
    log_net.debug('Setting UPNP')

    import miniupnpc
    upnpc = miniupnpc.UPnP()
    upnpc.discoverdelay = 200
    ndevices = upnpc.discover()
    log_net.debug('UPNP device(s) detected', num=ndevices)

    if not ndevices:
        return None

    upnpc.selectigd()
    external_ip = upnpc.externalipaddress()
    log_net.debug('upnp', external_ip=external_ip,
                  status=upnpc.statusinfo(),
                  connection_type=upnpc.connectiontype())

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
        external_port += 1

    if not found:
        log_net.debug('No redirect candidate', external_ip=external_ip,
                      lan_ip=upnpc.lanaddr, lan_port=port)
        return None

    log_net.debug('trying to redirect', external_ip=external_ip, external_port=external_port,
                  lan_ip=upnpc.lanaddr, lan_port=port)

    res = upnpc.addportmapping(external_port, 'TCP',
                               upnpc.lanaddr, port,
                               'pyethereum p2p port %u' % external_port,
                               '')

    if res:
        log_net.debug('success to redirect', external_ip=external_ip, external_port=external_port,
                      lan_ip=upnpc.lanaddr, lan_port=port)
    else:
        return None
    return upnpc, external_ip, external_port


def upnp_delete(upnpc, external_port):
    res = upnpc.deleteportmapping(external_port, 'TCP')
    if res:
        log_net.debug('successfully deleted port mapping')
    else:
        log_net.debug('failed to remove port mapping')


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
        log_net.info('TCP server started', ip=self.ip, port=self.port)

        # setup upnp
        try:
            upnp_res = upnp_add(self.port)
            if upnp_res:
                self.upnpc, self.external_ip, self.external_port = upnp_res
        except Exception as e:
            log_net.debug('upnp failed', error=e)

        if not self.external_ip:
            try:
                self.external_ip = get_public_ip()
                self.external_port = self.port
            except Exception as e:
                log_net.debug('can\'t get public ip')

        if self.external_ip:
            signals.p2p_address_ready.send(sender=None,
                                           ip=self.external_ip,
                                           port=self.external_port)
            log_net.info('my public address',
                         external_ip=self.external_ip, external_port=self.external_port)

        super(TcpServer, self).pre_loop()

    def loop_body(self):
        log_net.debug('in run loop')
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
