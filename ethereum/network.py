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


NetworkSimulator = NetworkSimulatorBase
#NetworkSimulator = SimPyNetworkSimulator
