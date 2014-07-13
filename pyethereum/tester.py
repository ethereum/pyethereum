import pyethereum
import time
serpent = None

u = pyethereum.utils
t = pyethereum.transactions
b = pyethereum.blocks
pb = pyethereum.processblock

accounts = []
keys = []

for i in range(10):
    keys.append(u.sha3(str(i)))
    accounts.append(u.privtoaddr(keys[-1]))

k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = accounts[:10]


class state():
    def __init__(self, num_accounts=len(keys)):
        global serpent
        if not serpent:
            serpent = __import__('serpent')
        o = {}
        for i in range(num_accounts):
            o[accounts[i]] = 10**18
        self.block = b.genesis(o)
        self.block.coinbase = a0
        self.mine(1)

    def contract(self, code, sender=k0, endowment=0):
        sendnonce = self.block.get_nonce(u.privtoaddr(sender))
        evm = serpent.compile(code)
        tx = t.contract(sendnonce, 1, 100000, endowment, evm)
        tx.sign(sender)
        (s, a) = pb.apply_transaction(self.block, tx)
        if not s:
            raise Exception("Contract creation failed")
        return a

    def send(self, sender, to, value, data=[]):
        sendnonce = self.block.get_nonce(u.privtoaddr(sender))
        evmdata = serpent.encode_datalist(data)
        tx = t.Transaction(sendnonce, 1, 100000, to, value, evmdata)
        tx.sign(sender)
        (s, r) = pb.apply_transaction(self.block, tx)
        if not s:
            raise Exception("Transaction failed")
        o = serpent.decode_datalist(r)
        return map(lambda x: x-2**256 if x > 2**255 else x, o)

    def mine(self, n=1, coinbase=a0):
        for i in range(n):
            self.block.finalize()
            t = (self.block.timestamp or int(time.time())) + 60
            self.block = b.Block.init_from_parent(self.block, coinbase, '', t)

    def snapshot(self):
        return self.block.serialize()

    def revert(self, data):
        self.block = b.Block.deserialize(data)


def enable_debug():
    pb.enable_debug()


def disable_debug():
    pb.disable_debug()
