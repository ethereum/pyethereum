# -*- coding: utf-8 -*-
from ethereum.config import Env
from ethereum import config

class Trace(object):
    storages = {}
    transactions = {}
    enabled = None
    def __init__(self):
        self.enabled = config.default_config['TRACE_TRANSACTIONS']

    def getTrace(self, tx_hash):
        if not self.enabled: raise Exception('Trace transaction is disabled!')
        if tx_hash in self.transactions:
            return self.transactions[tx_hash]
        else:
            raise Exception('Transaction not found!')

    def addTrace(self, tx_hash, tx_trace):
        if self.enabled:
            if tx_hash.lower()[:2] != "0x": tx_hash = "0x"+tx_hash
            self.transactions[tx_hash] = tx_trace
            return True
        return False

    def addStorage(self, block_num, tx_hash, storage):
        if self.enabled:
            str = {}
            storage = storage.to_dict()
            for a in storage:
                str[a.encode('hex')] = storage[a].encode('hex')
            if not block_num in self.storages: self.storages[block_num] = []
            tmp = [tx_hash in i for i in self.storages[block_num]]
            if (True in tmp):
                self.storages[block_num][tmp.index(True)] = str
            else:
                self.storages[block_num].append({ tx_hash:str })
            return True
        return False

    def getStorage(self, block_num, tx_num, stor_start, stor_end, limit):
        # stor_start, stor_end, limit not yet implemented
        if self.enabled:
            if not block_num in self.storages: raise Exception('Block not found!')
            if not tx_num in self.storages[block_num]: raise Exception('TX not found!')
            return { "complete": True, "storage": self.storages[block_num][tx_num] }
        raise Exception('Trace is disabled!')
