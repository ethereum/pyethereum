import pytest
from ethereum import slogging


@pytest.mark.hookwrapper
def pytest_runtest_setup(item):
    """Attach pytest-capturelog's handler to `slogging`'s root logger"""
    yield
    caplog_handler = getattr(item, 'capturelog_handler', None)
    if caplog_handler and caplog_handler not in slogging.rootLogger.handlers:
        slogging.rootLogger.addHandler(caplog_handler)


@pytest.mark.hookwrapper
def pytest_runtest_makereport(item, call):
    """Remove pytest-capturelog's handler from `slogging`'s root logger"""
    if call.when == 'call':
        caplog_handler = getattr(item, 'capturelog_handler', None)
        if caplog_handler and caplog_handler in slogging.rootLogger.handlers:
            slogging.rootLogger.removeHandler(caplog_handler)
    yield
