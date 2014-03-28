
from setuptools import setup, find_packages

console_scripts = ['trie=pyethereum.trie:main',
                   'eth=pyethereum.eth:main']

setup(name="pyethereum",
      packages=find_packages("."),
      install_requires=['leveldb', 'pybitcointools', 'pysha3'],
      entry_points=dict(console_scripts=console_scripts))
