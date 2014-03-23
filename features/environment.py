from trie_hook import trie_feature_hooker

# USE: BEHAVE_DEBUG_ON_ERROR=yes     (to enable debug-on-error)
from distutils.util import strtobool as _bool
import os

BEHAVE_DEBUG_ON_ERROR = _bool(os.environ.get("BEHAVE_DEBUG_ON_ERROR", "no"))

def after_step(context, step):
    if BEHAVE_DEBUG_ON_ERROR and step.status == "failed":
        # -- ENTER DEBUGGER: Zoom in on failure location.
        # NOTE: Use IPython debugger, same for pdb (basic python debugger).
        import ipdb
        ipdb.post_mortem(step.exc_traceback)


def before_feature(context, feature):
    if feature.name == 'trie tree manipulate':
        trie_feature_hooker.before(context, feature)

def after_feature(context, feature):
    if feature.name == 'trie tree manipulate':
        trie_feature_hooker.after(context, feature)
