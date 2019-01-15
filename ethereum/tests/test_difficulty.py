import ethereum.utils as utils
import rlp
import ethereum.tools.testutils as testutils
import ethereum.config as config
from ethereum.state import State
from ethereum.common import calc_difficulty
from ethereum.block import Block, BlockHeader
import sys
import os
import json

from ethereum.slogging import get_logger
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
# configure_logging(':trace')


def test_difficulty(filename, testname, testdata):

    parent_timestamp = int(
        testdata["parentTimestamp"],
        10 if testdata["parentTimestamp"].isdigit() else 16)
    parent_difficulty = int(
        testdata["parentDifficulty"],
        10 if testdata["parentDifficulty"].isdigit() else 16)
    parent_blk_number = int(
        testdata["currentBlockNumber"],
        10 if testdata["currentBlockNumber"].isdigit() else 16) - 1
    cur_blk_timestamp = int(
        testdata["currentTimestamp"],
        10 if testdata["currentTimestamp"].isdigit() else 16)
    reference_dif = int(
        testdata["currentDifficulty"],
        10 if testdata["currentDifficulty"].isdigit() else 16)

    env = config.Env()
    if 'Homestead' in filename:
        env.config['HOMESTEAD_FORK_BLKNUM'] = 0
    elif 'difficultyFrontier' in filename:
        env.config['HOMESTEAD_FORK_BLKNUM'] = 2**99
    elif 'difficultyMorden' in filename:
        env.config['HOMESTEAD_FORK_BLKNUM'] = 494000
    elif 'difficultyRopsten' in filename:
        env.config['HOMESTEAD_FORK_BLKNUM'] = 0
    else:
        env.config['HOMESTEAD_FORK_BLKNUM'] = 1150000
    # env.config['EXPDIFF_FREE_PERIODS'] = 2**98

    parent = Block(BlockHeader(timestamp=parent_timestamp,
                               difficulty=parent_difficulty,
                               number=parent_blk_number))

    calculated_dif = calc_difficulty(
        parent, cur_blk_timestamp, config=env.config)

    print(calculated_dif)
    print(reference_dif)
    assert calculated_dif == reference_dif, (parent.header.difficulty, reference_dif,
                                             calculated_dif, parent.header.number, cur_blk_timestamp - parent_timestamp)


def not_a_difficulty_test(filename, testname, testdata):
    if 'difficultyOlimpic.json' in filename:
        return True
    if 'difficulty' in filename:
        return False

    return True


def pytest_generate_tests(metafunc):
    testutils.generate_test_params(
        'BasicTests',
        metafunc,
        exclude_func=not_a_difficulty_test)


def main():
    import pdb
    pdb.set_trace()
    if len(sys.argv) == 1:
        # read fixture from stdin
        fixtures = {'stdin': json.load(sys.stdin)}
    else:
        # load fixtures from specified file or dir
        fixtures = testutils.get_tests_from_file_or_dir(sys.argv[1])
    for filename, tests in list(fixtures.items()):
        for testname, testdata in list(tests.items()):
            if len(sys.argv) < 3 or testname == sys.argv[2]:
                print("Testing: %s %s" % (filename, testname))
                # testutils.check_state_test(testdata)
                test_difficulty(filename, testname, testdata)


if __name__ == '__main__':
    main()
