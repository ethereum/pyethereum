import pytest
from pyethereum import tester


def test_blockhashes_10():
    s = tester.state()
    s.mine(10)
    o = s.block.get_ancestor_list(256)
    assert o[0] == s.block == s.blocks[10]
    for i in range(1, 10):
        assert o[i] == s.blocks[10-i]
    for i in range(11, 257):
        assert o[i] is None
    assert len(o) == 257


def test_blockhashes_300():
    s = tester.state()
    s.mine(300)
    o = s.block.get_ancestor_list(256)
    assert o[0] == s.block == s.blocks[300]
    for i in range(1, 257):
        assert o[i] == s.blocks[300-i]
    assert len(o) == 257
