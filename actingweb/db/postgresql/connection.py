"""
PostgreSQL connection pool management for ActingWeb.

Provides thread-safe connection pooling using psycopg3's built-in ConnectionPool.
Handles configuration from environment variables and supports test isolation via schema prefixes.
"""

import logging
import os
import threading
from typing import Any

# Import will be available when postgresql extra is installed
try:
    from psycopg import sql
    from psycopg_pool import ConnectionPool
except ImportError as e:
    raise ImportError(
        "PostgreSQL backend requires psycopg. "
        "Install with: poetry install --extras postgresql"
    ) from e

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_connection_string() -> str:
    """
    Build PostgreSQL connection string from environment variables.

    Environment variables:
        PG_DB_HOST: Database host (default: localhost)
        PG_DB_PORT: Database port (default: 5432)
        PG_DB_NAME: Database name (default: actingweb)
        PG_DB_USER: Database user (default: actingweb)
        PG_DB_PASSWORD: Database password (default: empty)
        PG_DB_PREFIX: Table/schema prefix for test isolation (default: empty)
        PG_DB_SCHEMA: Schema name (default: public)

    Returns:
        PostgreSQL connection string (libpq format)
    """
    host = os.getenv("PG_DB_HOST", "localhost")
    port = os.getenv("PG_DB_PORT", "5432")
    database = os.getenv("PG_DB_NAME", "actingweb")
    user = os.getenv("PG_DB_USER", "actingweb")
    password = os.getenv("PG_DB_PASSWORD", "")

    # Build connection string
    if password:
        conninfo = (
            f"host={host} port={port} dbname={database} user={user} password={password}"
        )
    else:
        conninfo = f"host={host} port={port} dbname={database} user={user}"

    logger.debug(
        f"PostgreSQL connection: host={host}, port={port}, dbname={database}, user={user}"
    )

    return conninfo


def get_schema_name() -> str:
    """
    Get schema name with worker prefix for test isolation.

    For parallel test execution, each worker uses a unique schema based on PG_DB_PREFIX.
    This is equivalent to DynamoDB's table prefix approach.

    Environment variables:
        PG_DB_PREFIX: Prefix for schema name (e.g., "test_w0_" for worker 0)
        PG_DB_SCHEMA: Base schema name (default: public)

    Returns:
        Schema name (e.g., "test_w0_public" or "public")
    """
    prefix = os.getenv("PG_DB_PREFIX", "")
    base_schema = os.getenv("PG_DB_SCHEMA", "public")

    if prefix:
        schema = f"{prefix}{base_schema}"
        logger.debug(f"Using schema: {schema} (worker isolation)")
        return schema
    else:
        return base_schema


def get_pool() -> ConnectionPool:
    """
    Get or create the global connection pool (thread-safe singleton).

    The pool is created on first access and reused for all subsequent connections.
    Configuration is read from environment variables.

    Environment variables:
        PG_POOL_MIN_SIZE: Minimum pool size (default: 2)
        PG_POOL_MAX_SIZE: Maximum pool size (default: 10)
        PG_POOL_TIMEOUT: Connection timeout in seconds (default: 30)

    Returns:
        ConnectionPool instance

    Raises:
        psycopg.OperationalError: If unable to connect to database
    """
    global _pool

    if _pool is None:
        with _pool_lock:
            # Double-check locking pattern
            if _pool is None:
                conninfo = get_connection_string()
                min_size = int(os.getenv("PG_POOL_MIN_SIZE", "2"))
                max_size = int(os.getenv("PG_POOL_MAX_SIZE", "10"))
                timeout = float(os.getenv("PG_POOL_TIMEOUT", "30.0"))

                logger.info(
                    f"Creating PostgreSQL connection pool (min={min_size}, max={max_size})"
                )

                _pool = ConnectionPool(
                    conninfo=conninfo,
                    min_size=min_size,
                    max_size=max_size,
                    timeout=timeout,
                    # Configure pool to check connections on checkout
                    check=ConnectionPool.check_connection,
                )

                logger.info("PostgreSQL connection pool created successfully")

    return _pool


def get_connection() -> Any:
    """
    Get a connection from the pool (as context manager).

    The connection is automatically returned to the pool when used as a context manager:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

    Returns:
        Connection context manager from the pool

    Raises:
        psycopg.OperationalError: If unable to get connection from pool
    """
    pool = get_pool()
    return pool.connection()


def close_pool() -> None:
    """
    Close the connection pool.

    This should be called:
    - During test cleanup
    - When shutting down the application
    - When switching database backends

    After calling this, a new pool will be created on next get_connection() call.
    """
    global _pool

    if _pool is not None:
        with _pool_lock:
            if _pool is not None:
                logger.info("Closing PostgreSQL connection pool")
                _pool.close()
                _pool = None
                logger.info("PostgreSQL connection pool closed")


def ensure_schema_exists() -> None:
    """
    Ensure the schema exists, creating it if necessary.

    This is useful for test isolation where each worker needs its own schema.
    Called automatically during table creation or can be called explicitly.

    Raises:
        psycopg.Error: If unable to create schema
    """
    schema = get_schema_name()

    # Don't try to create 'public' schema (always exists)
    if schema == "public":
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if schema exists
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = %s)",
                (schema,),
            )
            exists = cur.fetchone()[0]  # type: ignore[index]

            if not exists:
                logger.info(f"Creating schema: {schema}")
                # Schema names can't be parameterized, so we validate it first
                if not schema.replace("_", "").replace("-", "").isalnum():
                    raise ValueError(f"Invalid schema name: {schema}")
                # Use sql.Identifier for safe schema name interpolation
                cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                conn.commit()
                logger.info(f"Schema created: {schema}")


def set_search_path(conn: Any) -> None:
    """
    Set the search_path for a connection to use the configured schema.

    This should be called after getting a connection if you want to use unqualified
    table names (e.g., "actors" instead of "test_w0_public.actors").

    Args:
        conn: The connection to configure

    Raises:
        psycopg.Error: If unable to set search path
    """
    schema = get_schema_name()
    with conn.cursor() as cur:
        # Schema names can't be parameterized, validate first
        if not schema.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid schema name: {schema}")
        # Use sql.Identifier for safe schema name interpolation
        cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
