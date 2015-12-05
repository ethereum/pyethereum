import random, sys, time

# A network simulator

class NetworkSimulator():

    def __init__(self, latency=50, agents=[], reliability=0.9, broadcast_success_rate=1.0):
        self.agents = agents
        self.latency_distribution_sample = transform(normal_distribution(latency, (latency * 2) // 5), lambda x: max(x, 0))
        self.time = 0
        self.objqueue = {}
        self.peers = {}
        self.reliability = reliability
        self.broadcast_success_rate = broadcast_success_rate

    def generate_peers(self, num_peers=5):
        self.peers = {}
        for a in self.agents:
            p = []
            while len(p) <= num_peers // 2:
                p.append(random.choice(self.agents))
                if p[-1] == a:
                    p.pop()
            self.peers[a.id] = self.peers.get(a.id, []) + p
            for peer in p:
                self.peers[peer.id] = self.peers.get(peer.id, []) + [a]

    def tick(self):
        if self.time in self.objqueue:
            for sender_id, recipient, obj in self.objqueue[self.time]:
                if random.random() < self.reliability:
                    recipient.on_receive(obj, sender_id)
            del self.objqueue[self.time]
        for a in self.agents:
            a.tick()
        self.time += 1

    def run(self, steps, sleep=0):
        for i in range(steps):
            a = time.time()
            self.tick()
            timedelta = time.time() - a
            print 'Tick finished in: %.2f' % timedelta
            if sleep > timedelta:
                time.sleep(sleep - timedelta)

    def broadcast(self, sender, obj):
        assert isinstance(obj, (str, bytes))
        if random.random() < self.broadcast_success_rate:
            for p in self.peers[sender.id]:
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
