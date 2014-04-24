from common import app  # noqa


def auto_discover():
    from os import path
    import pkgutil
    current_dir = path.dirname(__file__)
    for finder, name, ispkg in pkgutil.iter_modules(path=[current_dir]):
        main_name = path.splitext(name)[0]
        if main_name.endswith('api'):
            finder.find_module(name).load_module(name)

auto_discover()
