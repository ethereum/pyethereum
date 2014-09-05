===================================================
Ethereum -- Next generation cryptocurrency network
===================================================

Ethereum Python Client
======================
.. image:: https://travis-ci.org/ethereum/pyethereum.png?branch=master
   :target: https://travis-ci.org/ethereum/pyethereum

.. image:: https://coveralls.io/repos/ethereum/pyethereum/badge.png
  :target: https://coveralls.io/r/ethereum/pyethereum


Quickstart
-------------

Installation:
++++++++++++++


``git clone https://github.com/ethereum/pyethereum/``
``python setup.py install``
``pip install -r requirements.txt``


Running the client:
+++++++++++++++

``pyeth`` at the commandline will start the ethereum node and connect to the p2p network. 

Note: At the first invocation a default configuration will be written to ~/.pyethereum (location depending on your platform). 
You can edit this file to suite your needs.


Interacting with the network:
+++++++++++++++

``pyethclient`` is the command line client to inspect and manipulate the ethereum blockchain.


Tutorial coming soon!


For developers
---------------

See our [developer notes](https://github.com/ethereum/pyethereum/wiki/Developer-Notes)


Licence
========
See LICENCE

Credits
========
`Ethereum <https://ethereum.org/>`_ is based on a design by Vitalik Buterin.

Implementation of the python ethereum client is mainly done by

- Chen Houwu
- Heiko Hees
- Vitalik Buterin
