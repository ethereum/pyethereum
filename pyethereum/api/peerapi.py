from common import make_api_app
from bottle import request  # noqa

app = make_api_app()


@app.get('/')
def index():
    return dict(name="chen", last="houwu")
