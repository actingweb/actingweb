"""
Root conftest for all tests (unit and integration).

This sets up the test environment BEFORE any modules are imported.
"""

import faulthandler
import os


def pytest_configure(config):
    """
    Pytest hook that runs before test collection and module imports.

    This is critical - it sets environment variables BEFORE ActingWeb modules
    are imported, ensuring that PynamoDB models use test table names.
    """
    # Set test AWS credentials
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
    os.environ["AWS_DEFAULT_REGION"] = "us-west-1"
    os.environ["AWS_DB_PREFIX"] = "test"

    # For unit tests that don't need actual DynamoDB, point to localhost
    # Integration tests will override this with their docker host
    # Port 8001 matches docker-compose.test.yml which maps host:8001 -> container:8000
    if "AWS_DB_HOST" not in os.environ:
        os.environ["AWS_DB_HOST"] = "http://localhost:8001"

    # Non-cooperative hang watchdog (opt-in via PYTEST_WATCHDOG_SECONDS, used in
    # CI). faulthandler.dump_traceback_later runs a C-level timer thread that
    # dumps ALL thread stacks and hard-exits if this process is still alive after
    # N seconds. This catches an xdist controller/worker wedge (e.g. the
    # controller blocked in socket recv waiting on an unresponsive worker at the
    # suite tail) that pytest's own *cooperative* --session-timeout cannot
    # interrupt — its check only runs when the event loop regains control, which
    # a recv-wedge prevents. Armed in both the controller and every worker
    # process (each runs pytest_configure). N must exceed the legitimate full-run
    # wall but stay under the CI job's timeout-minutes.
    watchdog = os.environ.get("PYTEST_WATCHDOG_SECONDS")
    if watchdog:
        try:
            seconds = float(watchdog)
        except ValueError:
            seconds = 0
        if seconds > 0:
            faulthandler.dump_traceback_later(seconds, exit=True)


def pytest_unconfigure(config):
    """Cancel the hang watchdog on clean shutdown so it can't fire post-run."""
    if os.environ.get("PYTEST_WATCHDOG_SECONDS"):
        faulthandler.cancel_dump_traceback_later()


def pytest_collection_modifyitems(config, items):
    """
    Reorder tests to run unit tests first, then integration tests.

    Integration tests use class-level state that depends on test ordering.
    By running them after unit tests, we ensure they maintain their relative
    order within the integration test files.
    """
    # Separate tests into unit and integration
    unit_tests = []
    integration_tests = []

    for item in items:
        if "integration" in str(item.fspath):
            integration_tests.append(item)
        else:
            unit_tests.append(item)

    # Reorder: unit tests first, then integration tests (preserving their order)
    items[:] = unit_tests + integration_tests
