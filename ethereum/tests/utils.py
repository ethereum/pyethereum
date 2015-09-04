# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# pyethereum is free software: you can redistribute it and/or modify it
# under the terms of the The MIT License


"""Utilities used by more than one test."""


import json
import os
import tempfile
from ethereum.db import DB as DB
from ethereum.config import Env
__TESTDATADIR = "../tests"

tempdir = tempfile.mktemp()


def load_test_data(fname):
    return json.loads(open(os.path.join(__TESTDATADIR, fname)).read())


def new_db():
    return DB()


def new_env():
    return Env(new_db())
