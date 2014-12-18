from setuptools import setup, find_packages
import versioneer
versioneer.VCS = 'git'
versioneer.versionfile_source = 'pyethereum/_version.py'
versioneer.versionfile_build = 'pyethereum/_version.py'
versioneer.tag_prefix = '' # tags are like 1.2.0
versioneer.parentdir_prefix = 'pyethereum-' # dirname like 'myproject-1.2.0'

console_scripts = ['pyeth=pyethereum.eth:main',
                   'pyethclient=pyethereum.ethclient:main']

setup(name="pyethereum",
      packages=find_packages("."),
      description='Next generation cryptocurrency network',
      url='https://github.com/ethereum/pyethereum/',
      install_requires=[
          'bitcoin',
          'bottle',
          'docopt',
          'ethereum-serpent',
          'leveldb',
          'miniupnpc',
          'pysha3',
          'pytest',
          'repoze.lru',
          'requests',
          'waitress',
          'structlog',
      ],
      entry_points=dict(console_scripts=console_scripts),
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass())
