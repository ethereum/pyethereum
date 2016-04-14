#!/usr/bin/env python
import sys
import json
from collections import defaultdict


def read_pythons(fn='pylog.jsons'):
    with open(fn) as f:
        lines = [json.loads(line) for line in f.readlines()]
    blocks = defaultdict(list)
    bnum = 0
    for l in lines:
        if l['pc'] == 0:
            bnum += 1
        # remove py slogging specifics:
        l.pop('event')
        l.pop('level')
        blocks[bnum].append(l)
    return blocks

if __name__ == '__main__':
    pyblocks = read_pythons()
    blocknum = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    print json.dumps(pyblocks[blocknum], indent=2)
