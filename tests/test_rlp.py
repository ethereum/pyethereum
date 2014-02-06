# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# pyethereum is free software: you can redistribute it and/or modify it
# under the terms of the The MIT License


"""Tests related to the trie.Trie class."""


import rlp
import utils


class TestRLP:
    def test_encodings(self):
        tdata = utils.load_test_data("rlptest.txt")
        for sample, expected in tdata:
            actual = rlp.encode(sample).encode('hex')
            assert expected == actual, (
                "RLPEncode mismatch for sample '%s'; expected='%s' - "
                "actual='%s'" % (sample, expected, actual))

    def test_decoding(self):
        tdata = utils.load_test_data("rlptest.txt")
        for expected, sample in tdata:
            actual = rlp.decode(sample.decode('hex'))
            assert expected == actual, (
                "RLPDecode mismatch for sample '%s'; expected='%s' - "
                "actual='%s'" % (sample, expected, actual))
