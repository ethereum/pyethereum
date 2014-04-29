import uuid
import logging
import traceback

from threading import Timer, Lock

from dispatch import Signal

logger = logging.getLogger(__name__)


config_ready = Signal(providing_args=["config"])
local_address_set = Signal(providing_args=["ip", "port"])

connection_accepted = Signal(providing_args=["connection", "ip", "port"])
disconnect_requested = Signal(providing_args=[""])

new_peer_received = Signal(providing_args=["peer"])
new_transactions_received = Signal(providing_args=["transactions"])
new_blocks_received = Signal(providing_args=["blocks"])

remote_chain_requested = Signal(providing_args=["parents", "count"])
send_blocks = Signal(providing_args=["blocks"])

_async_data_names = [
    'transactions',
    'blocks',
    'peers',
    'connected_peers',
    'known_peers',
]


def _create_async_req_signals():
    for name in _async_data_names:
        globals()['{}_requested'.format(name)] = Signal(
            providing_args=["uid", "req"])
        globals()['{}_request_aborted'.format(name)] = Signal(
            providing_args=["uid"])
        globals()['{}_ready'.format(name)] = Signal(
            providing_args=["uid", "data", "error"])

_create_async_req_signals()

def request_data_async(name, req=None,
                       success_callback=None, fail_callback=None,
                       timeout=5, sender=None):
    '''
    To use this function, two roles must be involved:

    data provider
        a handler for `{name}_requested` signal, which accept two
        parameters: `req` and `uid`. When the data is ready,
        it should send a `{name}_ready` signal. During the data
        producing process, it can optionally handle the
        `{name}_request_aborted` signal, and then abort the process
        with same `request_uid` with the aborted signal

        .. note: you handler will never got activated multiple times if with
        `uid` argument

    data consumer:
        a callable takes one parameter, which will be called with the ready
        `data`

    :param name: data name
    :param req: request arguments
    :param success_callback: data consumer called when success, accept a `data`
        args
    :param fail_callback: exception consumer called when failed, accept a
        `error` args denote the Exception
    :param timeout: timeout to abort the request, if provided `fail_callback`,
        it will be called with a time out Exception
    :param sender: request sender
    :return: the request uid
    '''
    requested_signal = globals()["{}_requested".format(name)]
    ready_signal = globals()["{}_ready".format(name)]
    uid = str(uuid.uuid4())
    state = dict(finished=False)
    lock = Lock()

    def data_ready_handler(sender, data=None, error=None, **kwargs):
        with lock:
            if state['finished']:
                return
            else:
                state['finished'] = True
        try:
            if error:
                fail_callback(error)
            else:
                success_callback(data)
        except:
            logger.warning(traceback.format_exc())
        finally:
            ready_signal.disconnect(dispatch_uid=uid)

    ready_signal.connect(data_ready_handler, dispatch_uid=uid, weak=False)
    requested_signal.send(sender=sender, req=req, uid=uid)

    def timeout_callback():
        with lock:
            if state['finished']:
                return
            else:
                state['finished'] = True
                abort_data_request(name, uid)

        if not fail_callback:
            return

        try:
            fail_callback(Exception('time out for {} seconds'.format(timeout)))
        except:
            logger.warning(traceback.format_exc())

    with lock:
        if not state['finished']:
            timer = Timer(timeout, timeout_callback)
            timer.start()

    return uid


def abort_data_request(name, uid):
    '''
    :param name: data name
    :uid: request uid
    '''
    ready_signal = globals()["{}_ready".format(name)]
    abort_signal = globals()["{}_request_aborted".format(name)]
    ready_signal.disconnect(dispatch_uid=uid)
    abort_signal.send(sender=None, uid=uid)
