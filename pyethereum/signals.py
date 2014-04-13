from dispatch import Signal

config_ready = Signal(providing_args=[""])
connection_accepted = Signal(providing_args=["connection", "host", "port"])

packet_sending = Signal(providing_args=["packet"])
packet_sent = Signal(providing_args=["packet"])

peers_data_requested = Signal(providing_args=["request_data"])
peers_data_ready = Signal(providing_args=["requester", "ready_data"])

transactions_data_requested = Signal(providing_args=["request_data"])
transactions_data_ready = Signal(providing_args=["requester", "ready_data"])

blocks_data_requested = Signal(providing_args=["request_data"])
blocks_data_ready = Signal(providing_args=["requester", "ready_data"])

disconnect_requested = Signal(providing_args=[""])

new_peer_received = Signal(providing_args=["peer"])
new_transactions_received = Signal(providing_args=["transactions"])
new_blocks_received = Signal(providing_args=["blocks"])


def request_data_async(sender, data_name, request_data, ready_data_consumer):
    requested_signal = globals()["{0}_data_requested".format(data_name)]
    ready_signal = globals()["{0}_data_ready".format(data_name)]

    def data_ready_handler(requester, ready_data, **kwargs):
        # ignore ready signal for other requester
        if requester is not sender:
            return
        ready_data_consumer(ready_data=ready_data)
        ready_signal.discconnect(data_ready_handler)

    ready_signal.connect(data_ready_handler)
    requested_signal.send(sender=sender, request_data=request_data)
