"""ActingWeb database abstraction layer.

This package provides database implementations for ActingWeb actors.
Backends are loaded dynamically via config.py based on DATABASE_BACKEND environment variable.

Supported backends:
- dynamodb: DynamoDB backend (requires 'pynamodb' package)
- postgresql: PostgreSQL backend (requires 'psycopg', 'sqlalchemy', 'alembic' packages)

Installation:
    poetry install --extras dynamodb    # DynamoDB only
    poetry install --extras postgresql  # PostgreSQL only
    poetry install --extras all         # Both backends

Note: Backend modules are not imported here to allow optional dependencies.
They are loaded dynamically by config.py when needed.
"""
