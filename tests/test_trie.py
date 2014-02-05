# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# pyethereum is free software: you can redistribute it and/or modify it
# under the terms of the The MIT License


"""Tests related to the trie.Trie class."""


import random
import trie
import utils


class TestTrie:
    def _load_data(self, td_idx):
        # Load the test data
        tdata = utils.load_test_data("trietest.txt")
        tdatum = tdata[td_idx]
        inputs = tdatum["inputs"]
        expected = tdatum["expectation"]
        return (inputs, expected)

    def _test_hash(self, tmpdir, td_idx):
        # `tmpdir` is a `py.path.local` object which offers `os.path` methods,
        # see http://pytest.org/latest/tmpdir.html for details.
        inputs, expected = self._load_data(td_idx)
        # Prepare the Trie
        db = tmpdir.ensure("triedb-%s" % random.randrange(10000000), dir=True)
        t0 = trie.Trie(db.strpath)
        for k, v in inputs.items():
            t0.update(k, v)
        # The actual test
        actual = t0.root.encode('hex')
        assert expected == actual, (
            "\ninputs = '%s',\nhash = '%s'" % (inputs, actual))

    def test_trie1(self, tmpdir):
        self._test_hash(tmpdir, 0)

    def test_trie2(self, tmpdir):
        self._test_hash(tmpdir, -1)
