Next generation cryptocurrency network
=======================================
Ethereum Python Client

.. image:: https://travis-ci.org/ethereum/pyethereum.png?branch=master
   :target: https://travis-ci.org/ethereum/pyethereum

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

Otherwise download the `bootstrap script <http://downloads.buildout.org/2/bootstrap.py>`_
into the project folder and call ``python bootstrap.py``.

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
#.  `behave <http://pythonhosted.org/behave/index.html>`_ is used for testing.
    Tips for writing test code for behave

        1. write test scenario in *xxx.feature*
        2. run ``behave``, then behave will report the newly written scenario are
           not implemented, and code skeleton for the corresponding steps will
           also be generated.
        3. copy & copy the generated code skeleton in a file in the *steps*
           directory and then write your own codes basing on it.

#.  Should write codes compatible with Python3
#.  codes should pass PEP8 check.

Logging:
---------
Please use the ``logging`` module for logging.

**pyethereum** defaults to a verbose stdout-logging configuration. To change that, create a file,
``logging.conf``, at the repository-root, e.g.::

    [loggers]
    keys=root,trie

    [handlers]
    keys=consoleHandler,nullHandler

    [formatters]
    keys=default

    [logger_root]
    level=WARNING
    handlers=nullHandler

    [logger_trie]
    level=DEBUG
    handlers=consoleHandler
    qualname=pyethereum.trie

    [formatter_default]
    format=%(asctime)s - %(name)s - %(levelname)s - %(message)s

    [handler_consoleHandler]
    class=StreamHandler
    level=DEBUG
    formatter=default
    args=(sys.stdout,)

    [handler_nullHandler]
    class=NullHandler
    args=()

and adjust levels and handlers according to your needs.

Licence
========
See LICENCE

Author
=========
Vitalik Buterin
