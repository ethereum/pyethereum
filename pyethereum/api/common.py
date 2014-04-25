import time

from bottle import Bottle

from pyethereum import signals


def make_api_app():
    app = Bottle()
    app.config['autojson'] = True
    return app


def response_async_data(name, make_response, req=None):
    state = dict(res=None, ready=False)

    def callback(data):
        state.update(res=make_response(data), ready=True)

    signals.request_data_async(name, callback, req)

    for i in range(500):
        if state['ready']:
            return state['res']
        time.sleep(0.01)
    return Exception()
