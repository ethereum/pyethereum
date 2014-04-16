from dispatch import Signal

config_ready = Signal(providing_args=[""])
connection_accepted = Signal(providing_args=["connection", "host", "port"])

packet_sending = Signal(providing_args=["packet"])
packet_sent = Signal(providing_args=["packet"])

peers_data_requested = Signal(providing_args=["request_data"])
peers_data_ready = Signal(providing_args=["requester", "ready_data"])

transactions_data_requested = Signal(
    providing_args=["request_data", "request_uid"])
transactions_data_ready = Signal(
    providing_args=["requester", "ready_data", "request_uid"])
transactions_data_request_aborted = Signal(providing_args=[""])

blocks_data_requested = Signal(
    providing_args=["request_data", "request_uid"])
blocks_data_ready = Signal(
    providing_args=["requester", "ready_data", "request_uid"])
blocks_data_request_aborted = Signal(providing_args=["request_uid"])

disconnect_requested = Signal(providing_args=[""])

new_peer_received = Signal(providing_args=["peer"])
new_transactions_received = Signal(providing_args=["transactions"])
new_blocks_received = Signal(providing_args=["blocks"])


def request_data_async(sender, data_name, request_data,
                       ready_data_consumer, request_uid=None):
    '''
    :param request_uid: a unique id of any string.
    multiple call with same uid won't have data consumed multiple times
    '''
    requested_signal = globals()["{0}_data_requested".format(data_name)]
    ready_signal = globals()["{0}_data_ready".format(data_name)]
    request_uid_saved = request_uid

    def data_ready_handler(requester, ready_data, request_uid=None, **kwargs):
        # ignore ready signal for other requester
        if requester is not sender:
            return
        if request_uid and request_uid != request_uid_saved:
            return

        ready_data_consumer(ready_data=ready_data)
        ready_signal.discconnect(data_ready_handler)

    ready_signal.connect(data_ready_handler, dispatch_uid=request_uid)
    requested_signal.send(sender=sender, request_data=request_data,
                          request_uid=request_uid)


def abort_data_request(data_name, request_uid):
    ready_signal = globals()["{0}_data_ready".format(data_name)]
    abort_signal = globals()["{0}_data_request_aborted".format(data_name)]
    ready_signal.discconnect(dispatch_uid=request_uid)
    abort_signal.send(sender=None, request_uid=request_uid)
