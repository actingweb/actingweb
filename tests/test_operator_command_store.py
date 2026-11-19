"""Every operator command prints the store it will read before its first read
(AC-9), and refuses to write on DynamoDB when ``AWS_DB_PREFIX`` is unset or
empty (AC-10): the default prefix names a real deployment, so a shell without
the application's environment would otherwise write to the wrong tables.

The commands are taken from ``pyproject.toml``'s scripts, so a new command
without an entry below fails here. A read is stopped at the backend's choke
point (PynamoDB's API call, the PostgreSQL pool) with an exception the
commands' fault folds cannot swallow.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _scripts() -> dict[str, str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return dict(data["tool"]["poetry"]["scripts"])


#: A read-only invocation of each command.
READ_ONLY: dict[str, list[str]] = {
    "actingweb-verify-property-lists": [],
    "actingweb-migrate-property-lists": [],
    "actingweb-verify-orphans": [],
    "actingweb-mark-actors-vouched": ["--dry-run"],
    "actingweb-unique-creators": ["report"],
    "actingweb-property-lookup": ["report"],
    "actingweb-deletions": ["report"],
    "actingweb-peer-state": ["report"],
}

#: Every writing mode of every command.
WRITING: list[tuple[str, list[str]]] = [
    ("actingweb-verify-property-lists", ["--repair"]),
    ("actingweb-migrate-property-lists", ["--migrate"]),
    ("actingweb-migrate-property-lists", ["--downgrade", "actor/list"]),
    ("actingweb-mark-actors-vouched", []),
    ("actingweb-unique-creators", ["resolve", "--apply"]),
    ("actingweb-unique-creators", ["enable", "--apply"]),
    ("actingweb-unique-creators", ["disable", "--apply"]),
    ("actingweb-unique-creators", ["creator-to-email", "--apply"]),
    ("actingweb-property-lookup", ["backfill", "--apply"]),
    ("actingweb-property-lookup", ["mark-complete", "--apply"]),
    ("actingweb-property-lookup", ["unmark", "--apply"]),
    ("actingweb-deletions", ["resume", "--apply"]),
    ("actingweb-deletions", ["clear", "some-actor", "--apply"]),
    ("actingweb-peer-state", ["prune", "--apply"]),
]


class _FirstRead(BaseException):
    """Raised at the first store access; not an ``Exception``, so no fault
    fold in a command turns it into an exit status."""


def _main(script: str) -> Any:
    target = _scripts()[script]
    module, func = target.split(":")
    return getattr(importlib.import_module(module), func)


@pytest.fixture
def first_read(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Stop at the first store access; record what was printed by then."""
    seen: list[str] = []

    def stop(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        seen.append(capsys.readouterr().out)
        raise _FirstRead

    import botocore.client
    import psycopg
    import psycopg_pool
    from pynamodb.connection.base import Connection

    monkeypatch.setattr(Connection, "_make_api_call", stop)
    monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", stop)
    monkeypatch.setattr(psycopg, "connect", stop)
    monkeypatch.setattr(psycopg.Connection, "connect", stop)
    monkeypatch.setattr(psycopg_pool.ConnectionPool, "__init__", stop)
    monkeypatch.setattr(psycopg_pool.ConnectionPool, "connection", stop)
    return seen


def _run(script: str, argv: list[str]) -> int | None:
    """The exit status, or None when the command reached a store read."""
    try:
        result = _main(script)(argv)
    except _FirstRead:
        return None
    except SystemExit as e:
        return int(e.code or 0)
    return int(result)


def test_every_command_is_covered() -> None:
    assert set(_scripts()) == set(READ_ONLY)
    # verify-orphans has no writing mode.
    assert {s for s, _ in WRITING} == set(_scripts()) - {"actingweb-verify-orphans"}


@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
@pytest.mark.parametrize("script", sorted(READ_ONLY))
def test_every_command_prints_the_store_first(
    script: str,
    backend: str,
    first_read: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", backend)
    monkeypatch.setenv("AWS_DB_PREFIX", "ac9prefix")
    monkeypatch.setenv("AWS_DB_HOST", "http://localhost:8001")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-north-1")
    monkeypatch.setenv("PG_DB_HOST", "pghost.example")
    monkeypatch.setenv("PG_DB_NAME", "ac9db")
    monkeypatch.setenv("PG_DB_SCHEMA", "ac9schema")
    monkeypatch.setenv("PG_DB_PREFIX", "ac9pg_")
    status = _run(script, READ_ONLY[script])
    assert status is None, f"{script} exited {status} before reading the store"
    banner = first_read[0]
    assert f"backend={backend}" in banner
    if backend == "dynamodb":
        for part in (
            "prefix=ac9prefix",
            "endpoint=http://localhost:8001",
            "region=eu-north-1",
        ):
            assert part in banner
    else:
        for part in (
            "host=pghost.example",
            "db=ac9db",
            "schema=ac9schema",
            "prefix=ac9pg_",
        ):
            assert part in banner


@pytest.mark.parametrize(("script", "argv"), WRITING)
def test_writing_without_a_prefix_is_refused(
    script: str,
    argv: list[str],
    first_read: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "dynamodb")
    monkeypatch.delenv("AWS_DB_PREFIX", raising=False)
    assert _run(script, argv) == 2
    assert not first_read, "the store was read"
    err = capsys.readouterr().err
    assert "AWS_DB_PREFIX" in err and "demo_actingweb" in err


def test_an_empty_prefix_is_unset(
    first_read: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "dynamodb")
    monkeypatch.setenv("AWS_DB_PREFIX", "")
    assert _run("actingweb-property-lookup", ["backfill", "--apply"]) == 2
    assert not first_read
    assert "AWS_DB_PREFIX" in capsys.readouterr().err


@pytest.mark.parametrize("script", sorted(READ_ONLY))
def test_dry_runs_are_not_refused(
    script: str, first_read: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "dynamodb")
    monkeypatch.delenv("AWS_DB_PREFIX", raising=False)
    assert _run(script, READ_ONLY[script]) is None
    assert "prefix=demo_actingweb" in first_read[0]


@pytest.mark.parametrize(("script", "argv"), WRITING)
def test_postgresql_is_not_refused(
    script: str,
    argv: list[str],
    first_read: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "postgresql")
    monkeypatch.delenv("AWS_DB_PREFIX", raising=False)
    assert _run(script, argv) is None
