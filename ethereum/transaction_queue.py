import heapq
heapq.heaptop = lambda x: x[0]
PRIO_INFINITY = -2**100

class TransactionQueue():

    def __init__(self):
        self.txs = []
        self.aside = []
        self.last_max_gas = 2**100

    def add_transaction(self, tx, force=False):
        prio = PRIO_INFINITY if force else -tx.gasprice
        heapq.heappush(self.txs, (prio, tx))

    def pop_transaction(self, max_gas=9999999999, max_seek_depth=16, min_gasprice=0):
        while len(self.aside) and max_gas >= heapq.heaptop(self.aside)[0]:
            tx = heapq.heappop(self.aside)[1]
            heapq.heappush(self.txs, (-tx.gasprice, tx))
        for i in range(min(len(self.txs), max_seek_depth)):
            prio, tx = heapq.heaptop(self.txs)
            if tx.startgas > max_gas:
                heapq.heappop(self.txs)
                heapq.heappush(self.aside, (tx.startgas, tx))
            elif tx.gasprice >= min_gasprice or prio == PRIO_INFINITY:
                heapq.heappop(self.txs)
                return tx
            else:
                return None
        return None


def test():
    from ethereum.transactions import Transaction
    def tx(s, g):
        return Transaction(nonce=0, startgas=s, gasprice=g,
                           value=0, data='', to='\x35' * 20)
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
        q.add_transaction(tx(param[0], param[1]))
    # Attempt pops from queue
    for (maxgas, expected_s, expected_g) in operations:
        tx = q.pop_transaction(max_gas=maxgas)
        if tx:
            assert (tx.startgas, tx.gasprice) == (expected_s, expected_g)
        else:
            assert expected_s is expected_g is None
    print 'Test successful'
