from common import app  # noqa


def auto_discover():
    from os import path
    import pkgutil
    current_dir = path.dirname(__file__)
    for finder, name, ispkg in pkgutil.iter_modules(path=[current_dir]):
        if name.endswith('api'):
            full_name = 'pyethereum.api.{}'.format(name)
            finder.find_module(full_name).load_module(full_name)

auto_discover()
