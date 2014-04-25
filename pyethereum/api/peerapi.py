from common import make_api_app, response_async_data
from bottle import request  # noqa

from models import Peer, PeerResponder

app = make_api_app()


def make_peers_response(peers):
    peers = [Peer(host, ip, node_id) for (host, ip, node_id) in peers]
    return PeerResponder().respond(peers)


@app.get('/live/')
def live():
    return response_async_data('live_peers', make_peers_response)


@app.get('/known/')
def known():
    return response_async_data('known_peers', make_peers_response)
