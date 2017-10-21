FROM python:3.6

MAINTAINER Amit Kumar Jaiswal <amitkumarj441@gmail.com>

# Install dependencies
RUN apt-get update && \
    apt-get install -y libssl-dev build-essential automake pkg-config libtool libffi-dev libgmp-dev

# Download and install Pyethereum
WORKDIR /code
RUN https://github.com/ethereum/pyethereum.git
WORKDIR /code/pyethereum
RUN python setup.py install
