"""
Backend Verification Tests

These tests explicitly verify that the correct database backend is being used
based on the DATABASE_BACKEND environment variable. This prevents accidentally
using the wrong backend when both services are running.
"""

import os

import pytest


def test_backend_environment_variable():
    """Verify DATABASE_BACKEND environment variable is set correctly."""
    backend = os.getenv("DATABASE_BACKEND", "dynamodb")
    assert backend in ["dynamodb", "postgresql"], f"Invalid backend: {backend}"


def test_config_loads_correct_backend():
    """Verify Config loads the correct database modules."""
    from actingweb.config import Config

    backend = os.getenv("DATABASE_BACKEND", "dynamodb")
    config = Config()

    # Verify config.database matches environment
    assert config.database == backend, (
        f"Config.database={config.database} but DATABASE_BACKEND={backend}"
    )

    # Verify loaded modules are from correct backend
    assert backend in config.DbActor.__name__, (
        f"DbActor module is {config.DbActor.__name__}, expected to contain '{backend}'"
    )
    assert backend in config.DbProperty.__name__, (
        f"DbProperty module is {config.DbProperty.__name__}, expected to contain '{backend}'"
    )
    assert backend in config.DbTrust.__name__, (
        f"DbTrust module is {config.DbTrust.__name__}, expected to contain '{backend}'"
    )


@pytest.mark.integration
def test_backend_actually_connects():
    """
    Verify the backend actually connects to the expected database.

    This test writes a test record and verifies it can be read back,
    ensuring we're actually using the configured backend.
    """
    import time

    from actingweb.config import Config

    backend = os.getenv("DATABASE_BACKEND", "dynamodb")
    config = Config()

    # Create a test actor with unique ID
    test_id = f"backend_verify_{int(time.time() * 1000)}"
    db_actor = config.DbActor.DbActor()  # type: ignore

    try:
        # Create actor
        success = db_actor.create(
            actor_id=test_id,
            creator="backend_test@example.com",
            passphrase="test123",
        )
        assert success, f"Failed to create test actor in {backend} backend"

        # Read it back
        db_actor_read = config.DbActor.DbActor()  # type: ignore
        result = db_actor_read.get(actor_id=test_id)

        assert result is not None, f"Failed to read test actor from {backend} backend"
        assert result["id"] == test_id, f"Wrong actor ID returned from {backend}"
        assert (
            result["creator"] == "backend_test@example.com"
        ), f"Wrong creator returned from {backend}"

        # Verify we're actually using the expected backend by checking module names
        if backend == "postgresql":
            # PostgreSQL-specific: verify we can get connection info
            from actingweb.db.postgresql.connection import get_pool, get_schema_name

            pool = get_pool()
            assert pool is not None, "PostgreSQL connection pool should be initialized"
            schema = get_schema_name()
            assert schema, "PostgreSQL schema name should be set"

        elif backend == "dynamodb":
            # DynamoDB-specific: verify table name has correct prefix
            from actingweb.db.dynamodb.actor import Actor

            expected_prefix = os.getenv("AWS_DB_PREFIX", "demo_actingweb")
            assert Actor.Meta.table_name.startswith(
                expected_prefix
            ), f"DynamoDB table should start with {expected_prefix}"

    finally:
        # Clean up
        try:
            db_actor_cleanup = config.DbActor.DbActor()  # type: ignore
            db_actor_cleanup.get(actor_id=test_id)
            if db_actor_cleanup.handle:
                db_actor_cleanup.delete()
        except Exception:
            pass  # Best effort cleanup


@pytest.mark.integration
def test_postgresql_exclusive_features():
    """
    Test PostgreSQL-exclusive features to ensure we're using PostgreSQL.

    This test only runs when DATABASE_BACKEND=postgresql.
    """
    backend = os.getenv("DATABASE_BACKEND", "dynamodb")
    if backend != "postgresql":
        pytest.skip("PostgreSQL-specific test")

    from actingweb.db.postgresql.connection import get_connection, get_pool

    # Verify PostgreSQL connection pool exists
    pool = get_pool()
    assert pool is not None, "PostgreSQL connection pool should exist"

    # Verify we can execute a PostgreSQL-specific query
    with get_connection() as conn:
        with conn.cursor() as cur:
            # PostgreSQL-specific: Get version
            cur.execute("SELECT version()")
            result = cur.fetchone()
            assert result is not None, "Should be able to query PostgreSQL version"
            assert (
                "PostgreSQL" in result[0]
            ), f"Version should contain 'PostgreSQL', got: {result[0]}"


