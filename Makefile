.PHONY: clean-pyc clean-build docs clean

help:
	@echo "clean - remove all build, test, coverage and Python artifacts"
	@echo "clean-build - remove build artifacts"
	@echo "clean-pyc - remove Python file artifacts"
	@echo "clean-test - remove test and coverage artifacts"
	@echo "lint - check style with flake8"
	@echo "test - run tests with the default Python"
	@echo "testnovm - run tests except test_vm"
	@echo "testquick - run tests except test_vm, test_state"
	@echo "testtb - run tests with tracebacks"
	@echo "test-all - run tests on every Python version with tox"
	@echo "coverage - check code coverage quickly with the default Python"
	@echo "docs - generate Sphinx HTML documentation, including API docs"
	@echo "release - package and upload a release"
	@echo "dist - package"
	@echo "fixtures-init - init fixtures"
	@echo "fixtures-update - update fixtures"

clean: clean-build clean-pyc clean-test

clean-build:
	rm -fr build/
	rm -fr dist/
	rm -fr *.egg-info

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-test:
	rm -fr .tox/
	rm -f .coverage
	rm -fr htmlcov/

lint:
	flake8 ethereum tests --ignore=E501

lint-minimal:
	python -m flake8 --ignore=F401,F841,F811 --select=F --exclude=todo,experimental,ethash.py,ethash_utils.py ethereum

test:
	py.test --tb=no ethereum/tests/

test-minimal:
	py.test ethereum/tests/test_abi.py ethereum/tests/test_bloom.py ethereum/tests/test_chain.py ethereum/tests/test_compress.py ethereum/tests/test_db.py ethereum/tests/test_difficulty.py ethereum/tests/test_opcodes.py ethereum/tests/test_trie_next_prev.py ethereum/tests/test_utils.py

testnovm:
	py.test --tb=no ethereum/tests/ --ignore=ethereum/tests/test_vm.py

testquick:
	py.test --tb=no ethereum/tests/ --ignore=ethereum/tests/test_vm.py --ignore=ethereum/tests/test_state.py

testtb:
	python setup.py test

test-all:
	tox

fixtures-init:
	git submodule init
	git submodule update --recursive
fixtures-update:
	cd fixtures && git pull origin develop && cd ..

coverage:
	coverage run --source ethereum setup.py test
	coverage report -m
	coverage html
	open htmlcov/index.html

release: clean
	@echo "make sure the github dependencies are updated to their respective pypi packets in setup.py"
	python setup.py sdist upload
	python setup.py bdist_wheel upload

dist: clean
	python setup.py sdist
	python setup.py bdist_wheel
	ls -l dist
