#!/usr/bin/env python
import sys
import json
from collections import defaultdict


def read_pythons(fn='pylog.jsons'):
    with open(fn) as f:
        lines = [json.loads(line) for line in f.readlines()]
    txs = list()
    for l in lines:
        if l['event'] != "eth.vm.op.vm":
            continue
        # remove py slogging specifics:
        l.pop('event')
        l.pop('level')
        txs.append(l)
    return read_transactions(txs)


def read_transactions(traces):
    txs = defaultdict(list)
    tx_num = 0
    for step in traces:
        if step['pc'] == 0:
            tx_num += 1
        txs[tx_num].append(step)
    return txs


if __name__ == '__main__':
    pyblocks = read_pythons()
    txnum = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    print json.dumps(pyblocks[txnum], indent=2)
