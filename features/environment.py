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


def auto_discover_hooks():
    from os import path
    from importlib import import_module

    hooks = {}
    hook_dir = path.join(path.dirname(__file__), 'hooks')
    for f in os.listdir(hook_dir):
        if not f.endswith('.py'):
            continue
        name = f[:-3]
        module = import_module('hooks.{0}'.format(name))
        if not hasattr(module, 'hook'):
            continue
        hooks[name] = getattr(module, 'hook')

    return hooks

hooks = auto_discover_hooks()


def before_feature(context, feature):
    for tag in feature.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'before_feature'):
                hooks[tag].before_feature(context, feature)


def after_feature(context, feature):
    for tag in feature.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'after_feature'):
                hooks[tag].after_feature(context, feature)


def before_scenario(context, scenario):
    for tag in scenario.feature.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'before_scenario'):
                hooks[tag].before_scenario(context, scenario)

    for tag in scenario.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'before_scenario'):
                hooks[tag].before_scenario(context, scenario)


def after_scenario(context, scenario):
    for tag in scenario.feature.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'after_scenario'):
                hooks[tag].after_scenario(context, scenario)

    for tag in scenario.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'after_scenario'):
                hooks[tag].after_scenario(context, scenario)
