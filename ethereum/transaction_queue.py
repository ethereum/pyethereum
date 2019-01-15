import heapq
heapq.heaptop = lambda x: x[0]
PRIO_INFINITY = -2**100


class OrderableTx(object):

    def __init__(self, prio, counter, tx):
        self.prio = prio
        self.counter = counter
        self.tx = tx

    def __lt__(self, other):
        if self.prio < other.prio:
            return True
        elif self.prio == other.prio:
            return self.counter < other.counter
        else:
            return False


class TransactionQueue():

    def __init__(self):
        self.counter = 0
        self.txs = []
        self.aside = []

    def __len__(self):
        return len(self.txs)

    def add_transaction(self, tx, force=False):
        prio = PRIO_INFINITY if force else -tx.gasprice
        heapq.heappush(self.txs, OrderableTx(prio, self.counter, tx))
        self.counter += 1

    def pop_transaction(self, max_gas=9999999999,
                        max_seek_depth=16, min_gasprice=0):
        while len(self.aside) and max_gas >= heapq.heaptop(self.aside).prio:
            item = heapq.heappop(self.aside)
            item.prio = -item.tx.gasprice
            heapq.heappush(self.txs, item)
        for i in range(min(len(self.txs), max_seek_depth)):
            item = heapq.heaptop(self.txs)
            if item.tx.startgas > max_gas:
                heapq.heappop(self.txs)
                item.prio = item.tx.startgas
                heapq.heappush(self.aside, item)
            elif item.tx.gasprice >= min_gasprice or item.prio == PRIO_INFINITY:
                heapq.heappop(self.txs)
                return item.tx
            else:
                return None
        return None

    def peek(self, num=None):
        if num:
            return self.txs[0:num]
        else:
            return self.txs

    def diff(self, txs):
        remove_hashes = [tx.hash for tx in txs]
        keep = [item for item in self.txs if item.tx.hash not in remove_hashes]
        q = TransactionQueue()
        q.txs = keep
        return q


def make_test_tx(s=100000, g=50, data='', nonce=0):
    from ethereum.transactions import Transaction
    return Transaction(nonce=nonce, startgas=s, gasprice=g,
                       value=0, data=data, to=b'\x35' * 20)


def test():
    q = TransactionQueue()
    # (startgas, gasprice) pairs
    params = [(100000, 81), (50000, 74), (40000, 65),
              (60000, 39), (30000, 50), (30000, 50),
              (30000, 80)]
    # (maxgas, expected_startgas, expected_gasprice) triplets
    operations = [(999999, 100000, 81),
                  (999999, 30000, 80),
                  (30000, 30000, 50),
                  (29000, None, None),
                  (30000, 30000, 50),
                  (30000, None, None),
                  (999999, 50000, 74)]
    # Add transactions to queue
    for param in params:
        q.add_transaction(make_test_tx(s=param[0], g=param[1]))
    # Attempt pops from queue
    for (maxgas, expected_s, expected_g) in operations:
        tx = q.pop_transaction(max_gas=maxgas)
        if tx:
            assert (tx.startgas, tx.gasprice) == (expected_s, expected_g)
        else:
            assert expected_s is expected_g is None
    print('Test successful')


def test_diff():
    tx1 = make_test_tx(data='foo')
    tx2 = make_test_tx(data='bar')
    tx3 = make_test_tx(data='baz')
    tx4 = make_test_tx(data='foobar')
    q1 = TransactionQueue()
    for tx in [tx1, tx2, tx3, tx4]:
        q1.add_transaction(tx)
    q2 = q1.diff([tx2])
    assert len(q2) == 3
    assert tx1 in [item.tx for item in q2.txs]
    assert tx3 in [item.tx for item in q2.txs]
    assert tx4 in [item.tx for item in q2.txs]

    q3 = q2.diff([tx4])
    assert len(q3) == 2
    assert tx1 in [item.tx for item in q3.txs]
    assert tx3 in [item.tx for item in q3.txs]


def test_orderable_tx():
    assert OrderableTx(-1, 0, None) < OrderableTx(0, 0, None)
    assert OrderableTx(-1, 0, None) < OrderableTx(-1, 1, None)
    assert not OrderableTx(1, 0, None) < OrderableTx(-1, 0, None)
    assert not OrderableTx(1, 1, None) < OrderableTx(-1, 0, None)


def test_ordering_for_same_prio():
    q = TransactionQueue()
    count = 10
    # Add <count> transactions to the queue, all with the same
    # startgas/gasprice but with sequential nonces.
    for i in range(count):
        q.add_transaction(make_test_tx(nonce=i))

    expected_nonce_order = range(count)
    nonces = []
    for i in range(count):
        tx = q.pop_transaction()
        nonces.append(tx.nonce)
    # Since they have the same gasprice they should have the same priority and
    # thus be popped in the order they were inserted.
    assert nonces == expected_nonce_order
