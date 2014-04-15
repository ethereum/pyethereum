from distutils.util import strtobool as _bool
import os


def auto_discover_hooks():
    from os import path
    import pkgutil

    hooks = {}
    hook_dir = path.join(path.dirname(__file__), 'hooks')
    for finder, name, ispkg in pkgutil.iter_modules(path=[hook_dir]):
        module = finder.find_module(name).load_module(name)
        if not hasattr(module, 'hook'):
            continue
        hooks[name] = getattr(module, 'hook')

    return hooks


def before_all(context):
    context._hooks = auto_discover_hooks()


def before_feature(context, feature):
    hooks = context._hooks
    for tag in feature.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'before_feature'):
                hooks[tag].before_feature(context, feature)


def after_feature(context, feature):
    hooks = context._hooks
    for tag in feature.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'after_feature'):
                hooks[tag].after_feature(context, feature)


def before_scenario(context, scenario):
    hooks = context._hooks
    for tag in scenario.feature.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'before_scenario'):
                hooks[tag].before_scenario(context, scenario)

    for tag in scenario.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'before_scenario'):
                hooks[tag].before_scenario(context, scenario)


def after_scenario(context, scenario):
    hooks = context._hooks
    for tag in scenario.feature.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'after_scenario'):
                hooks[tag].after_scenario(context, scenario)

    for tag in scenario.tags:
        if tag in hooks:
            if hasattr(hooks[tag], 'after_scenario'):
                hooks[tag].after_scenario(context, scenario)


# USE: BEHAVE_DEBUG_ON_ERROR=yes     (to enable debug-on-error)
BEHAVE_DEBUG_ON_ERROR = _bool(os.environ.get("BEHAVE_DEBUG_ON_ERROR", "no"))


def after_step(context, step):
    if BEHAVE_DEBUG_ON_ERROR and step.status == "failed":
        # -- ENTER DEBUGGER: Zoom in on failure location.
        # NOTE: Use IPython debugger, same for pdb (basic python debugger).
        import ipdb
        ipdb.post_mortem(step.exc_traceback)
