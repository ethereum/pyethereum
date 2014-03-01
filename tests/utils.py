# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# pyethereum is free software: you can redistribute it and/or modify it
# under the terms of the The MIT License


"""Utilities used by more than one test."""


import json
import os

__TESTDATADIR = "../tests"
assert os.path.exists(__TESTDATADIR), ('Expecting test data at', __TESTDATADIR, \
	'You need to clone the test data repository which can be found here: https://github.com/ethereum/tests')

def load_test_data(fname):
    return json.loads(open(os.path.join(__TESTDATADIR, fname)).read())
