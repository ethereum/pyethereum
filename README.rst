Next generation cryptocurrency network
=======================================
Ethereum Python Client

.. image:: https://travis-ci.org/ethereum/pyethereum.png?branch=master
   :target: https://travis-ci.org/ethereum/pyethereum

.. image:: https://coveralls.io/repos/ethereum/pyethereum/badge.png
  :target: https://coveralls.io/r/ethereum/pyethereum


Install
=========
Python2.7 is required.

pip install -r requirements.txt


Buildout(optional)
==================
You can have dependencies managed by `buildout <http://buildout.org>`_ --
a ``buildout.cfg`` is already included in the project.

Bootstrap:
-----------
In order to do so, you'll need to bootstrap the project (needs only be
done once). On systems that provide ``curl`` you can use the following handy
one-liner:

``curl http://downloads.buildout.org/2/bootstrap.py | python``

If your system has ``wget`` and not ``curl`` you can also use ``wget -O -``
in place of ``curl``. Otherwise download the `bootstrap script <http://downloads.buildout.org/2/bootstrap.py>`_
into the project folder and call ``python bootstrap.py``.  (If you get setuptools issue, try
``python bootstrap.py -v 2.1.1``)

Building:
----------
Build the project via ``bin/buildout``.

This will install dependencies in a virtualenv, provide you with a scoped ``python``
interpreter (``bin/python``) and make all console_scripts available in the
``bin`` directory (e.g. ``bin/behave`` in order to run tests).

To Do
=========

For Developer
=============

Coding
------
#.  Should write codes compatible with Python3
#.  codes should pass PEP8 check.

Testing
-------
#.  `behave <http://pythonhosted.org/behave/index.html>`_ is used for testing.

    Tips for writing test code for behave

    1.  write test scenario in *xxx.feature*
    2.  run ``behave``, then behave will report the newly written scenario are
        not implemented, and code skeleton for the corresponding steps will
        also be generated.
    3.  copy & copy the generated code skeleton in a file in the *steps*
        directory and then write your own codes basing on it.
    4.  if you need setup/teardown for feature/scenario with specific tag of
        *mytag*, create a file called mytag.py in the *hooks* directory

    Tips for debug

    1. for test specific scenario while ignoring all other ones, just add `@wip`
       in the uppper line of the scenario.
    2. for debug, run::

        $ BEHAVE_DEBUG_ON_ERROR=yes behave -w

Logging:
---------
Please use the ``logging`` module for logging.

For basic, verbose logging functionality, the following is sufficient (adjust level to your needs)::

    import logging

    logging.basicConfig(format='[%(asctime)s] %(name)s %(levelname)s %(message)s', level=logging.DEBUG)
    logger = logging.getLogger(__name__)

If you need a more advanced setup, have a look at the
`python docs <http://docs.python.org/2/library/logging.html>`_


**Easy Debugging:**
The ``eth.py`` script, understands a command line flag for easy debugging, e.g.::

    pyethereum/eth.py -L pyethereum.wire:DEBUG,:INFO ...<other args>

will set the log-level for ``wire`` to ``DEBUG`` and the root logger to ``INFO``.

Licence
========
See LICENCE

Author
=========
Vitalik Buterin
