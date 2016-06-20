from setuptools import setup, find_packages


with open('README.rst') as readme_file:
    readme = readme_file.read()

# requirements
install_requires = set(x.strip() for x in open('requirements.txt'))
install_requires_replacements = {
    'https://github.com/ethereum/ethash/tarball/master': 'pyethash',
    'git+https://github.com/ulope/secp256k1-py#egg=secp256k1': 'secp256k1'
}
install_requires = [install_requires_replacements.get(r, r) for r in install_requires]

# dev requirements
tests_require = set(x.strip() for x in open('dev_requirements.txt'))
tests_require_replacements = {
    # 'https://github.com/ethereum/serpent/tarball/develop': 'ethereum-serpent>=1.8.1',
    # THIS SHOULD NOT BE MERGED
    'https://github.com/pipermerriam/serpent/tarball/piper/python3-support-with-pyethereum3': 'ethereum-serpent>=1.8.1',
}
tests_require = [tests_require_replacements.get(r, r) for r in tests_require]

# *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
# see: https://github.com/ethereum/pyethapp/wiki/Development:-Versions-and-Releases
version = '1.3.6'

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
    dependency_links=[
        "https://github.com/ulope/secp256k1-py/archive/master.zip#egg=secp256k1-0.11.1"
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
