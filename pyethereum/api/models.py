from marshmallow import Serializer, fields
from hyp.responder import Responder


class Peer(object):
    def __init__(self, host, port, node_id=''):
        self.host = host
        self.port = port
        self.node_id = node_id


class PeerSerializer(Serializer):
    host = fields.String()
    port = fields.Integer()
    node_id = fields.String()


class PeerResponder(Responder):
    TYPE = 'peer'
    SERIALIZER = PeerSerializer
