import pytest

from ethereum import slogging


CATCH_LOG_HANDLER_NAME = 'catch_log_handler'


# Connect catchlog's handler to slogging's root logger
@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_call(item):
    catchlog_handler = getattr(item, CATCH_LOG_HANDLER_NAME, None)
    if catchlog_handler and catchlog_handler not in slogging.rootLogger.handlers:
        slogging.rootLogger.addHandler(catchlog_handler)

    _ = yield

    if catchlog_handler and catchlog_handler in slogging.rootLogger.handlers:
        slogging.rootLogger.removeHandler(catchlog_handler)


# Configuration file for adding commandline arguements in pytest
def pytest_addoption(parser):
    parser.addoption("--tracevm", action="store_true",
        help="print vm trace")

@pytest.fixture
def tracevm(request):
    return request.config.getoption("--tracevm")