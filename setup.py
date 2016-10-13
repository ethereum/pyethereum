from setuptools import setup, find_packages


with open('README.rst') as readme_file:
    readme = readme_file.read()

# requirements
install_requires = set(x.strip() for x in open('requirements.txt'))
install_requires_replacements = {
    'https://github.com/ethereum/ethash/tarball/master': 'pyethash',
}
install_requires = [install_requires_replacements.get(r, r) for r in install_requires]

# dev requirements
tests_require = set(x.strip() for x in open('dev_requirements.txt'))
tests_require_replacements = dict()
tests_require_replacements = {
    'https://github.com/ethereum/serpent/tarball/develop': 'ethereum-serpent>=2.0.2'
}
tests_require = [tests_require_replacements.get(r, r) for r in tests_require]

# *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
# see: https://github.com/ethereum/pyethapp/wiki/Development:-Versions-and-Releases
version = '1.5.4'

setup(
    name="ethereum",
    packages=find_packages("."),
    description='Next generation cryptocurrency network',
    long_description=readme,
    url='https://github.com/ethereum/pyethereum/',
    install_requires=install_requires,
    tests_require=tests_require,
    setup_requires=[
        'pytest-runner==2.7'
    ],
    version=version,
    classifiers=[
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
)