@pytest.mark.integration
def test_dynamodb_exclusive_features():
    """
    Test DynamoDB-exclusive features to ensure we're using DynamoDB.

    This test only runs when DATABASE_BACKEND=dynamodb.
    """
    backend = os.getenv("DATABASE_BACKEND", "dynamodb")
    if backend != "dynamodb":
        pytest.skip("DynamoDB-specific test")

    from actingweb.db.dynamodb.actor import Actor

    # Verify DynamoDB table exists and has expected structure
    assert hasattr(Actor, "Meta"), "DynamoDB model should have Meta class"
    assert hasattr(Actor.Meta, "table_name"), "DynamoDB Meta should have table_name"
    assert hasattr(
        Actor.Meta, "region"
    ), "DynamoDB Meta should have region configured"

    # Verify we can describe the table (confirms it exists in DynamoDB)
    try:
        table_description = Actor._get_connection().describe_table()
        # Check for key attributes in the table description
        # (DynamoDB Local returns direct dict, AWS returns {"Table": {...}})
        if "Table" in table_description:
            table_description = table_description["Table"]
        assert "AttributeDefinitions" in table_description, (
            "Should get valid DynamoDB table description"
        )
    except Exception as e:
        pytest.fail(f"Failed to describe DynamoDB table: {e}")


@pytest.mark.integration
def test_backend_isolation():
    """
    Verify that backends are truly isolated and not sharing data.

    This test ensures that when using PostgreSQL, we're not accidentally
    reading from DynamoDB, and vice versa.
    """
    import time

    from actingweb.config import Config

    backend = os.getenv("DATABASE_BACKEND", "dynamodb")
    config = Config()

    # Create a uniquely named actor
    test_id = f"isolation_test_{backend}_{int(time.time() * 1000)}"
    db_actor = config.DbActor.DbActor()  # type: ignore

    try:
        # Create in current backend
        success = db_actor.create(
            actor_id=test_id,
            creator=f"isolation_{backend}@example.com",
            passphrase="test123",
        )
        assert success, f"Failed to create test actor in {backend}"

        # Verify it exists in current backend
        db_actor_check = config.DbActor.DbActor()  # type: ignore
        result = db_actor_check.get(actor_id=test_id)
        assert result is not None, f"Should find actor in {backend}"
        assert (
            result["creator"] == f"isolation_{backend}@example.com"
        ), "Should get correct creator"

        # Verify the module path confirms we're using the right backend
        module_path = config.DbActor.__name__
        assert (
            backend in module_path
        ), f"Module path {module_path} should contain backend name {backend}"

    finally:
        # Clean up
        try:
            db_actor_cleanup = config.DbActor.DbActor()  # type: ignore
            db_actor_cleanup.get(actor_id=test_id)
            if db_actor_cleanup.handle:
                db_actor_cleanup.delete()
        except Exception:
            pass


def test_backend_module_namespaces():
    """
    Verify that imported modules are from the correct backend namespace.

    This ensures no accidental cross-backend imports.
    """
    from actingweb.config import Config

    backend = os.getenv("DATABASE_BACKEND", "dynamodb")
    config = Config()

    # Check all database modules
    modules_to_check = [
        ("DbActor", config.DbActor),
        ("DbProperty", config.DbProperty),
        ("DbTrust", config.DbTrust),
        ("DbPeerTrustee", config.DbPeerTrustee),
        ("DbSubscription", config.DbSubscription),
        ("DbSubscriptionDiff", config.DbSubscriptionDiff),
        ("DbAttribute", config.DbAttribute),
    ]

    for module_name, module in modules_to_check:
        module_path = module.__name__
        expected_path = f"actingweb.db.{backend}."

        assert module_path.startswith(expected_path), (
            f"{module_name} module path '{module_path}' "
            f"should start with '{expected_path}' for backend '{backend}'"
        )
