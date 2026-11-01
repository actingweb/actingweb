"""An indexed property write and its lookup row succeed or fail together.

Before 3.16 a DynamoDB write that could not write its lookup row logged and
committed the property anyway, so a value could exist that reverse lookup
never found. Now the pair is one ``TransactWriteItems`` (DynamoDB) or one
database transaction (PostgreSQL), and a fault raises ``DbError`` with nothing
written. A value another actor already holds is a logged collision, not a
failure.
"""

from __future__ import annotations

import importlib
import logging
import os
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError

BACKEND = os.getenv("DATABASE_BACKEND", "dynamodb")
INDEXED = ["email"]


def _module(name: str) -> Any:
    return importlib.import_module(f"actingweb.db.{BACKEND}.{name}")


def _prop() -> Any:
    return _module("property").DbProperty(indexed_properties=list(INDEXED))


def _lookup(name: str, value: str) -> str | None:
    return _module("property_lookup").DbPropertyLookup().get(name, value)


def _stored(actor_id: str, name: str) -> str | None:
    return _prop().get(actor_id=actor_id, name=name)


@pytest.fixture
def actors() -> Iterator[list[str]]:
    """Two actors (PostgreSQL needs real rows for the lookup foreign key)."""
    ids = [f"sync-{uuid.uuid4()}", f"sync-{uuid.uuid4()}"]
    if BACKEND == "postgresql":
        for actor_id in ids:
            _module("actor").DbActor().create(
                actor_id=actor_id, creator=f"{actor_id}@x.test", passphrase=""
            )
    yield ids
    for actor_id in ids:
        lst = _module("property").DbPropertyList(indexed_properties=list(INDEXED))
        lst.fetch(actor_id=actor_id)
        lst.delete()
    if BACKEND == "postgresql":
        from actingweb.db.postgresql.connection import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            for actor_id in ids:
                cur.execute("DELETE FROM actors WHERE id = %s", (actor_id,))
            conn.commit()


def _fault_the_lookup_write() -> Any:
    """Make the lookup half of an indexed write fail."""
    if BACKEND == "dynamodb":
        from pynamodb.connection import Connection

        return mock.patch.object(
            Connection,
            "transact_write_items",
            side_effect=RuntimeError("ProvisionedThroughputExceededException"),
        )
    return mock.patch(
        "actingweb.db.postgresql.property.DbProperty._update_lookup_entry_in_transaction",
        side_effect=RuntimeError("lookup insert failed"),
    )


class TestFailsClosed:
    def test_a_lookup_fault_raises_and_leaves_no_property_row(
        self, actors: list[str]
    ) -> None:
        actor = actors[0]
        value = f"fault-{uuid.uuid4()}@x.test"
        with _fault_the_lookup_write():
            with pytest.raises(DbError):
                _prop().set(actor_id=actor, name="email", value=value)
        assert _stored(actor, "email") is None
        assert _lookup("email", value) is None

    def test_a_fault_on_a_value_change_keeps_the_old_pair(
        self, actors: list[str]
    ) -> None:
        actor = actors[0]
        old = f"old-{uuid.uuid4()}@x.test"
        assert _prop().set(actor_id=actor, name="email", value=old)
        with _fault_the_lookup_write():
            with pytest.raises(DbError):
                _prop().set(actor_id=actor, name="email", value=f"new-{uuid.uuid4()}")
        assert _stored(actor, "email") == old
        assert _lookup("email", old) == actor

    def test_a_collision_still_writes_the_property_and_logs(
        self, actors: list[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        first, second = actors
        shared = f"shared-{uuid.uuid4()}@x.test"
        assert _prop().set(actor_id=first, name="email", value=shared)
        with caplog.at_level(logging.WARNING):
            assert _prop().set(actor_id=second, name="email", value=shared)
        assert _stored(second, "email") == shared
        assert _lookup("email", shared) == first  # the first owner keeps it
        assert any(
            "LOOKUP_COLLISION" in r.message or "LOOKUP_CONFLICT" in r.message
            for r in caplog.records
        )

    def test_a_value_change_after_a_past_collision_leaves_the_owners_row(
        self, actors: list[str]
    ) -> None:
        """The second actor never owned the row for ``shared``; moving away
        from it must not delete the first actor's row (DynamoDB retries the
        transaction without the delete)."""
        first, second = actors
        shared = f"shared-{uuid.uuid4()}@x.test"
        moved = f"moved-{uuid.uuid4()}@x.test"
        assert _prop().set(actor_id=first, name="email", value=shared)
        assert _prop().set(actor_id=second, name="email", value=shared)
        assert _prop().set(actor_id=second, name="email", value=moved)
        assert _stored(second, "email") == moved
        assert _lookup("email", moved) == second
        assert _lookup("email", shared) == first

    def test_a_value_change_moves_the_lookup_row(self, actors: list[str]) -> None:
        actor = actors[0]
        old = f"old-{uuid.uuid4()}@x.test"
        new = f"new-{uuid.uuid4()}@x.test"
        assert _prop().set(actor_id=actor, name="email", value=old)
        assert _prop().set(actor_id=actor, name="email", value=new)
        assert _lookup("email", old) is None
        assert _lookup("email", new) == actor


class TestNonIndexedAndUnchanged:
    def test_a_non_indexed_write_is_a_plain_put(self, actors: list[str]) -> None:
        actor = actors[0]
        if BACKEND == "dynamodb":
            from actingweb.db.dynamodb.actor import DbActor

            with mock.patch.object(DbActor, "_run_transaction") as txn:
                assert _prop().set(actor_id=actor, name="plain", value="x")
            txn.assert_not_called()
        else:
            with mock.patch(
                "actingweb.db.postgresql.property.DbProperty._update_lookup_entry_in_transaction"
            ) as sync:
                assert _prop().set(actor_id=actor, name="plain", value="x")
            sync.assert_not_called()
        assert _stored(actor, "plain") == "x"

    def test_an_unchanged_indexed_value_skips_the_sync(self, actors: list[str]) -> None:
        actor = actors[0]
        value = f"same-{uuid.uuid4()}@x.test"
        assert _prop().set(actor_id=actor, name="email", value=value)
        if BACKEND == "dynamodb":
            with _fault_the_lookup_write():
                # Would raise if it tried to sync the lookup row again.
                assert _prop().set(actor_id=actor, name="email", value=value)
        else:
            # PostgreSQL syncs inside the one transaction and skips the
            # statements itself when the value is unchanged.
            assert _prop().set(actor_id=actor, name="email", value=value)
        assert _lookup("email", value) == actor
