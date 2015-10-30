import pytest
from ethereum import slogging


CATCH_LOG_HANDLER_NAME = 'catch_log_handler'


@pytest.mark.hookwrapper
def pytest_runtest_setup(item):
    """Attach pytest-catchlog's handler to `slogging`'s root logger"""
    yield
    caplog_handler = getattr(item, CATCH_LOG_HANDLER_NAME, None)
    if caplog_handler and caplog_handler not in slogging.rootLogger.handlers:
        slogging.rootLogger.addHandler(caplog_handler)


@pytest.mark.hookwrapper
def pytest_runtest_makereport(item, call):
    """Remove pytest-catchlog's handler from `slogging`'s root logger"""
    if call.when == 'call':
        caplog_handler = getattr(item, CATCH_LOG_HANDLER_NAME, None)
        if caplog_handler and caplog_handler in slogging.rootLogger.handlers:
            slogging.rootLogger.removeHandler(caplog_handler)
    yield
