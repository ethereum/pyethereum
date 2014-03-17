from setuptools import setup


console_scripts = ['trie=pyethereum.trie:main']

setup(name="pyethereum",
      install_requires=['leveldb', 'pybitcointools', 'pysha3'],
      entry_points=dict(console_scripts=console_scripts),
      )
