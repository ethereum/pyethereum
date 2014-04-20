#!/usr/bin/env python
import sys
import re
import json
from pyethereum import pyethtool
import shlex

def smart_print(o):
    if isinstance(o, (list, dict)):
        try:
            print json.dumps(o)
        except:
            print o
    else:
        print o

def main():
    if len(sys.argv) == 1:
        # Shell
        while 1:
            cmdline = raw_input('> ')
            if cmdline in ['quit','exit']:
                break
            tokens = shlex.split(cmdline)
            cmd, args = tokens[0], tokens[1:]
            o = getattr(pyethtool, cmd)(*args)
            smart_print(o)

    else:
        cmd = sys.argv[2] if sys.argv[1][0] == '-' else sys.argv[1]
        if sys.argv[1] == '-s':
            args = re.findall(r'\S\S*', sys.stdin.read()) + sys.argv[3:]
        elif sys.argv[1] == '-B':
            args = [sys.stdin.read()] + sys.argv[3:]
        elif sys.argv[1] == '-b':
            args = [sys.stdin.read()[:-1]] + sys.argv[3:]  # remove trailing \n
        elif sys.argv[1] == '-j':
            args = [json.loads(sys.stdin.read())] + sys.argv[3:]
        elif sys.argv[1] == '-J':
            args = json.loads(sys.stdin.read()) + sys.argv[3:]
        else:
            cmd = sys.argv[1]
            args = sys.argv[2:]
        o = getattr(pyethtool, cmd)(*args)
        smart_print(o)



if __name__ == '__main__':
    main()
