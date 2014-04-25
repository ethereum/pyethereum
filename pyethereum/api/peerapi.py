from common import app
from bottle import request  # noqa


@app.get('/')
def index():
    return dict(name="chen", last="houwu")
