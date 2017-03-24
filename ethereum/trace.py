# -*- coding: utf-8 -*-
from ethereum.config import Env
from ethereum.db import BaseDB
from ethereum import config


class Trace(object):
    def __init__(self, db):
        assert isinstance(db, BaseDB)
        self.db = db
        self.transactions = {}
	self.enabled = config.default_config['TRACE_TRANSACTIONS']
    def getTrace(self, tx_hash):
        if not self.enabled: raise Exception('Trace transaction is disabled!')
        if tx_hash in self.transactions:
            return self.transactions[tx_hash]
        else:
            raise Exception('Transaction not found!')
    def addTrace(self, tx_hash, tx_trace):
        if self.enabled:
            tx_hash = tx_hash.encode('hex')
            if tx_hash.lower()[:2] != "0x": tx_hash = "0x"+tx_hash
            self.transactions[tx_hash] = tx_trace
