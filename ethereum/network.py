import random
import sys
import time
from utils import DEBUG

# A network simulator


class NetworkSimulatorBase():

    start_time = time.time()

    def __init__(self, latency=50, agents=[], reliability=0.9, broadcast_success_rate=1.0):
        self.agents = agents
        self.latency_distribution_sample = transform(
            normal_distribution(latency, (latency * 2) // 5), lambda x: max(x, 0))
        self.time = 0
        self.objqueue = {}
        self.peers = {}
        self.reliability = reliability
        self.broadcast_success_rate = broadcast_success_rate
        self.time_sleeping = 0
        self.time_running = 0
        self.sleepdebt = 0

    def generate_peers(self, num_peers=5):
        self.peers = {}
        for a in self.agents:
            p = []
            while len(p) <= num_peers // 2:
                p.append(random.choice(self.agents))
                if p[-1] == a:
                    p.pop()
            self.peers[a.id] = list(set(self.peers.get(a.id, []) + p))
            for peer in p:
                self.peers[peer.id] = list(set(self.peers.get(peer.id, []) + [a]))

    def tick(self):
        if self.time in self.objqueue:
            for sender_id, recipient, obj in self.objqueue[self.time]:
                if random.random() < self.reliability:
                    recipient.on_receive(obj, sender_id)
            del self.objqueue[self.time]
        for a in self.agents:
            a.tick()
        self.time += 1

    def run(self, seconds, sleep=0):
        t = 0
        while 1:
            a = time.time()
            self.tick()
            timedelta = time.time() - a
            if sleep > timedelta:
                tsleep = sleep - timedelta
                sleepdebt_repayment = min(self.sleepdebt, tsleep * 0.5)
                time.sleep(tsleep - sleepdebt_repayment)
                self.time_sleeping += tsleep - sleepdebt_repayment
                self.sleepdebt -= sleepdebt_repayment
            else:
                self.sleepdebt += timedelta - sleep
            self.time_running += timedelta
            print 'Tick finished in: %.2f. Total sleep %.2f, running %.2f' % (timedelta, self.time_sleeping, self.time_running)
            if self.sleepdebt > 0:
                print 'Sleep debt: %.2f' % self.sleepdebt
            t += time.time() - a
            if t >= seconds:
                return

    def broadcast(self, sender, obj):
        assert isinstance(obj, (str, bytes))
        if random.random() < self.broadcast_success_rate:
            for p in self.peers[sender.id]:
                recv_time = self.time + self.latency_distribution_sample()
                if recv_time not in self.objqueue:
                    self.objqueue[recv_time] = []
                self.objqueue[recv_time].append((sender.id, p, obj))

    def send_to_one(self, sender, obj):
        assert isinstance(obj, (str, bytes))
        if random.random() < self.broadcast_success_rate:
            p = random.choice(self.peers[sender.id])
            recv_time = self.time + self.latency_distribution_sample()
            if recv_time not in self.objqueue:
                self.objqueue[recv_time] = []
            self.objqueue[recv_time].append((sender.id, p, obj))

    def direct_send(self, sender, to_id, obj):
        if random.random() < self.broadcast_success_rate * self.reliability:
            for a in self.agents:
                if a.id == to_id:
                    recv_time = self.time + self.latency_distribution_sample()
                    if recv_time not in self.objqueue:
                        self.objqueue[recv_time] = []
                    self.objqueue[recv_time].append((sender.id, a, obj))

    def knock_offline_random(self, n):
        ko = {}
        while len(ko) < n:
            c = random.choice(self.agents)
            ko[c.id] = c
        for c in ko.values():
            self.peers[c.id] = []
        for a in self.agents:
            self.peers[a.id] = [x for x in self.peers[a.id] if x.id not in ko]

    def partition(self):
        a = {}
        while len(a) < len(self.agents) / 2:
            c = random.choice(self.agents)
            a[c.id] = c
        for c in self.agents:
            if c.id in a:
                self.peers[c.id] = [x for x in self.peers[c.id] if x.id in a]
            else:
                self.peers[c.id] = [x for x in self.peers[c.id] if x.id not in a]

    @property
    def now(self):
        return time.time()


def normal_distribution(mean, standev):
    def f():
        return int(random.normalvariate(mean, standev))

    return f


def exponential_distribution(mean):
    def f():
        total = 0
        while 1:
            total += 1
            if not random.randrange(32):
                break
        return int(total * 0.03125 * mean)

    return f


def convolve(*args):
    def f():
        total = 0
        for arg in args:
            total += arg()
        return total

    return f


def transform(dist, xformer):
    def f():
        return xformer(dist())

    return f


class SimPyNetworkSimulator(NetworkSimulatorBase):

    start_time = 0

    def __init__(self, latency=50, agents=[], reliability=0.9, broadcast_success_rate=1.0):
        import simpy
        NetworkSimulatorBase.__init__(self, latency, agents, reliability, broadcast_success_rate)
        self.simenv = simpy.Environment()

    @property
    def now(self):
        return self.simenv.now

    def tick_loop(self, agent, tick_delay):
        ASYNC_CLOCKS = True
        if ASYNC_CLOCKS:
            deviation = id(self) % 1000  # ms
            yield self.simenv.timeout(deviation / 1000.)

        while True:
            yield self.simenv.timeout(tick_delay)
            # DEBUG('ticking agent', at=self.now, id=agent.id)
            agent.tick()

    def run(self, seconds, sleep=0):
        self.simenv._queue = []
        assert len(self.agents) < 20
        for a in self.agents:
            self.simenv.process(self.tick_loop(a, sleep))
        self.simenv.run(until=self.now + seconds)

    def moo(self):
        print 7

    def receive_later(self, sender_id, recipient, obj):
        print 4
        delay = self.latency_distribution_sample()
        print 5, delay
        yield self.simenv.timeout(delay)
        # raise Exception("cow")
        # DEBUG('receiving message', at=self.now, id=agent.id)
        # recipient.on_receive(obj, sender_id)

    def broadcast(self, sender, obj):
        assert isinstance(obj, (str, bytes))
        print 1
        if random.random() < self.broadcast_success_rate:
            print 2
            for p in self.peers[sender.id]:
                print 3
                self.moo()
                self.receive_later(sender.id, p, obj)
                print 3.1

    def send_to_one(self, sender, obj):
        assert isinstance(obj, (str, bytes))
        if random.random() < self.broadcast_success_rate:
            p = random.choice(self.peers[sender.id])
            self.receive_later(sender.id, p, obj)

    def direct_send(self, sender, to_id, obj):
        if random.random() < self.broadcast_success_rate * self.reliability:
            for p in self.agents:
                if p.id == to_id:
                    self.receive_later(sender.id, p, obj)


#NetworkSimulator = NetworkSimulatorBase
#NetworkSimulator = SimPyNetworkSimulator


import sys
import random
import copy
import six
import rlp
import gevent

from devp2p.crypto import (
    sha3,
    privtopub as privtopub_raw,
)
from devp2p.app import BaseApp
from devp2p.protocol import BaseProtocol
from devp2p.service import WiredService
from devp2p.utils import (
    colors,
    COLOR_END,
    host_port_pubkey_to_uri,
    update_config_with_defaults,
)
from devp2p import app_helper

import ethereum.slogging as slogging
from ethereum.guardian import NetworkMessage


#slogging.configure(config_string=':debug,p2p.discovery:info')
slogging.configure(config_string=':info,p2p.discovery:info')
logger = slogging.get_logger('guardian')

_nonce = 0


#
# Protocol
#
class GuardianProtocol(BaseProtocol):
    protocol_id = 1
    network_id = 0
    max_cmd_id = 1  # Actually max id is 0, but 0 is the special value.
    name = 'guardian'
    version = 1

    def __init__(self, peer, service):
        # required by P2PProtocol
        self.config = peer.config
        BaseProtocol.__init__(self, peer, service)

    class network_message(BaseProtocol.command):
        """
        A guardian network message
        """
        cmd_id = 0

        structure = [
            ('network_message', NetworkMessage)
        ]

#
#  Service
#
class GuardianService(WiredService):

    # required by BaseService
    name = 'guardianservice'
    default_config = {
        'guardianservice': {
            'num_participants': 1,
        }
    }

    # required by WiredService
    wire_protocol = GuardianProtocol

    def __init__(self, app):
        self.config = app.config
        self.address = privtopub_raw(self.config['node']['privkey_hex'].decode('hex'))
        super(GuardianService, self).__init__(app)

    def log(self, text, **kargs):
        node_num = self.config['node_num']
        msg = ' '.join([
            colors[node_num % len(colors)],
            "NODE%d" % node_num,
            text,
            (' %r' % kargs if kargs else ''),
            COLOR_END])
        logger.debug(msg)

    def broadcast(self, obj, origin=None):
        fmap = {NetworkMessage: 'network_message'}
        self.log('broadcasting', obj=obj)
        bcast = self.app.services.peermanager.broadcast
        bcast(GuardianProtocol, fmap[type(obj)], args=(obj,),
              exclude_peers=[origin.peer] if origin else [])

    def on_wire_protocol_stop(self, proto):
        assert isinstance(proto, self.wire_protocol)
        self.log('----------------------------------')
        self.log('on_wire_protocol_stop', proto=proto)

    def on_wire_protocol_start(self, proto):
        self.log('----------------------------------')
        self.log('on_wire_protocol_start', proto=proto, peers=self.app.services.peermanager.peers)
        assert isinstance(proto, self.wire_protocol)
        # register callbacks
        proto.receive_network_message_callbacks.append(self.on_receive_network_message)

    def on_receive_network_message(self, proto, network_message):
        assert isinstance(network_message, NetworkMessage)
        assert isinstance(proto, self.wire_protocol)
        self.log('----------------------------------')
        self.log('on_receive network_message', network_message=network_message, proto=proto)
        agent = self.app.services.guardianservice.config['guardianservice']['agent']
        lookup_fn = self.app.services.guardianservice.config['guardianservice']['lookup_fn']
        other_agent_id = lookup_fn(proto.peer.remote_pubkey)
        agent.on_receive(rlp.encode(network_message), other_agent_id)

    def send_network_message(self, typ, args):
        # without this we hit a race condition between our nodes.
        gevent.sleep(random.random())
        network_message = NetworkMessage(typ=typ, args=args)
        self.log('----------------------------------')
        self.log('sending network_message', network_message=network_message)
        self.broadcast(network_message)


#
#  App
#
guardian_client_name = "guardianapp"
guardian_version = '0.1'
guardian_client_version = ''.join((
    guardian_version,
    sys.platform,
    'py{:d}.{:d}.{:d}'.format(*sys.version_info[:3]),
))
guardian_client_version_string = '{:s}/v{:s}'.format(
    guardian_client_name,
    guardian_client_version,
)

guardian_default_config = copy.deepcopy(BaseApp.default_config)
guardian_default_config.update({
    'client_version_string': guardian_client_version_string,
    'post_app_start_callback': None,
})


class GuardianApp(BaseApp):
    client_name = guardian_client_name
    version = guardian_version
    client_version = guardian_client_version
    client_version_string = guardian_client_version_string

    default_config = guardian_default_config


from devp2p import app_helper
from devp2p import peermanager
from devp2p.service import BaseService
from devp2p.discovery import NodeDiscovery


class DevP2PNetwork(NetworkSimulatorBase):

    start_time = time.time()

    def __init__(self, agents=None, seed=0, min_peers=2, max_peers=5, random_port=False):
        self.agents = agents or []

        # copy/paste from devp2p.app_helper, not sure if this gevent config is
        # necessary.
        gevent.get_hub().SYSTEM_ERROR = BaseException
        if random_port:
            self.base_port = random.randint(10000, 60000)
        else:
            self.base_port = 29870

        # setup the bootstrap node (node0) enode
        self.bootstrap_node_privkey = app_helper.mk_privkey('%d:udp:%d' % (seed, 0))
        self.bootstrap_node_pubkey = privtopub_raw(self.bootstrap_node_privkey)
        self.enode = host_port_pubkey_to_uri(b'0.0.0.0', self.base_port, self.bootstrap_node_pubkey)

        services = [NodeDiscovery, peermanager.PeerManager, GuardianService]

        # prepare config
        base_config = dict()
        for s in services:
            update_config_with_defaults(base_config, s.default_config)

        bootstrap_nodes = [self.enode]

        base_config['seed'] = seed
        base_config['base_port'] = self.base_port
        base_config['num_nodes'] = len(self.agents)
        base_config['min_peers'] = min_peers
        base_config['max_peers'] = max_peers

        public_key_to_agent_id = {}

        base_config['guardianservice']['lookup_fn'] = public_key_to_agent_id.__getitem__

        self.base_config = base_config

        # prepare apps
        self.apps = {}
        for idx, agent in enumerate(self.agents):
            base_config['discovery']['bootstrap_nodes'] = bootstrap_nodes
            app = app_helper.create_app(idx, self.base_config, services, GuardianApp)
            app.config['guardianservice']['agent'] = agent
            enode = host_port_pubkey_to_uri(
                b'0.0.0.0',
                app.config['discovery']['listen_port'],
                app.config['node']['id'],
            )
            public_key_to_agent_id[app.config['node']['id']] = agent.id
            bootstrap_nodes.append(enode)
            if len(bootstrap_nodes) > 4:
                bootstrap_nodes = random.sample(bootstrap_nodes, 4)
            self.apps[agent.id] = app

    def start(self):
        for app in self.apps.values():
            app.start()
            gevent.sleep(random.random())
            if app.config['post_app_start_callback'] is not None:
                app.config['post_app_start_callback'](app)

    def join(self):
        # wait for apps to finish
        for app in self.apps.values():
            app.join()

    def stop(self):
        # finally stop
        for app in self.apps.values():
            app.stop()

    def generate_peers(self, *args, **kwargs):
        raise ValueError("DevP2PNetwork does not generate_peers")
    #def generate_peers(self, num_peers=5):
    #    self.peers = {}
    #    for a in self.agents:
    #        p = []
    #        while len(p) <= num_peers // 2:
    #            p.append(random.choice(self.agents))
    #            if p[-1] == a:
    #                p.pop()
    #        self.peers[a.id] = list(set(self.peers.get(a.id, []) + p))
    #        for peer in p:
    #            self.peers[peer.id] = list(set(self.peers.get(peer.id, []) + [a]))


    def tick(self, *args, **kwargs):
        raise ValueError("DevP2PNetwork does not tick")
    #def tick(self):
    #    if self.time in self.objqueue:
    #        for sender_id, recipient, obj in self.objqueue[self.time]:
    #            if random.random() < self.reliability:
    #                recipient.on_receive(obj, sender_id)
    #        del self.objqueue[self.time]
    #    for a in self.agents:
    #        a.tick()
    #    self.time += 1


    def run(self, seconds, sleep=0):
        start_time = time.time()
        while time.time() < start_time + seconds:
            for agent in self.agents:
                gevent.sleep(random.random())
                agent.tick()

    def broadcast(self, sender, obj):
        assert isinstance(obj, (str, bytes))
        gevent.sleep(random.random())
        app = self.apps[sender.id]
        network_message = rlp.decode(obj, NetworkMessage)
        bcast = app.services.peermanager.broadcast
        bcast(
            GuardianProtocol,
            'network_message',
            args=(network_message,),
            exclude_peers=[],
        )

        #if random.random() < self.broadcast_success_rate:
        #    for p in self.peers[sender.id]:
        #        recv_time = self.time + self.latency_distribution_sample()
        #        if recv_time not in self.objqueue:
        #            self.objqueue[recv_time] = []
        #        self.objqueue[recv_time].append((sender.id, p, obj))

    def send_to_one(self, sender, obj):
        assert isinstance(obj, (str, bytes))

        app = self.apps[sender.id]
        peer = random.choice(app.services.peermanager.peers)
        to_id = app.config['guardianservice']['lookup_fn'](peer.remote_pubkey)

        self.direct_send(sender, to_id, obj)

    def direct_send(self, sender, to_id, obj):
        app = self.apps[sender.id]
        lookup_fn = app.config['guardianservice']['lookup_fn']

        to_peer = None

        for peer in app.services.peermanager.peers:
            if lookup_fn(peer.remote_pubkey) == to_id:
                to_peer = peer
                break

        if to_peer is None:
            import ipdb; ipdb.set_trace()
            raise ValueError("Not connected to the provided agent")

        proto = to_peer.protocols[GuardianProtocol]
        proto.send_network_message(rlp.decode(obj, NetworkMessage))

    def knock_offline_random(self, n):
        # TODO: how to do this with a devp2p network?
        raise NotImplementedError("Not Implemented")

    def partition(self):
        # TODO: how to do this with a devp2p network?
        raise NotImplementedError("Not Implemented")


NetworkSimulator = DevP2PNetwork
