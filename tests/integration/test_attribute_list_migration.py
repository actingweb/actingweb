"""PostgreSQL revision a7b8c9d0e1f2: ``attributes.bucket_name`` and ``name``
to TEXT, and the partial index ``ix_attributes_list_rows``
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 2).

Runs on a schema of its own (``isolated_store``), in the ``unique_creator``
xdist group: the swap is process-wide.
"""

import os
import subprocess
from collections.abc import Iterator
from typing import Any

import pytest

from tests.integration._isolated_store import MIGRATIONS_DIR, isolated_store

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

pytestmark = [
    pytest.mark.xdist_group(name="unique_creator"),
    pytest.mark.skipif(
        DATABASE_BACKEND != "postgresql", reason="a PostgreSQL revision"
    ),
]

BELOW = "f6a7b8c9d0e1"
REVISION = "a7b8c9d0e1f2"
INDEX = "ix_attributes_list_rows"


def _alembic(command: str, revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["poetry", "run", "alembic", command, revision],
        cwd=MIGRATIONS_DIR,
        env=dict(os.environ),
        check=False,
        capture_output=True,
        text=True,
    )


def _sql(statement: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    from actingweb.db.postgresql.connection import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(statement, params)
            rows = cur.fetchall() if cur.description else []
        conn.commit()
    return rows


def _state() -> tuple[dict[str, str], bool | None]:
    from actingweb.db.postgresql.connection import get_schema_name

    schema = get_schema_name()
    types = dict(
        _sql(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'attributes' "
            "AND column_name IN ('bucket_name', 'name')",
            (schema,),
        )
    )
    index = _sql(
        "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relname = %s AND n.nspname = %s",
        (INDEX, schema),
    )
    return types, (index[0][0] if index else None)


@pytest.fixture
def below(docker_services, setup_database, worker_info) -> Iterator[None]:  # noqa: ARG001
    """A schema of its own, built to the revision before this one."""
    with isolated_store(
        DATABASE_BACKEND, worker_info["db_prefix"], revision=BELOW, tag="alr_"
    ):
        yield


def _close_pool() -> None:
    from actingweb.db.postgresql.connection import close_pool

    close_pool()


class TestTheRevision:
    def test_up_down_and_up_again(self, below):
        assert _state() == (
            {"bucket_name": "character varying", "name": "character varying"},
            None,
        )
        assert _alembic("upgrade", REVISION).returncode == 0
        _close_pool()
        assert _state() == ({"bucket_name": "text", "name": "text"}, True)
        assert _alembic("downgrade", BELOW).returncode == 0
        _close_pool()
        assert _state() == (
            {"bucket_name": "character varying", "name": "character varying"},
            None,
        )
        assert _alembic("upgrade", REVISION).returncode == 0
        _close_pool()
        assert _state() == ({"bucket_name": "text", "name": "text"}, True)

    def test_a_name_over_255_characters_is_stored_and_blocks_the_downgrade(self, below):
        from actingweb.db.postgresql.attribute import DbAttribute

        assert _alembic("upgrade", REVISION).returncode == 0
        _close_pool()
        name = "list:" + "n" * 120 + "-#" + "a" * 180
        DbAttribute.put_attr("actor-long", "remote:" + "p" * 32, name, "v")
        assert DbAttribute.get_attr_range(
            "actor-long", "remote:" + "p" * 32, name, name
        ) == {name: "v"}
        down = _alembic("downgrade", BELOW)
        assert down.returncode != 0
        _close_pool()
        assert _state()[0] == {"bucket_name": "text", "name": "text"}

    def test_a_failed_build_is_refused_at_start_and_rebuilt_by_the_upgrade(self, below):
        from actingweb.db.postgresql.attribute import attribute_schema_problems
        from actingweb.interface.app import ActingWebApp, AttributeSchemaNotReady

        # What a CREATE INDEX CONCURRENTLY that failed part-way through the
        # upgrade leaves: the columns widened (committed before the build),
        # an INVALID index of the revision's definition, and the revision not
        # stamped. The build is cancelled while it waits for a transaction
        # that holds a write lock on the table.
        _sql(
            "ALTER TABLE attributes ALTER COLUMN bucket_name TYPE TEXT, "
            "ALTER COLUMN name TYPE TEXT"
        )
        import psycopg
        from psycopg import sql

        from actingweb.db.postgresql.connection import get_schema_name
        from tests.integration._isolated_store import _pg_conninfo

        search_path = sql.SQL("SET search_path TO {}").format(
            sql.Identifier(get_schema_name())
        )
        with psycopg.connect(_pg_conninfo()) as holder:
            holder.execute(search_path)
            holder.execute(
                "INSERT INTO attributes (id, bucket_name, bucket, name, data) "
                "VALUES ('a', 'b:list:x', 'b', 'list:x', '1')"
            )
            with psycopg.connect(_pg_conninfo(), autocommit=True) as builder:
                builder.execute(search_path)
                builder.execute("SET statement_timeout = '1s'")
                with pytest.raises(psycopg.errors.QueryCanceled):
                    builder.execute(
                        "CREATE INDEX CONCURRENTLY ix_attributes_list_rows "
                        'ON attributes (id, bucket, name COLLATE "C") '
                        "WHERE starts_with(name, 'list:')"
                    )
            holder.rollback()
        assert _state()[1] is False
        assert any("INVALID" in p for p in attribute_schema_problems())
        app = ActingWebApp(
            aw_type="urn:actingweb:test:alr", database="postgresql", fqdn="x.test"
        )
        with pytest.raises(AttributeSchemaNotReady, match="INVALID"):
            app._check_attribute_schema_ready()  # pyright: ignore[reportPrivateUsage]
        assert _alembic("upgrade", REVISION).returncode == 0
        _close_pool()
        assert _state() == ({"bucket_name": "text", "name": "text"}, True)
        assert attribute_schema_problems() == []

    def test_check_ready_refuses_the_schema_below_the_revision(self, below):
        from actingweb.interface.app import ActingWebApp, AttributeSchemaNotReady

        app = ActingWebApp(
            aw_type="urn:actingweb:test:alr", database="postgresql", fqdn="x.test"
        )
        with pytest.raises(AttributeSchemaNotReady, match="alembic upgrade head"):
            app._check_attribute_schema_ready()  # pyright: ignore[reportPrivateUsage]


_QUERIES = {
    "range": (
        "SELECT name, data FROM attributes WHERE id = $1 AND bucket = $2 "
        "AND starts_with(name, 'list:') "
        'AND name COLLATE "C" >= $3 AND name COLLATE "C" <= $4 '
        'ORDER BY name COLLATE "C"'
    ),
    "range_keys": (
        "SELECT name, NULL FROM attributes WHERE id = $1 AND bucket = $2 "
        "AND starts_with(name, 'list:') "
        'AND name COLLATE "C" >= $3 AND name COLLATE "C" <= $4 '
        'ORDER BY name COLLATE "C"'
    ),
    "prefix": (
        "SELECT name, data FROM attributes WHERE id = $1 AND bucket = $2 "
        "AND starts_with(name, 'list:') AND starts_with(name, $3) "
        'AND name COLLATE "C" >= $3 AND name COLLATE "C" <= $4 '
        'ORDER BY name COLLATE "C"'
    ),
    "last": (
        "SELECT name FROM attributes WHERE id = $1 AND bucket = $2 "
        "AND starts_with(name, 'list:') "
        'AND name COLLATE "C" >= $3 AND name COLLATE "C" <= $4 '
        'ORDER BY name COLLATE "C" DESC LIMIT 1'
    ),
}
_PARAMS = {
    "range": "('actor-x', 'remote:p', 'list:n-#', 'list:n-#~')",
    "range_keys": "('actor-x', 'remote:p', 'list:n-#', 'list:n-#~')",
    "prefix": "('actor-x', 'remote:p', 'list:n-', 'list:n-' || chr(1114111))",
    "last": "('actor-x', 'remote:p', 'list:n-#', 'list:n-#~')",
}


class TestThePlanner:
    @pytest.mark.parametrize("query", sorted(_QUERIES))
    def test_a_generic_plan_uses_the_partial_index(self, below, query):
        """The four list queries, prepared and planned generically (as a
        pooled connection's repeated statement is), on a seeded actor whose
        bucket also holds tokens: the partial index serves them."""
        from actingweb.db.postgresql.connection import get_connection

        assert _alembic("upgrade", REVISION).returncode == 0
        _close_pool()
        rows = []
        for bucket in ("remote:p", "remote:q", "_tokens"):
            for i in range(300):
                name = f"list:n-#a{i:03d}" if bucket != "_tokens" else f"tok{i}"
                rows.append(("actor-x", f"{bucket}:{name}", bucket, name, '"v"'))
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO attributes (id, bucket_name, bucket, name, data) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    rows,
                )
                cur.execute("ANALYZE attributes")
                cur.execute("SET plan_cache_mode = force_generic_plan")
                cur.execute(f"PREPARE q AS {_QUERIES[query]}")
                cur.execute(f"EXPLAIN EXECUTE q {_PARAMS[query]}")
                plan = "\n".join(r[0] for r in cur.fetchall())
                cur.execute("DEALLOCATE q")
            conn.rollback()
        assert INDEX in plan, plan
