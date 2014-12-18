
import os
import uuid
import StringIO
import ConfigParser
from pyethereum.utils import default_data_dir
from pyethereum.packeter import Packeter
from pyethereum.utils import sha3




def default_config_path():
    return os.path.join(default_data_dir, 'config.txt')


def default_client_version():
    return Packeter.CLIENT_VERSION  # FIXME


def default_node_id():
    return sha3(str(uuid.uuid1())).encode('hex')

config_template = \
    """
# NETWORK OPTIONS ###########

[network]

# Connect to remote host/port
# poc-7.ethdev.com:30300
remote_host = 207.12.89.180
remote_port = 30300

# Listen on the given host/port for incoming connections
listen_host = 0.0.0.0
listen_port = 30303

# Number of peer to connections to establish
num_peers = 10

# unique id of this node
node_id = {0}

# API OPTIONS ###########
[api]

# Serve the restful json api on the given host/port
listen_host = 0.0.0.0
listen_port = 30203

# path to server the api at
api_path = /api/v02a


# MISC OIPTIONS #########
[misc]

# Load database from path
data_dir = {1}

# percent cpu devoted to mining 0=off
mining = 30

# see help for available log groups
logging = :INFO


# log as json output
log_json = 0

# WALLET OPTIONS ##################
[wallet]

# Set the coinbase (mining payout) address
coinbase = 6c386a4b26f73c802f34673f7248bb118f97424a


""".format(default_node_id(), default_data_dir)


def get_default_config():
    f = StringIO.StringIO()
    f.write(config_template)
    f.seek(0)
    config = ConfigParser.ConfigParser()
    config.readfp(f)
    config.set('network', 'client_version', default_client_version())
    return config


def read_config(cfg_path=default_config_path()):
    # create default if not existent
    if not os.path.exists(cfg_path):
        open(cfg_path, 'w').write(config_template)
    # extend on the default config
    config = get_default_config()
    config.read(cfg_path)
    return config
