#!/usr/bin/env python

import sys
from setuptools import setup, find_packages

install_requires = [
    'leveldb',
    'ez_setup',
    'pybitcointools',
    'pysha3',
        ]

setup(
    name='pyethereum',
    version=0.1,
    description='Ethereum Python Client',
    author='Vitalik Buterin',
    url='https://github.com/ethereum/pyethereum',
    packages=find_packages(),
    install_requires=install_requires,
    license='https://github.com/ethereum/pyethereum/blob/master/LICENSE',
    classifiers = [
            'Development Status :: Alpha',
            'Topic :: Ethereum',
            'Programming Language :: Python',
        ],
    test_suite='test',
    ),

