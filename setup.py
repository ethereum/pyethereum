
from setuptools import setup, find_packages

console_scripts = ['eth=pyethereum.eth:main',
                   'serpent=tools.serpent_cli:main']

setup(name="pyethereum",
      packages=find_packages("."),
      install_requires=['leveldb', 'bitcoin', 'pysha3'],
      entry_points=dict(console_scripts=console_scripts))
