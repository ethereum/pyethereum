from setuptools import setup, find_packages

from setuptools.command.test import test as TestCommand


class PyTest(TestCommand):

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import pytest
        pytest.main(self.test_args)


console_scripts = []

cmdclass = dict(test=PyTest)

install_requires = [x.strip() for x in open('requirements.txt')]

setup(name="ethereum",
      packages=find_packages("."),
      description='Next generation cryptocurrency network',
      url='https://github.com/ethereum/pyethereum/',
      install_requires=install_requires,
      entry_points=dict(console_scripts=console_scripts),
      version='0.9.61',
      cmdclass=cmdclass
      )
