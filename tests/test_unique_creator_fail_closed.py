"""Creator uniqueness fails closed when enforcement is not in place (3.16).

A process that builds ``Config()`` directly, with uniqueness on and
``actingweb-unique-creators enable --apply`` not yet run, must not claim
creators against nothing: on DynamoDB the constructor no longer creates an
empty ``creators`` table, on PostgreSQL an enforced write probes for
``ux_actors_creator``. Either way the write raises ``DbError`` and an ERROR
names the remedy.
"""

from __future__ import annotations

import argparse
import logging
import os
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import CreatorTaken, DbError

REMEDY = "actingweb-unique-creators enable --apply"


def _backend() -> str:
    return os.environ.get("DATABASE_BACKEND", "dynamodb")


# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------


@pytest.fixture
def absent_creators_table() -> Iterator[str]:
    """Point ``Creator`` at a table that does not exist, with a clean ensure
    cache, and restore both afterwards (the name is process-wide)."""
    if _backend() != "dynamodb":
        pytest.skip("DynamoDB-only test")
    from actingweb.db.dynamodb import _ensure
    from actingweb.db.dynamodb.creator import Creator

    original = Creator.Meta.table_name
    name = f"test_absent_{uuid.uuid4().hex[:8]}_creators"
    _ensure.reset_ensure_cache()
    Creator.Meta.table_name = name
    try:
        yield name
    finally:
        try:
            if Creator.exists():
                Creator.delete_table()
        finally:
            Creator.Meta.table_name = original
            _ensure.reset_ensure_cache()


