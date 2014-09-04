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

- Python2.7 is required

``pip install -r requirements.txt``

That will try to install the requirements in your current environment.

*NOTE*: If you have not setup a `virtualenv <https://pypi.python.org/pypi/virtualenv>`_
this will most likely try to install dependencies globally and might require more
privileges.

In case you want to avoid messing with your global environment, you can use `Buildout (optional)`_.

Run the client:
+++++++++++++++
``pyethereum/eth.py -r 54.204.10.41``

For developers
---------------

How to contribute
++++++++++++++++++
We accept pull requests. `Fork the repository <https://github.com/ethereum/pyethereum/fork>`_ and send your PR!

dev_requirements
+++++++++++++++++
To install the dependencies necessary for development (testing, ...), run::

    pip install -r dev_requirements.txt
    python setup.py install

Coding
+++++++
#.  You should write code compatible with Python3.
#.  Your code should pass PEP8 check.

Testing
+++++++++
`pytest <http://pytest.org/latest/>`_ is used for testing

In order to run tests, you need to prepare the ``fixtures``-submodule
(not necessary when using bootstrap)::

    git submodule init
    git submodule update --recursive

then run the tests either by calling
``py.test`` (or ``behave`` for a set of older tests) consecutively or by calling ``tox`` (which will do both).

In order to update the ``fixtures``-submodule::

    git submodule status
    cd fixtures/
    git pull origin develop
    cd ..
    git commit -m 'updated fixtures submodule'

Tips for testing with the VM::

1. You can get traces for a transaction using the API and ethclient, e.g.::
    bin/pyethclient trace 522f583b94cb3a16deca41404ef404c2c1b3484070af2ec7971bc4e1a17c556e
2. Use the ``-s`` modifier to see the log output of tests, e.g.
    ``py.test -s tests/test_vm.py``
3. You can customize the level of VM logging detail by modifying PBLogger in processblock.py

Logging:
+++++++++
Please use the ``logging`` module for logging.

For basic, verbose logging functionality, the following is sufficient (adjust level to your needs)::

    import logging

    logging.basicConfig(format='[%(asctime)s] %(name)s %(levelname)s %(message)s', level=logging.DEBUG)
    logger = logging.getLogger(__name__)

If you need a more advanced setup, have a look at the
`python docs <http://docs.python.org/2/library/logging.html>`_


Easy Debugging:
~~~~~~~~~~~~~~~~
The ``eth.py`` script, understands a command line flag for easy debugging, e.g.::

    pyethereum/eth.py -L pyethereum.wire:DEBUG,:INFO ...<other args>

will set the log-level for ``wire`` to ``DEBUG`` and the root logger to ``INFO``.

    pyethereum/eth.py -L :DEBUG ...<other args>

logs everything to the console.


Buildout (optional)
-------------------
You can have dependencies managed by `buildout <http://buildout.org>`_ --
a ``buildout.cfg`` is already included in the project.

Bootstrap:
++++++++++++++++
In order to do so, you'll need to bootstrap the project (needs only be
done once). On systems that provide ``curl`` you can use the following handy
one-liner (`no curl`_ ?):

``curl http://downloads.buildout.org/2/bootstrap.py | python``

Build and run:
+++++++++++++++
Build the project via ``bin/buildout`` and run the client via ``bin/eth``.

This will install dependencies in a virtualenv, provide you with a scoped ``python``
interpreter (``bin/python``) and make all console_scripts available in the
``bin`` directory.

develop.cfg
++++++++++++
Instead of only running ``bin/buildout``, there is an extending
buildout configuration for development purposes (it will install the
dev_requirements, prepare tests, etc...). It is an *executable* .cfg file::

  ./develop.cfg

will run the extended buildout.

Hints:
+++++++

console-scripts
~~~~~~~~~~~~~~~
If you follow the **buildout** way, some of the commands in this `README` will change,
since buildout installs the dependencies as well as pyethereum's console_scripts in the ``bin/``-directory.
For example, instead of running the cli client with::

    pyethereum/eth.py # it will become
    bin/eth

same goes for ``behave`` which becomes ``bin/behave``.

no curl
~~~~~~~~
If your system has ``wget`` and not ``curl`` you can also use ``wget -O -``
in place of ``curl``. Otherwise download the `bootstrap script <http://downloads.buildout.org/2/bootstrap.py>`_
into the project folder and call ``python bootstrap.py``.  (If you get setuptools issue, try
``python bootstrap.py -v 2.1.1``)

buildout default.cfg
~~~~~~~~~~~~~~~~~~~~~~
To prevent buildout from cluttering your working directory with an ``eggs/`` directory, you should
consider using a ``~/.buildout/default.cfg``::

    export "BDIR=$HOME/.buildout"
    mkdir -p $BDIR/eggs $BDIR/extends $BDIR/cache
    echo "[buildout]" >> $BDIR/default.cfg
    echo "eggs-directory = $BDIR/eggs" >> $BDIR/default.cfg
    echo "download-cache = $BDIR/cache" >> $BDIR/default.cfg
    echo "extends-cache = $BDIR/extends" >> $BDIR/default.cfg

After doing that, cleaning your clone with ``git clean -xfd`` and redoing the **Bootstrap** part is recommended.


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
