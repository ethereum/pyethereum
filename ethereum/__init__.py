# ############# version ##################
from pkg_resources import get_distribution, DistributionNotFound
import os.path
try:
    _dist = get_distribution('ethereum')
    # Normalize case for Windows systems
    dist_loc = os.path.normcase(_dist.location)
    here = os.path.normcase(__file__)
    if not here.startswith(os.path.join(dist_loc, 'ethereum')):
        # not installed, but there is another version that *is*
        raise DistributionNotFound
except DistributionNotFound:
    __version__ = 'Please install this project with setup.py'
else:
    __version__ = _dist.version
# ########### endversion ##################

'''from ethereum import utils
from ethereum import trie
from ethereum import securetrie
from ethereum import blocks
from ethereum import transactions
from ethereum import processblock
from ethereum import tester
from ethereum import abi
from ethereum import ethash'''
