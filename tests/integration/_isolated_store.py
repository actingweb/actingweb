"""An isolated database for the creator-uniqueness tests.

The PostgreSQL unique index ``ux_actors_creator`` covers a whole schema, and
``actingweb-unique-creators enable`` refuses while any actors in the store
share a creator. The worker's shared store holds such actors on purpose (the
adoption and squat tests), so the uniqueness tests run against a store of
their own:

- **DynamoDB:** every model's table name is pointed at ``<prefix>uc_…`` (the
  worker prefix stays the start, so the worker cleanup removes them).
- **PostgreSQL:** ``PG_DB_PREFIX`` moves to ``<prefix>uc_``, Alembic builds
  that schema, and the pool is rebuilt (it binds a schema per connection).

The swap is process-wide, so it is only safe while nothing else in the worker
uses the database: the tests that use it share the ``unique_creator`` xdist
group, and the fixtures enter it per module and restore it on exit.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "actingweb",
    "db",
    "postgresql",
)


def _dynamodb_models() -> list[Any]:
    from actingweb.db.dynamodb.actor import Actor
    from actingweb.db.dynamodb.attribute import Attribute
    from actingweb.db.dynamodb.creator import Creator
    from actingweb.db.dynamodb.peertrustee import PeerTrustee
    from actingweb.db.dynamodb.property import Property, PropertyLegacy
    from actingweb.db.dynamodb.property_lookup import PropertyLookup, PropertyLookupV2
    from actingweb.db.dynamodb.subscription import Subscription
    from actingweb.db.dynamodb.subscription_diff import SubscriptionDiff
    from actingweb.db.dynamodb.subscription_suspension import SubscriptionSuspension
    from actingweb.db.dynamodb.trust import Trust

    return [
        Actor,
        Attribute,
        Creator,
        PeerTrustee,
        Property,
        PropertyLegacy,
        PropertyLookup,
        PropertyLookupV2,
        Subscription,
        SubscriptionDiff,
        SubscriptionSuspension,
        Trust,
    ]


def _pg_conninfo() -> str:
    return (
        f"host={os.environ['PG_DB_HOST']} port={os.environ['PG_DB_PORT']} "
        f"dbname={os.environ['PG_DB_NAME']} user={os.environ['PG_DB_USER']} "
        f"password={os.environ['PG_DB_PASSWORD']}"
    )


def _drop_schema(schema: str) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(_pg_conninfo(), autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )


@contextmanager
def isolated_store(backend: str, worker_prefix: str) -> Iterator[None]:
    """Point this process at an empty store of its own, then back."""
    from actingweb.db.dynamodb._ensure import reset_ensure_cache

    prefix = f"{worker_prefix}uc_"
    if backend == "postgresql":
        from actingweb.db.postgresql.connection import close_pool

        schema = f"{prefix}public"
        previous = os.environ.get("PG_DB_PREFIX", "")
        _drop_schema(schema)
        env = {**os.environ, "PG_DB_PREFIX": prefix, "PG_DB_SCHEMA": "public"}
        subprocess.run(
            ["poetry", "run", "alembic", "upgrade", "head"],
            cwd=MIGRATIONS_DIR,
            env=env,
            check=True,
            capture_output=True,
        )
        close_pool()
        os.environ["PG_DB_PREFIX"] = prefix
        try:
            yield
        finally:
            close_pool()
            os.environ["PG_DB_PREFIX"] = previous
            _drop_schema(schema)
        return

    models = _dynamodb_models()
    originals = {m: m.Meta.table_name for m in models}
    # The names froze at first import, under whatever AWS_DB_PREFIX was set
    # then: the unit tests' "test" when they ran first in this worker, not
    # the worker prefix. Take the frozen prefix from the actor table.
    from actingweb.db.dynamodb.actor import Actor as ActorModel

    frozen = originals[ActorModel][: -len("_actors")]
    for model in models:
        original = originals[model]
        if not original.startswith(frozen + "_"):
            raise RuntimeError(f"unexpected table name {original!r}")
        model.Meta.table_name = prefix + original[len(frozen) :]
        assert model.Meta.table_name != original
    reset_ensure_cache()
    try:
        yield
    finally:
        for model in models:
            if "uc_" in model.Meta.table_name and model.exists():
                model.delete_table()
            model.Meta.table_name = originals[model]
        reset_ensure_cache()


def wipe_store(backend: str) -> None:
    """Empty the isolated store between tests (the creators table and the
    unique index included)."""
    if backend == "postgresql":
        from actingweb.db.creator_rules import UNIQUE_INDEX_NAME
        from actingweb.db.postgresql.connection import get_connection, get_schema_name

        if "uc_" not in get_schema_name():
            raise RuntimeError(f"refusing to wipe schema {get_schema_name()!r}")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = %s "
                    "AND tablename <> 'alembic_version'",
                    (get_schema_name(),),
                )
                tables = [r[0] for r in cur.fetchall()]
                if tables:
                    cur.execute("TRUNCATE " + ", ".join(tables))
                cur.execute(f"DROP INDEX IF EXISTS {UNIQUE_INDEX_NAME}")
            conn.commit()
        return
    from actingweb.db.dynamodb._ensure import reset_ensure_cache
    from actingweb.db.dynamodb.actor import Actor

    for model in _dynamodb_models():
        # Never a shared table: only names isolated_store() set.
        if "uc_" not in model.Meta.table_name:
            raise RuntimeError(f"refusing to wipe {model.Meta.table_name!r}")
        if model.exists():
            model.delete_table()
    reset_ensure_cache()
    # The command treats a missing actor table as a misconfiguration.
    Actor.create_table(wait=True)


def enable_enforcement(config: Any) -> None:
    """``actingweb-unique-creators enable --apply`` on the isolated store."""
    from actingweb.maintenance import unique_creators

    outcome = unique_creators.enable(
        config, unique_creators.collect(config), apply=True
    )
    assert outcome in ("built", "present", "backfilled"), outcome
