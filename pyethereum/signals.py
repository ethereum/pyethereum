from .dispatch import Signal

'''
.. note::
    *sender* is used by *receiver* to specify which source to accept signal
    from, usually it's some *class name*.
    if you want to carry a instance arg, don't use it, instead, you can add one
    more arg in the signal's `provoding_args`
'''

config_ready = Signal(providing_args=["config"])

p2p_address_ready = Signal(providing_args=["ip", "port"])

peer_connection_accepted = Signal(providing_args=["connection", "ip", "port"])
peer_disconnect_requested = Signal(providing_args=["peer", "forget"])

peer_addresses_received = Signal(providing_args=["addresses"])
peer_handshake_success = Signal(providing_args=["peer"])
peer_status_received = Signal(providing_args=["peer"])

getpeers_received = Signal(providing_args=["peer"])

local_transaction_received = Signal(providing_args=["transaction"])
remote_transactions_received = Signal(providing_args=["transactions"])
send_local_transactions = Signal(providing_args=["transaction"])

remote_block_hashes_received = Signal(providing_args=["block_hashes", "peer"])
get_block_hashes_received = Signal(providing_args=["block_hashes", "peer"])

remote_blocks_received = Signal(providing_args=["block_lst", "peer"])
get_blocks_received = Signal(providing_args=["block_hashes", "count", "peer"])

new_block_received = Signal(providing_args=["block", "peer"])

broadcast_new_block = Signal(providing_args=["block"])
