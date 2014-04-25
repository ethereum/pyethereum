from bottle import Bottle


def make_api_app():
    app = Bottle()
    app.config['autojson'] = True
    return app
