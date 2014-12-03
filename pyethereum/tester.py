import pyethereum
import shutil
import tempfile
import time
import logging
import sys
import spv

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

seed = 3**160


# Pseudo-RNG (deterministic for now for testing purposes)
def rand():
    global seed
    seed = pow(seed, 2, 2**512)
    return seed % 2**256


class state():
    def __init__(self, num_accounts=len(keys)):
        global serpent
        if not serpent:
            serpent = __import__('serpent')

        self.temp_data_dir = tempfile.mkdtemp()
        u.data_dir.set(self.temp_data_dir)

        o = {}
        for i in range(num_accounts):
            o[accounts[i]] = 10**24
        self.block = b.genesis(o)
        self.block.timestamp = 1410973349
        self.block.coinbase = a0

    def __del__(self):
        shutil.rmtree(self.temp_data_dir)

    def contract(self, code, sender=k0, endowment=0):
        evm = serpent.compile(code)
        return self.evm(evm, sender, endowment)

    def evm(self, evm, sender=k0, endowment=0):
        sendnonce = self.block.get_nonce(u.privtoaddr(sender))
        tx = t.contract(sendnonce, 1, gas_limit, endowment, evm)
        tx.sign(sender)
        (s, a) = pb.apply_transaction(self.block, tx)
        if not s:
            raise Exception("Contract creation failed")
        return a

    def send(self, sender, to, value, data=[], funid=None, abi=None):
        sendnonce = self.block.get_nonce(u.privtoaddr(sender))
        if funid is not None:
            evmdata = serpent.encode_abi(funid, *abi)
        else:
            evmdata = serpent.encode_datalist(*data)
        tx = t.Transaction(sendnonce, 1, gas_limit, to, value, evmdata)
        self.last_tx = tx
        tx.sign(sender)
        (s, r) = pb.apply_transaction(self.block, tx)
        if not s:
            raise Exception("Transaction failed")
        o = serpent.decode_datalist(r)
        return map(lambda x: x-2**256 if x >= 2**255 else x, o)

    def profile(self, sender, to, value, data=[], funid=None, abi=None):
        tm, g = time.time(), self.block.gas_used
        o = self.send(sender, to, value, data, funid, abi)
        intrinsic_gas_used = pb.GTXDATA * len(self.last_tx.data) + pb.GTXCOST
        return {
            "time": time.time() - tm,
            "gas": self.block.gas_used - g - intrinsic_gas_used,
            "output": o
        }

    def mkspv(self, sender, to, value, data=[], funid=None, abi=None):
        sendnonce = self.block.get_nonce(u.privtoaddr(sender))
        if funid is not None:
            evmdata = serpent.encode_abi(funid, *abi)
        else:
            evmdata = serpent.encode_datalist(*data)
        tx = t.Transaction(sendnonce, 1, gas_limit, to, value, evmdata)
        self.last_tx = tx
        tx.sign(sender)
        return spv.mk_transaction_spv_proof(self.block, tx)

    def verifyspv(self, sender, to, value, data=[],
                  funid=None, abi=None, proof=[]):
        sendnonce = self.block.get_nonce(u.privtoaddr(sender))
        if funid is not None:
            evmdata = serpent.encode_abi(funid, *abi)
        else:
            evmdata = serpent.encode_datalist(*data)
        tx = t.Transaction(sendnonce, 1, gas_limit, to, value, evmdata)
        self.last_tx = tx
        tx.sign(sender)
        return spv.verify_transaction_spv_proof(self.block, tx, proof)

    def trace(self, sender, to, value, data=[]):

        # collect debug output
        log = []

        def log_receiver(data):
            log.append(data)

        pb.pblogger.log_op = 1
        pb.pblogger.log_stack = 1
        pb.pblogger.log_memory = 1
        pb.pblogger.log_storage = 1
        pb.pblogger.listeners.append(log_receiver)
        self.send(sender, to, value, data)
        pb.pblogger.listeners.remove(log_receiver)
        return log
        
    def mine(self, n=1, coinbase=a0):
        for i in range(n):
            self.block.finalize()
            t = self.block.timestamp + 6 + rand() % 12
            self.block = b.Block.init_from_parent(self.block, coinbase, '', t)

    def snapshot(self):
        return self.block.serialize()

    def revert(self, data):
        self.block = b.Block.deserialize(data)


def enable_logging():
    logging.basicConfig(level=logging.DEBUG, format='%(message)s')
    pb.pblogger.log_apply_op = True
    pb.pblogger.log_stack = True
    pb.pblogger.log_op = True


gas_limit = 100000
