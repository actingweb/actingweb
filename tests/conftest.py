"""
Root conftest for all tests (unit and integration).

This sets up the test environment BEFORE any modules are imported.
"""
import os
import pytest


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
    if "AWS_DB_HOST" not in os.environ:
        os.environ["AWS_DB_HOST"] = "http://localhost:8000"
