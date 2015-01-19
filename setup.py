from setuptools import setup, find_packages
import versioneer
versioneer.VCS = 'git'
versioneer.versionfile_source = 'pyethereum/_version.py'
versioneer.versionfile_build = 'pyethereum/_version.py'
versioneer.tag_prefix = '' # tags are like 1.2.0
versioneer.parentdir_prefix = 'pyethereum-' # dirname like 'myproject-1.2.0'

from setuptools.command.test import test as TestCommand
class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True
    def run_tests(self):
        #import here, cause outside the eggs aren't loaded
        import pytest
        pytest.main(self.test_args)


console_scripts = ['pyeth=pyethereum.eth:main',
                   'pyethclient=pyethereum.ethclient:main']


cmdclass=versioneer.get_cmdclass()
cmdclass['test'] = PyTest

install_requires = [x.strip() for x in open('requirements.txt')]

setup(name="pyethereum",
      packages=find_packages("."),
      description='Next generation cryptocurrency network',
      url='https://github.com/ethereum/pyethereum/',
      install_requires=install_requires,
      entry_points=dict(console_scripts=console_scripts),
      version=versioneer.get_version(),
      cmdclass=cmdclass
      )
