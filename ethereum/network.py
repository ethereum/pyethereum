import gevent
import gevent.queue
from collections import namedtuple
import random, time
import slogging


TICK = ('tick')
GENESIS_STATE = {}


a_log = slogging.getLogger('sim.agent')


class DummyAgent(object):

    def __init__(self, genesis_state, key):
        self.genesis_state = genesis_state
        self.key = key
        self.node = None  # maintained by the Node

    def on_tick(self):
        """Agent.on_tick() is called whenever Node.tick() is triggered.
        Agent *can* manipulate it's node's *next* tick-cycle duration with
        returning a number.

        return: next tick duration or None (to keep current duration)
        """
        # now decide what we want to do
        if random.random() > .5:
            self.node.broadcast("lucky tick @agent[{}]".format(self.key))
        # return 1

    def handle(self, sender, msg):
        """Agent.handle() is called whenever a message is received.

        sender: the id of the sending network Node
        msg: the msg string
        """
        a_log.debug("received", agent=self.key, msg_=msg, from_=sender)
        if not msg.startswith('poke'):
            self.node.send_to_one("poke from [{}]".format(self.key))


net_log = slogging.getLogger('sim.net')


class NetworkSimulator(object):

    def __init__(self,
                 num_agents=5,
                 reliability=0.9,
                 broadcast_success_rate=1.0,
                 time_scaling=1.0,
                 latency=50
                 ):
        """
        reliability: global reliability
        time_scaling: scale all time delays by a factor
        """
        self.nodes = []
        self.time = 0
        self.reliability = reliability
        self.broadcast_success_rate = broadcast_success_rate
        self.time_sleeping = 0
        self.time_running = 0
        self.sleepdebt = 0
        self.time_scaling = time_scaling
        self.latency_distribution_sample = transform(
            normal_distribution(latency, (latency * 2) // 5),
            lambda x: max(x, 0))
        for i in range(num_agents):
            self.create_node(i)

    def start(self):
        for node in self.nodes:
            node.tick()
            node.start()
        while True:
            gevent.sleep(0)

    def create_node(self, id_, agent_cls=DummyAgent):
        agent = agent_cls(GENESIS_STATE, id_)
        self.nodes.append(Node(self, agent, reliability=self.reliability))

    def knock_offline_random(self, n):
        offline = 0
        while offline < n:
            node = random.choice(self.nodes)
            if not node.offline:
                node.offline = True
                offline += 1

    def partition(self, split=0.5):
        """Separate the network by `split / 1 - split` and disconnect
        the left from the right partition.

        To undo, call partition(split=1.0).
        """
        left = []
        while len(left) < len(self.nodes) * split:
            left.append(random.choice(self.nodes))
            left = list(set(left))
        right = [node for node in self.nodes if not node in left]

        assert len(left) + len(right) == len(self.nodes)

        for node in left:
            node.connect_nodes(left)
        for node in right:
            node.connect_nodes(right)


n_log = slogging.getLogger('sim.node')


class Node(object):

    def __init__(self, network, agent, reliability=0.9, ticktime=1.0):
        """
        network: the global network
        agent: the agent behind the network node
        reliability: node-local reliability
        """
        self.peers = []
        self.mailbox = gevent.queue.Queue()
        self.agent = agent
        self.agent.node = self
        self.network = network
        self.reliability = reliability
        self.ticktime = ticktime
        self.offline = False

    def start(self):
        self.connect_nodes(self.network.nodes)
        gevent.spawn(self.run)

    def connect_nodes(self, nodes):
        self.peers = list(set(nodes) - set([self]))
        random.shuffle(self.peers)

    def run(self):
        """The Node's main-loop. It checks the mailbox for incoming
        messages and either:
            - reschedules the next `TICK` or
            - calls `self.agent.handle(message)`
        """
        while True:
            try:
                msg = self.mailbox.get(timeout=.1)
                if msg == TICK:
                    n_log.debug("mailbox: tick received", receiver=self)
                    gevent.spawn_later(self.ticktime * self.network.time_scaling, self.tick)
                else:
                    if not self.offline:
                        n_log.debug("mailbox: msg received", msg_=msg, receiver=self)
                        self.agent.handle(*msg)
            except gevent.queue.Empty:
                pass

    def tick(self):
        """call agents `tick()` and schedule retrigger
        """
        # agent *can* return next ticktime
        self.ticktime = self.agent.on_tick() or self.ticktime
        # enqueue next tick
        self.mailbox.put(TICK)

    def do_eventually(self, fun, *args):
        """maybe spawn `fun`ction with `*args` and latency
        """
        if random.random() < self.network.broadcast_success_rate * self.reliability:
            gevent.spawn_later(self.network.latency_distribution_sample() * self.network.time_scaling, fun, *args)
        else:
            n_log.debug("skipped", fun=fun, args_=args)

    def broadcast(self, msg):
        """send `msg` to all peers
        """
        for recipient in self.peers:
            self.send(recipient, msg)

    def send_to_one(self, msg):
        """send `msg` to one (random) peer
        """
        recipient = random.choice(self.peers)
        self.send(recipient, msg)

    def direct_send(self, msg, recipient):
        """send `msg` to `recipient`
        """
        self.send(recipient, msg)

    def send(self, recipient, msg):
        """wrap `msg` in an envelope and send to `recipient`.
        """
        envelope = namedtuple('envelope', ['sender', 'msg'])
        self.do_eventually(recipient.mailbox.put, envelope(self, msg))

    def __repr__(self):
        return "<Node {}>".format(id(self))


# A network simulator
class NetworkSimulator_OLD():

    def __init__(self, latency=50, agents=[], reliability=0.9, broadcast_success_rate=1.0):
        self.agents = agents
        self.latency_distribution_sample = transform(normal_distribution(latency, (latency * 2) // 5), lambda x: max(x, 0))
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


if __name__ == "__main__":
    slogging.configure_logging(":DEBUG")

    import gevent.monkey
    gevent.monkey.patch_all()

    net = NetworkSimulator()

    import IPython
    IPython.start_ipython(user_ns=dict(net=net))

    # net.start()
