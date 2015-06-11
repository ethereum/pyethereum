from ethereum import tester


def test_blockhashes_10():
    s = tester.state()
    s.mine(10)
    o = [s.block.get_ancestor_hash(i) for i in range(1, 11)]
    assert o[0] == s.block.get_parent().hash == s.blocks[9].hash
    for i in range(1, 9):
        assert o[i] == s.blocks[9 - i].hash


def test_blockhashes_300():
    s = tester.state()
    s.mine(300)
    o = [s.block.get_ancestor_hash(i) for i in range(1, 257)]
    assert o[0] == s.block.get_parent().hash == s.blocks[299].hash
    for i in range(1, 256):
        assert o[i] == s.blocks[299 - i].hash
