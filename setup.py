
from setuptools import setup, find_packages

console_scripts = [ 'pyeth=pyethereum.eth:main',
                    'pyethclient=pyethereum.ethclient:main']

setup(name="pyethereum",
      version='0.2.4',
      packages=find_packages("."),
      install_requires=[
          'six', 'leveldb', 'bitcoin', 'pysha3',
          'miniupnpc',
          'bottle', 'waitress', 'docopt'],
      entry_points=dict(console_scripts=console_scripts))
