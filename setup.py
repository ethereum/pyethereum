
from setuptools import setup, find_packages

console_scripts = ['eth=pyethereum.eth:main',
                   'pyethtool=tools.pyethtool_cli:main']

setup(name="pyethereum",
      packages=find_packages("."),
      install_requires=['six', 'leveldb', 'bitcoin', 'pysha3'],
      entry_points=dict(console_scripts=console_scripts))
