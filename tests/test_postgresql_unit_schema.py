"""The PostgreSQL unit-run schema helper (tests/_pg_schema.py)."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from tests import _pg_schema

pytestmark = pytest.mark.skipif(
    os.environ.get("DATABASE_BACKEND", "dynamodb") != "postgresql",
    reason="PostgreSQL only",
)


def test_a_schema_at_head_runs_no_upgrade() -> None:
    # The session fixture has already migrated public, so it is at head now.
    with mock.patch.object(_pg_schema, "run_upgrade") as upgrade:
        assert _pg_schema.ensure_postgresql_schema() is False
    upgrade.assert_not_called()


def test_a_schema_behind_head_runs_one_upgrade() -> None:
    with (
        mock.patch.object(_pg_schema, "head_revisions", return_value={"zzz"}),
        mock.patch.object(_pg_schema, "run_upgrade") as upgrade,
    ):
        assert _pg_schema.ensure_postgresql_schema() is True
    upgrade.assert_called_once_with()


def test_a_missing_version_table_counts_as_behind() -> None:
    import psycopg

    cur = mock.Mock()
    cur.execute.side_effect = psycopg.errors.UndefinedTable("no alembic_version")
    assert _pg_schema.current_revisions(cur) == set()


def test_the_upgrade_targets_public_whatever_the_shell_prefix() -> None:
    with (
        mock.patch.dict(os.environ, {"PG_DB_PREFIX": "test_w3_", "PG_DB_SCHEMA": "x"}),
        mock.patch.object(_pg_schema.subprocess, "run") as run,
    ):
        _pg_schema.run_upgrade()
    env = run.call_args.kwargs["env"]
    assert "PG_DB_PREFIX" not in env
    assert env["PG_DB_SCHEMA"] == "public"
    assert run.call_args.kwargs["check"] is True
