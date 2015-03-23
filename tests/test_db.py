import itertools
import random
import tempfile
import pytest
from pyethereum.db import _EphemDB, _CodernityDB, _LevelDB
from pyethereum.utils import db_path
from rlp.utils import ascii_chr

random.seed(0)


def random_string(length):
    return ''.join([ascii_chr(random.randint(0, 255)) for _ in range(length)])


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


@pytest.mark.parametrize('DB', [_CodernityDB, _LevelDB])
def test_db(DB):
    if DB is None:
        pytest.xfail('DB not installed')
    tempdir = tempfile.mktemp()
    f = db_path(tempfile.mktemp())
    db1 = DB(f)
    for key in content:
        assert key not in db1
        with pytest.raises(KeyError):
            db1.get(key)
    for key, value in content.items():
        db1.put(key, value)
        assert key in db1
        assert db1.get(key) == value

    # not commited, so db2 is empty
    db2 = DB(f)
    for key in content:
        assert key not in db2
        with pytest.raises(KeyError):
            db2.get(key)
    for key, value in content.items():
        db2.put(key, value)
    db2.commit()
    for key, value in content.items():
        assert key in db2
        assert db2.get(key) == value
    for key in content:
        db2.put(key, alt_content[key])
        assert key in db2
        assert db2.get(key) == alt_content[key]

    # alt_content not commited, so db3 still contains original content
    db3 = DB(f)
    for key, value in content.items():
        assert key in db3
        assert db3.get(key) == value
    for key in content.items():
        db3.delete(key)
        assert key not in db3
        with pytest.raises(KeyError):
            db3.get(key)

    # deletion not commited, so db4 still contains original content
    db4 = DB(f)
    for key in content:
        assert key in db4
        assert db4.get(key) == content[key]
        db4.delete(key)
        assert key not in db4
        with pytest.raises(KeyError):
            db4.get(key)
    db4.commit()

    # deletion commited, so db5 is empty
    db5 = DB(f)
    for key in content:
        assert key not in db5
        with pytest.raises(KeyError):
            db5.get(key)
