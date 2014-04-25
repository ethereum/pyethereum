from common import make_api_app as _make_root_app

app = _make_root_app()


def _auto_discover():
    from os import path
    import pkgutil
    current_dir = path.dirname(__file__)
    for finder, name, ispkg in pkgutil.iter_modules(path=[current_dir]):
        if name.endswith('api'):
            full_name = 'pyethereum.api.{}'.format(name)
            module = finder.find_module(full_name).load_module(full_name)
            app.mount('/{}'.format(name[:-3]), module.app)
    print app

_auto_discover()
