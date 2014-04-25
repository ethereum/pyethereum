import sys
import os


def make_pyethereum_avail():
    ''' so pyethreum.package.module is available'''
    where = os.path.join(__file__, os.path.pardir, os.path.pardir)
    where = os.path.abspath(where)
    for path in sys.path:
        if os.path.abspath(path) == where:
            return
    sys.path.append(where)
