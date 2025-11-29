"""
Root conftest for all tests (unit and integration).

This sets up the test environment BEFORE any modules are imported.
"""

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
