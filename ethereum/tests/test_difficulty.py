from ethereum import tester, blocks
import ethereum.utils as utils
import rlp
import ethereum.testutils as testutils
from ethereum.testutils import fixture_to_bytes
import ethereum.config as config
import sys
import os
import json

from ethereum.slogging import get_logger
logger = get_logger()
# customize VM log output to your needs
# hint: use 'py.test' with the '-s' option to dump logs to the console
# configure_logging(':trace')


def test_difficulty(filename, testname, testdata):
    testdata = fixture_to_bytes(testdata)

    parent_timestamp=int(testdata["parentTimestamp"], 10 if testdata["parentTimestamp"].isdigit() else 16)
    parent_difficulty=int(testdata["parentDifficulty"], 10 if testdata["parentDifficulty"].isdigit() else 16)
    parent_blk_number=int(testdata["currentBlockNumber"], 10 if testdata["currentBlockNumber"].isdigit() else 16)-1
    cur_blk_timestamp=int(testdata["currentTimestamp"], 10 if testdata["currentTimestamp"].isdigit() else 16)
    reference_dif = int(testdata["currentDifficulty"], 10 if testdata["currentDifficulty"].isdigit() else 16)


    env = tester.state().env
    if 'Homestead' in filename:
        env.config['HOMESTEAD_FORK_BLKNUM'] = 0
    if 'difficultyMorden' in filename:
        env.config['HOMESTEAD_FORK_BLKNUM'] = 494000

    parent_bh = blocks.BlockHeader(timestamp=parent_timestamp,
                             difficulty=parent_difficulty,
                             number=parent_blk_number)
    block = blocks.Block(parent_bh, [], env=env,
                      making=True)


    calculated_dif = blocks.calc_difficulty(block, cur_blk_timestamp)

    print calculated_dif
    print reference_dif
    assert calculated_dif == reference_dif


def not_a_difficulty_test(filename, testname, testdata):
    if 'difficultyOlimpic.json' in filename:
        return True
    if 'difficulty' in filename:
        return False

    return True


def pytest_generate_tests(metafunc):
    testutils.generate_test_params('BasicTests', metafunc, exclude_func=not_a_difficulty_test)


def main():
    import pdb; pdb.set_trace()
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
