import random
import math
from contextlib import contextmanager
import parse
from behave import register_type

@parse.with_pattern(r"[\s\S]+")
def parse_py(text):
    exec("val = {0}".format(text))
    return val

register_type(Py=parse_py)

@contextmanager
def AssertException(e):
    caught = False
    try:
        yield
    except e:
        caught = True
    assert caught
