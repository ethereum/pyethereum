from dispatch import Signal

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

getpeers_received = Signal(providing_args=["peer"])
gettransactions_received = Signal(providing_args=["peer"])

remote_blocks_received = Signal(providing_args=["block_lst", "peer"])
remote_chain_requested = Signal(providing_args=["parents", "count"])
local_chain_requested = Signal(providing_args=["peer", "blocks", "count"])
send_local_blocks = Signal(providing_args=["blocks"])

local_transaction_received = Signal(providing_args=["transaction"])
remote_transactions_received = Signal(providing_args=["transactions"])
send_local_transactions = Signal(providing_args=["transaction"])
