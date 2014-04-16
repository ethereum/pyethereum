import random  # noqa
import math  # noqa
from contextlib import contextmanager
import parse

import mock


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


def instrument(func):
    instrumented = mock.MagicMock()
    instrumented.side_effect = lambda *args, **kwargs: func(*args, **kwargs)
    return instrumented
