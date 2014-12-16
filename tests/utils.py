# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# pyethereum is free software: you can redistribute it and/or modify it
# under the terms of the The MIT License


"""Utilities used by more than one test."""


import json
import os
import tempfile
import pyethereum.utils as utils
from pyethereum.db import DB as DB
from pyethereum.config import get_default_config as _get_default_config
__TESTDATADIR = "../tests"

tempdir = tempfile.mktemp()

def new_config():
    cfg = _get_default_config()
    cfg.set('misc', 'data_dir', tempfile.mktemp())

def load_test_data(fname):
    return json.loads(open(os.path.join(__TESTDATADIR, fname)).read())

def new_db():
    return DB(utils.db_path(tempfile.mktemp()))

# def set_db(name=''):
#     if name:
#         utils.data_dir.set(os.path.join(tempdir, name))
#     else:
#         utils.data_dir.set(tempfile.mktemp())
