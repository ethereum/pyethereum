
from setuptools import setup, find_packages

console_scripts = ['pyeth=pyethereum.eth:main',
                   'pyethtool=tools.pyethtool_cli:main']

setup(name="pyethereum",
      version='0.0.1',
      packages=find_packages("."),
      install_requires=[
          'six', 'leveldb', 'bitcoin', 'pysha3',
          'miniupnpc',
          'bottle', 'waitress'],
      entry_points=dict(console_scripts=console_scripts))
