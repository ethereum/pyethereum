===================================================
Ethereum -- Next generation cryptocurrency network
===================================================

Ethereum Python Client
======================

+-----------+------------------+------------------+--------------------+--------------------+
|           | Linux            | OSX              | Travis             | Coverage           |
+-----------+------------------+------------------+--------------------+--------------------+
| develop   | |Linux develop|  | |OSX develop|    | |Travis develop|   | |Coverage develop| |
+-----------+------------------+------------------+--------------------+--------------------+
| master    | |Linux master|   | |OSX master|     | |Travis master|    | |Coverage master|  |
+-----------+------------------+------------------+--------------------+--------------------+

Quickstart
-------------

Installation:
++++++++++++++


``git clone https://github.com/ethereum/pyethereum/``

``python setup.py install``



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

See our `developer notes <https://github.com/ethereum/pyethereum/wiki/Developer-Notes>`_


Licence
========
See LICENCE

`Ethereum <https://ethereum.org/>`_ is based on a design by Vitalik Buterin.

.. |Linux develop| image:: http://build.ethdev.com/buildstatusimage?builder=Linux%20PyEthereum%20develop
   :target: https://build.ethdev.com/builders/Linux%20PyEthereum%20develop/builds/-1
.. |OSX develop| image:: https://build.ethdev.com/buildstatusimage?builder=OSX%20PyEthereum%20develop
   :target: https://build.ethdev.com/builders/OSX%20PyEthereum%20develop/builds/-1
.. |Linux master| image:: http://build.ethdev.com/buildstatusimage?builder=Linux%20PyEthereum%20master
   :target: https://build.ethdev.com/builders/Linux%20PyEthereum%20master/builds/-1
.. |OSX master| image:: https://build.ethdev.com/buildstatusimage?builder=OSX%20PyEthereum%20master
   :target: https://build.ethdev.com/builders/OSX%20PyEthereum%20master/builds/-1

.. |Travis develop| image:: https://travis-ci.org/ethereum/pyethereum.png?branch=develop
   :target: https://travis-ci.org/ethereum/pyethereum
.. |Travis master| image:: https://travis-ci.org/ethereum/pyethereum.png?branch=master
   :target: https://travis-ci.org/ethereum/pyethereum
.. |Coverage develop| image:: https://coveralls.io/repos/ethereum/pyethereum/badge.png?branch=develop
   :target: https://coveralls.io/r/ethereum/pyethereum?branch=develop
.. |Coverage master| image:: https://coveralls.io/repos/ethereum/pyethereum/badge.png?branch=master
   :target: https://coveralls.io/r/ethereum/pyethereum?branch=master
