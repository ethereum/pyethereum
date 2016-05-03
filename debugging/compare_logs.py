#!/usr/bin/env python
"""
./compare_logs.py

Usage:
    ./compare_logs.py -p <pyfile> [-t <txnum>] [-g <gofile>]
    ./compare_logs.py stepwise -p <pyfile> [-t <txnum>] [-g <gofile>]

Help:
    -p <pyfile>     The filename for the pyethapp trace file.
    -t <txnum>      Which tx to compare (default: 1).
    -g <gofile>     Optional: read this logfile for go trace.
"""
import json
from deepdiff import DeepDiff
from pprint import pprint
from print_pylog import read_pythons, read_transactions
from docopt import docopt


def read_geth(fn):
    with open(fn) as f:
        slogs = json.load(f)['result']['structLogs']
    return slogs


def print_stats(txs, num, name):
    print "{}-trace contains [{}] transactions".format(name, len(txs))
    print "{}-tx [{}] contains [{}] vm steps".format(name, num, len(txs[num]))


get = lambda l, idx, default: l[idx] if len(l) > idx else default

if __name__ == '__main__':
    options = docopt(__doc__)
    pytransactions = read_pythons(options['-p'])
    txnum = int(options['-t'] or '1')
    if '-g' in options and options['-g'] is not None:
        gofile = options['-g']
    else:
        gofile = "trace-{}.json".format(txnum)

    goblock = read_geth(gofile)

    gotransactions = read_transactions(goblock)

    print_stats(gotransactions, txnum, "go")
    print_stats(pytransactions, txnum, "py")

    print "diffing tx [{}]".format(txnum)

    go = py = None

    deltastep = 0

    def diff_(step, deltastep=0):
        print "diffing vm step [{}]".format(i)
        go = get(gotransactions[txnum], step, {})
        py = get(pytransactions[txnum], step + deltastep, {})
        return DeepDiff(go, py)

    if options['stepwise']:
        for i in range(max(len(gotransactions[txnum]), len(pytransactions[txnum]))):
            diff = diff_(i, deltastep)
            if len(diff):
                goop = get(gotransactions[txnum], i, {}).get('op')
                pyop = get(pytransactions[txnum], i, {}).get('op')
                if goop != pyop:
                    print "go: {} vs py: {}".format(goop, pyop)
                    print "trying with delta"
                    if not len(diff_(i, deltastep + 1)):
                        print "delta +1"
                        print "skipping py vm step[{}]; not in go:".format(i)
                        print json.dumps(pytransactions[txnum][i + deltastep], indent=2, sort_keys=True)
                        deltastep += 1
                        continue
                    elif not len(diff_(i, deltastep - 1)):
                        print "delta -1"
                        print "skipping go vm step[{}]; not in py:".format(i)
                        print json.dumps(gotransactions[txnum][i + deltastep], indent=2, sort_keys=True)
                        deltastep -= 1
                        continue
                    else:
                        print "step [{}] differs:".format(i)
                        pprint(diff)
            else:
                print "ok"
    else:
        pprint(DeepDiff(goblock, pytransactions[txnum]))
        print "diffed {} vs {}[{}]".format(gofile, options['-p'], txnum)
