import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# Import our schema models for autogenerate support
from actingweb.db.postgresql.schema import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url with environment variable if set
db_url = os.getenv("PG_DB_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)
else:
    # Build URL from individual environment variables
    host = os.getenv("PG_DB_HOST", "localhost")
    port = os.getenv("PG_DB_PORT", "5432")
    database = os.getenv("PG_DB_NAME", "actingweb")
    user = os.getenv("PG_DB_USER", "actingweb")
    password = os.getenv("PG_DB_PASSWORD", "")

    # Use postgresql+psycopg dialect (psycopg3, not psycopg2)
    if password:
        db_url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    else:
        db_url = f"postgresql+psycopg://{user}@{host}:{port}/{database}"

    config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Get schema name for table creation (supports test isolation)
    schema = os.getenv("PG_DB_PREFIX", "") + os.getenv("PG_DB_SCHEMA", "public")

    # Ensure schema exists before opening migration transaction
    if schema != "public":
        # Validate schema name
        if not schema.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid schema name: {schema}")
        # Create schema in a separate autocommit connection
        with connectable.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as schema_conn:
            schema_conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

    with connectable.begin() as connection:
        # Set search path to use the correct schema
        if schema:
            connection.execute(text(f"SET search_path TO {schema}"))

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=schema if schema != "public" else None,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
