#!/usr/bin/env python
"""
./compare_logs.py

Usage:
    ./compare_logs.py -p <pyfile> [-b <blocknum>] [-g <gofile>]

Help:
    -p <pyfile>     The filename for the pyethapp trace file.
    -b <blocknum>   Which block to compare (default: 1).
    -g <gofile>     Optional: read this logfile for go trace.
"""
import json
from deepdiff import DeepDiff
from pprint import pprint
from print_pylog import read_pythons
from docopt import docopt


def read_geth(fn):
    with open(fn) as f:
        slogs = json.load(f)['result']['structLogs']
    return slogs


if __name__ == '__main__':
    options = docopt(__doc__)
    print options
    pyblocks = read_pythons(options['-p'])
    assert len(pyblocks)
    blocknum = int(options['-b'] or '1')
    if '-g' in options and options['-g'] is not None:
        gofile = options['-g']
    else:
        gofile = "trace-{}.json".format(blocknum)

    goblock = read_geth(gofile)
    pprint(DeepDiff(goblock, pyblocks[blocknum]))
    print "diffed {} vs {}[{}]".format(gofile, options['-p'], blocknum)
