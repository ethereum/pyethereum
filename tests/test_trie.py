# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# pyethereum is free software: you can redistribute it and/or modify it
# under the terms of the The MIT License


"""Tests related to the radix/merkle trees."""


import random
from pyethereum import trie
import utils


class TestTrie:
    def test_hashes(self, tmpdir):
        # `tmpdir` is a `py.path.local` object which offers `os.path` methods,
        # see http://pytest.org/latest/tmpdir.html for details.
        tdata = utils.load_test_data("trietest.txt")
        for tdatum in tdata:
            inputs = tdatum["inputs"]
            expected = tdatum["expectation"]

            # Prepare the Trie
            db = tmpdir.ensure("tdb-%s" % random.randrange(1000000), dir=True)
            t0 = trie.Trie(db.strpath)
            for k, v in inputs.items():
                t0.update(k, v)
            # The actual test
            actual = t0.root.encode('hex')
            assert expected == actual, (
                "inputs='%s', expected='%s', actual='%s'" %
                (inputs, expected, actual))
