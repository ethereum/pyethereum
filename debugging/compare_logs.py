#!/usr/bin/env python
import sys
import json
from deepdiff import DeepDiff
from pprint import pprint
from print_pylog import read_pythons
# from __future__ import print_function


def read_geth(fn):
    with open(fn) as f:
        slogs = json.load(f)['result']['structLogs']
    return slogs


if __name__ == '__main__':
    pyblocks = read_pythons()
    blocknum = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    goblock = read_geth("trace-{}.json".format(blocknum))
    pprint(DeepDiff(goblock, pyblocks[blocknum]))
