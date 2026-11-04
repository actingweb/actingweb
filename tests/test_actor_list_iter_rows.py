"""``DbActorList.iter_rows``: the streamed actor enumeration (3.16).

Runs on the run's backend (DynamoDB Local or the PostgreSQL test schema).
Seeded actors are deleted in ``finally``; the store is shared, so the
assertions look only at the seeded ids.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb.config import Config
from actingweb.db import get_actor, get_actor_list

BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def config() -> Config:
    return Config(database=BACKEND, unique_creator=False)


@pytest.fixture
def seeded(config: Config) -> Any:
    prefix = uuid.uuid4().hex[:8]
    ids = [f"{prefix}{i:02d}{uuid.uuid4().hex[:6]}" for i in range(5)]
    for actor_id in ids:
        assert get_actor(config).create(
            actor_id=actor_id, creator=f"{actor_id}@example.com", passphrase="secret"
        )
    try:
        yield ids
    finally:
        for actor_id in ids:
            db = get_actor(config)
            if db.get(actor_id=actor_id):
                db.delete()


def test_every_seeded_actor_appears_once_with_id_and_creator_only(
    config: Config, seeded: list[str]
) -> None:
    if BACKEND == "postgresql":
        from actingweb.db.postgresql import actor as pg

        patch = mock.patch.object(pg, "_ITER_PAGE", 2)
    else:
        patch = contextlib.nullcontext()
    with patch:
        rows = [r for r in get_actor_list(config).iter_rows() if r["id"] in seeded]
    assert sorted(r["id"] for r in rows) == sorted(seeded)
    assert all(set(r) == {"id", "creator"} for r in rows)
    assert all(r["creator"] == f"{r['id']}@example.com" for r in rows)
    if BACKEND == "postgresql":
        ids = [r["id"] for r in rows]
        assert ids == sorted(ids)  # keyset pages in id order


@pytest.mark.skipif(BACKEND != "dynamodb", reason="DynamoDB scan options")
def test_dynamodb_passes_the_scan_options_through() -> None:
    from actingweb.db.dynamodb import actor as ddb

    with mock.patch.object(ddb.Actor, "scan", return_value=iter([])) as scan:
        list(ddb.DbActorList().iter_rows(consistent=True, rate_limit=25.0))
        ddb.DbActorList().fetch()
    first, second = scan.call_args_list
    assert first.kwargs == {
        "attributes_to_get": ["id", "creator"],
        "consistent_read": True,
        "rate_limit": 25.0,
    }
    assert second.kwargs == {"attributes_to_get": ["id", "creator"]}


def test_fetch_still_returns_the_full_list(config: Config, seeded: list[str]) -> None:
    rows = get_actor_list(config).fetch()
    assert isinstance(rows, list)
    assert set(seeded) <= {r["id"] for r in rows}


@pytest.mark.skipif(BACKEND != "postgresql", reason="PostgreSQL pool")
def test_postgresql_holds_no_connection_between_pages(seeded: list[str]) -> None:
    from actingweb.db.postgresql import actor as pg

    held = {"open": 0, "max_while_yielded": 0}
    real = pg.get_connection

    class _Counting:
        def __init__(self) -> None:
            self.inner = real()

        def __enter__(self) -> Any:
            held["open"] += 1
            return self.inner.__enter__()

        def __exit__(self, *exc: Any) -> Any:
            held["open"] -= 1
            return self.inner.__exit__(*exc)

    with (
        mock.patch.object(pg, "_ITER_PAGE", 2),
        mock.patch.object(pg, "get_connection", _Counting),
    ):
        rows = pg.DbActorList().iter_rows()
        for _ in range(3):  # into the second page, then abandoned
            next(rows)
            held["max_while_yielded"] = max(held["max_while_yielded"], held["open"])
        del rows
    assert held["max_while_yielded"] == 0
    assert held["open"] == 0
