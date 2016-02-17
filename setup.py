import sys
from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand


class PyTest(TestCommand):
    user_options = [('pytest-args=', 'a', "Arguments to pass to py.test")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.pytest_args = []

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import pytest
        errno = pytest.main(self.pytest_args)
        sys.exit(errno)

with open('README.rst') as readme_file:
    readme = readme_file.read()


console_scripts = []

cmdclass = dict(test=PyTest)

# requirements
install_requires = set(x.strip() for x in open('requirements.txt'))
install_requires_replacements = {
    'https://github.com/ethereum/ethash/tarball/master': 'pyethash'}
install_requires = [install_requires_replacements.get(r, r) for r in install_requires]

# dev requirements
tests_require = set(x.strip() for x in open('dev_requirements.txt'))
tests_require_replacements = {
    'https://github.com/ethereum/serpent/tarball/develop': 'ethereum-serpent>=1.8.1'}
tests_require = [tests_require_replacements.get(r, r) for r in tests_require]

# *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
# see: https://github.com/ethereum/pyethapp/wiki/Development:-Versions-and-Releases
version = '1.0.8'

setup(name="ethereum",
      packages=find_packages("."),
      description='Next generation cryptocurrency network',
      long_description=readme,
      url='https://github.com/ethereum/pyethereum/',
      install_requires=install_requires,
      tests_require=tests_require,
      entry_points=dict(console_scripts=console_scripts),
      version=version,
      cmdclass=cmdclass
      )
