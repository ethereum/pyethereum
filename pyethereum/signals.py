import uuid
from dispatch import Signal

config_ready = Signal(providing_args=[""])
local_address_set = Signal(providing_args=["ip", "port"])

connection_accepted = Signal(providing_args=["connection", "ip", "port"])
disconnect_requested = Signal(providing_args=[""])

new_peer_received = Signal(providing_args=["peer"])
new_transactions_received = Signal(providing_args=["transactions"])
new_blocks_received = Signal(providing_args=["blocks"])

remote_chain_requested = Signal(providing_args=["parents", "count"])


_async_data_names = [
    'transactions',
    'blocks',
    'peers',
    'live_peers',
    'known_peers',
]


def _create_async_req_signals():
    for name in _async_data_names:
        globals()['{}_requested'.format(name)] = Signal(
            providing_args=["uid", "req"])
        globals()['{}_request_aborted'.format(name)] = Signal(
            providing_args=["uid"])
        globals()['{}_ready'.format(name)] = Signal(
            providing_args=["uid", "data"])

_create_async_req_signals()


def request_data_async(name, callback, req=None, sender=None):
    '''
    To use this function, two roles must be involved:

    data provider
        a handler for `{name}_requested` signal, which accept two
        parameters: `arg` and `uid`. When the data is ready,
        it should send a `{name}_ready` signal. During the data
        producing process, it can optionally handle the
        `{name}_request_aborted` signal, and then abort the process
        with same `request_uid` with the aborted signal

        .. note: you handler will never got activated multiple times if with
        `uid` argument

    data consumer:
        a callable takes one parameter, which will be called with the ready
        `data`

        .. note: it's weak referenced,
            so you should ensure it's not garbage collected

    :param name: data name
    :callback: the data consumer
    :arg: request arguments
    :param sender: request sender
    :return: the request uid
    '''
    requested_signal = globals()["{}_requested".format(name)]
    ready_signal = globals()["{}_ready".format(name)]
    the_uid = str(uuid.uuid4())

    def data_ready_handler(sender, data, **kwargs):
        try:
            callback(data)
        except:
            pass
        ready_signal.disconnect(dispatch_uid=the_uid)

    ready_signal.connect(data_ready_handler, dispatch_uid=the_uid, weak=False)
    requested_signal.send(sender=sender, req=req, uid=the_uid)
    return the_uid


def abort_data_request(name, uid):
    '''
    :param name: data name
    :uid: request uid
    '''
    ready_signal = globals()["{}_ready".format(name)]
    abort_signal = globals()["{}_request_aborted".format(name)]
    ready_signal.discconnect(dispatch_uid=uid)
    abort_signal.send(sender=None, uid=uid)