class TestDynamoDBConstructorCreatesNoCreatorsTable:
    def test_enforced_constructor_creates_no_table_and_create_raises(
        self, absent_creators_table: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        from actingweb.db.dynamodb.actor import DbActor
        from actingweb.db.dynamodb.creator import Creator

        db = DbActor(unique_creator=True)
        assert not Creator.exists()
        actor_id = uuid.uuid4().hex
        with caplog.at_level(logging.ERROR, logger="actingweb.db.dynamodb.actor"):
            with pytest.raises(DbError) as raised:
                db.create(
                    actor_id=actor_id,
                    creator=f"fresh-{actor_id}@example.com",
                    passphrase="x",
                )
        assert not isinstance(raised.value, CreatorTaken)
        assert str(raised.value) == "database error during actor create"
        assert not Creator.exists()
        errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
        assert any(absent_creators_table in m and REMEDY in m for m in errors), errors
        # Nothing was written: the transaction refused both items.
        assert db.get(actor_id=actor_id) is None

    def test_remedy_is_logged_without_describe_table(
        self, absent_creators_table: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A runtime role without ``DescribeTable`` still gets the remedy."""
        from actingweb.db.dynamodb.actor import DbActor
        from actingweb.db.dynamodb.creator import Creator

        db = DbActor(unique_creator=True)
        actor_id = uuid.uuid4().hex
        with (
            mock.patch.object(
                Creator, "exists", side_effect=RuntimeError("AccessDenied")
            ),
            caplog.at_level(logging.ERROR, logger="actingweb.db.dynamodb.actor"),
        ):
            with pytest.raises(DbError):
                db.create(actor_id=actor_id, creator=f"r-{actor_id}@example.com")
        assert any(
            absent_creators_table in r.getMessage() and REMEDY in r.getMessage()
            for r in caplog.records
        )

    def test_unenforced_constructor_creates_only_the_actor_table(
        self, absent_creators_table: str
    ) -> None:
        from actingweb.db.dynamodb import actor as dynamodb_actor
        from actingweb.db.dynamodb.creator import Creator

        with mock.patch.object(
            dynamodb_actor, "ensure_table", wraps=dynamodb_actor.ensure_table
        ) as spy:
            dynamodb_actor.DbActor(unique_creator=False)
            dynamodb_actor.DbActor(unique_creator=True)
        assert [c.args[0] for c in spy.call_args_list] == [
            dynamodb_actor.Actor,
            dynamodb_actor.Actor,
        ]
        assert not Creator.exists()

    def test_deletions_config_builds_no_creators_table(
        self, absent_creators_table: str
    ) -> None:
        from actingweb.db import get_actor
        from actingweb.db.dynamodb.creator import Creator
        from actingweb.maintenance import deletions

        config = deletions.make_config(argparse.Namespace(unique_creator=True))
        assert config.unique_creator
        get_actor(config)
        assert not Creator.exists()


# ---------------------------------------------------------------------------
# PostgreSQL (no server needed: the connection is a fake)
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn
        self.rowcount = 1

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.statements.append(" ".join(sql.split()))

    def fetchone(self) -> Any:
        return None


class _Conn:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


@pytest.fixture
def pg_actor(real_pg_index_probe: None) -> Iterator[tuple[Any, _Conn, mock.Mock]]:
    """The PostgreSQL actor module on a fake connection, the real probe, and
    ``creator_index_state`` mocked (default: missing)."""
    from actingweb.db.postgresql import actor as pg

    conn = _Conn()
    with (
        mock.patch.object(pg, "get_connection", lambda: conn),
        mock.patch.object(pg, "get_schema_name", return_value="public"),
        mock.patch.object(pg, "creator_index_state", return_value="missing") as state,
    ):
        yield pg, conn, state


def _inserts(conn: _Conn) -> list[str]:
    return [s for s in conn.statements if s.startswith("INSERT INTO actors")]


class TestPostgreSQLIndexProbe:
    def test_missing_index_raises_logs_and_writes_nothing(
        self, pg_actor: tuple[Any, _Conn, mock.Mock], caplog: pytest.LogCaptureFixture
    ) -> None:
        pg, conn, _ = pg_actor
        db = pg.DbActor(unique_creator=True)
        with caplog.at_level(logging.ERROR, logger=pg.__name__):
            with pytest.raises(DbError) as raised:
                db.create(actor_id="a1", creator="x@example.com", passphrase="p")
        assert not isinstance(raised.value, CreatorTaken)
        assert str(raised.value) == "database error during actor create"
        assert _inserts(conn) == []
        errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("ux_actors_creator" in m and REMEDY in m for m in errors), errors

    def test_present_index_inserts_and_is_cached(
        self, pg_actor: tuple[Any, _Conn, mock.Mock]
    ) -> None:
        pg, conn, state = pg_actor
        state.return_value = "valid"
        db = pg.DbActor(unique_creator=True)
        assert db.create(actor_id="a1", creator="x@example.com", passphrase="p")
        assert db.create(actor_id="a2", creator="y@example.com", passphrase="p")
        assert len(_inserts(conn)) == 2
        assert state.call_count == 1  # one probe per process and schema

    def test_invalid_index_is_refused(
        self, pg_actor: tuple[Any, _Conn, mock.Mock]
    ) -> None:
        pg, conn, state = pg_actor
        state.return_value = "invalid"
        with pytest.raises(DbError):
            pg.DbActor(unique_creator=True).create(
                actor_id="a1", creator="x@example.com"
            )
        assert _inserts(conn) == []

    def test_exempt_creator_and_flag_off_never_probe(
        self, pg_actor: tuple[Any, _Conn, mock.Mock]
    ) -> None:
        pg, conn, state = pg_actor
        assert pg.DbActor(unique_creator=True).create(actor_id="a1", creator="trustee")
        assert pg.DbActor(unique_creator=False).create(
            actor_id="a2", creator="x@example.com"
        )
        assert state.call_count == 0
        assert len(_inserts(conn)) == 2

    def test_absent_and_faulting_probes_are_not_cached(
        self, pg_actor: tuple[Any, _Conn, mock.Mock]
    ) -> None:
        pg, _, state = pg_actor
        db = pg.DbActor(unique_creator=True)
        state.side_effect = RuntimeError("connection refused")
        with pytest.raises(DbError):
            db.create(actor_id="a1", creator="x@example.com")
        state.side_effect = None
        state.return_value = "missing"
        with pytest.raises(DbError):
            db.create(actor_id="a1", creator="x@example.com")
        state.return_value = "valid"
        assert db.create(actor_id="a1", creator="x@example.com")
        assert state.call_count == 3

    def test_rename_and_holder_replacement_are_guarded(
        self, pg_actor: tuple[Any, _Conn, mock.Mock]
    ) -> None:
        pg, conn, _ = pg_actor
        db = pg.DbActor(unique_creator=True)
        db.handle = {"id": "a1", "creator": "old@example.com", "passphrase": "p"}
        with pytest.raises(DbError):
            db.modify(creator="new@example.com")
        with pytest.raises(DbError):
            db.replace_creator_holder(
                "a0", actor_id="a1", creator="x@example.com", passphrase="p"
            )
        assert not any(s.startswith(("UPDATE", "INSERT")) for s in conn.statements)
        # A passphrase-only modify writes no creator and is not probed.
        assert db.modify(passphrase=b"new")

    def test_missing_enforcement_uses_the_db_probe(
        self, pg_actor: tuple[Any, _Conn, mock.Mock]
    ) -> None:
        from actingweb.maintenance import unique_creators

        _, _, state = pg_actor
        config = mock.Mock(database="postgresql")
        assert "does not exist" in (unique_creators.missing_enforcement(config) or "")
        state.return_value = "valid"
        assert unique_creators.missing_enforcement(config) is None
