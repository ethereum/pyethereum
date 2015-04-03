# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# pyethereum is free software: you can redistribute it and/or modify it
# under the terms of the The MIT License


"""Utilities used by more than one test."""


import json
import os
import tempfile
import ethereum.utils as utils
import ethereum.testutils as testutils
from ethereum.db import DB as DB
__TESTDATADIR = "../tests"

tempdir = tempfile.mktemp()


def load_test_data(fname):
    return json.loads(open(os.path.join(__TESTDATADIR, fname)).read())


def new_db():
    return DB(utils.db_path(tempfile.mktemp()))

# def set_db(name=''):
#     if name:
#         utils.data_dir.set(os.path.join(tempdir, name))
#     else:
#         utils.data_dir.set(tempfile.mktemp())
