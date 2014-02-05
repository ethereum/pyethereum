# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# pyethereum is free software: you can redistribute it and/or modify it
# under the terms of the The MIT License


"""Tests related to the trie.Trie class."""


import json
import os
import trie


class TestTrie:
    __TESTDATADIR = "../tests"

    def _load_test_data(self):
        return json.loads(
            open(os.path.join(self.__TESTDATADIR, 'trietest.txt')).read())

    def test_trie(self, tmpdir):
        db = tmpdir.ensure("trie-db", dir=True)
        t0 = trie.Trie(db.strpath)
        tdata = self._load_test_data()
        for tdatum in tdata:
            inputs = tdatum["inputs"]
            expected = tdatum["expectation"]
            for k, v in inputs.items():
                t0.update(k, v)
            actual = t0.root.encode('hex')
            assert expected == actual
