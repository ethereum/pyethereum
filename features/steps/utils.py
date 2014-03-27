import random  # noqa
import math  # noqa
from contextlib import contextmanager
import parse


@parse.with_pattern(r"[\s\S]+")
def parse_py(text):
    exec("val = {0}".format(text))
    return val  # noqa


@contextmanager
def AssertException(e):
    caught = False
    try:
        yield
    except e:
        caught = True
    assert caught
