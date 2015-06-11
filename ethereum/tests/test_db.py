import itertools
import random
import pytest
from ethereum.db import _EphemDB
from rlp.utils import ascii_chr

random.seed(0)


def random_string(length):
    return b''.join([ascii_chr(random.randint(0, 255)) for _ in range(length)])


content = {random_string(lk): random_string(lv)
           for lk, lv in itertools.product([1, 32, 255], [0, 1, 32, 255])}
alt_content = {key: random_string(32) for key in content}


def test_ephem():
    db = _EphemDB()
    for key in content:
        assert key not in db
        with pytest.raises(KeyError):
            db.get(key)
    for key, value in content.items():
        db.put(key, value)
        assert key in db
        assert db.get(key) == value
    for key in content:
        db.put(key, alt_content[key])
        assert key in db
        assert db.get(key) == alt_content[key]
    for key, value in content.items():
        db.delete(key)
        assert key not in db
        with pytest.raises(KeyError):
            db.get(key)
