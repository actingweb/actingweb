"""Reverse lookup: a stale owner and the stale-handle race (3.16,
owner-decided plan D14 and D15).

- D14: a lookup row whose owner no longer holds the value is taken over by
  the actor that writes it, on the changed path and the unchanged (heal)
  path; an owner that still holds it keeps it (a collision).
- D15: an indexed write is conditioned on the value it read, so two writers
  that both read the same old value cannot leave the loser's lookup row.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import DbError

BACKEND = os.getenv("DATABASE_BACKEND", "dynamodb")
INDEXED = ["email"]
dynamodb_only = pytest.mark.skipif(BACKEND != "dynamodb", reason="DynamoDB")
postgresql_only = pytest.mark.skipif(BACKEND != "postgresql", reason="PostgreSQL")


def _module(name: str) -> Any:
    return importlib.import_module(f"actingweb.db.{BACKEND}.{name}")


def _prop() -> Any:
    return _module("property").DbProperty(indexed_properties=list(INDEXED))


def _lookup(value: str) -> str | None:
    return _module("property_lookup").DbPropertyLookup().get("email", value)


def _stored(actor_id: str) -> str | None:
    return _prop().get(actor_id=actor_id, name="email")


def _addr(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@x.test"


def _raw_set(actor_id: str, value: str) -> None:
    """Change the stored value without touching the lookup table (what a
    throttled, best-effort lookup delete leaves behind)."""
    if BACKEND == "dynamodb":
        from actingweb.db.dynamodb.property import Property

        Property(id=actor_id, name="email", value=value).save()
    else:
        from actingweb.db.postgresql.connection import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE properties SET value = %s WHERE id = %s AND name = 'email'",
                (value, actor_id),
            )
            conn.commit()


@pytest.fixture
def actors() -> Iterator[list[str]]:
    ids = [f"race-{uuid.uuid4()}" for _ in range(3)]
    if BACKEND == "postgresql":
        for actor_id in ids:
            _module("actor").DbActor().create(
                actor_id=actor_id, creator=f"{actor_id}@x.test", passphrase=""
            )
    else:
        from actingweb.db.dynamodb._ensure import ensure_table
        from actingweb.db.dynamodb.actor import Actor

        ensure_table(Actor)
        for actor_id in ids:
            Actor(id=actor_id, creator=f"{actor_id}@x.test", passphrase="").save()
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
    else:
        from actingweb.db.dynamodb.actor import Actor

        for actor_id in ids:
            try:
                Actor.get(actor_id).delete()
            except Exception:  # noqa: BLE001 - already gone
                pass


class TestStaleOwner:
    def test_a_row_whose_owner_moved_on_is_taken_over(
        self, actors: list[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        a, b, _ = actors
        x = _addr("x")
        assert _prop().set(actor_id=a, name="email", value=x)
        _raw_set(a, _addr("moved"))  # the lookup row for x stays with a
        with caplog.at_level(logging.WARNING):
            assert _prop().set(actor_id=b, name="email", value=x)
        assert _lookup(x) == b
        takeover = [r.message for r in caplog.records if "LOOKUP_TAKEOVER" in r.message]
        assert takeover and all(x not in m for m in takeover)

    def test_the_heal_path_takes_a_stale_row_over(self, actors: list[str]) -> None:
        a, b, _ = actors
        x = _addr("x")
        assert _prop().set(actor_id=a, name="email", value=x)
        assert _prop().set(actor_id=b, name="email", value=x)  # a collision
        assert _lookup(x) == a
        _raw_set(a, _addr("moved"))
        assert _prop().set(actor_id=b, name="email", value=x)  # unchanged
        assert _lookup(x) == b

    def test_a_takeover_releases_the_writers_old_row(self, actors: list[str]) -> None:
        a, b, _ = actors
        x, y = _addr("x"), _addr("y")
        assert _prop().set(actor_id=b, name="email", value=y)
        assert _prop().set(actor_id=a, name="email", value=x)
        _raw_set(a, _addr("moved"))
        assert _prop().set(actor_id=b, name="email", value=x)
        assert _lookup(x) == b
        assert _lookup(y) is None

    def test_an_owner_that_still_holds_the_value_keeps_it(
        self, actors: list[str]
    ) -> None:
        a, b, _ = actors
        x = _addr("x")
        assert _prop().set(actor_id=a, name="email", value=x)
        assert _prop().set(actor_id=b, name="email", value=x)
        assert _lookup(x) == a
        assert _stored(b) == x

    @dynamodb_only
    def test_a_row_left_by_a_deleted_actor_is_taken_over(
        self, actors: list[str]
    ) -> None:
        from actingweb.db.dynamodb.actor import Actor
        from actingweb.db.dynamodb.property import Property

        a, b, _ = actors
        x = _addr("x")
        assert _prop().set(actor_id=a, name="email", value=x)
        Property.get(a, "email").delete()
        Actor.get(a).delete()
        assert _prop().set(actor_id=b, name="email", value=x)
        assert _lookup(x) == b

    @dynamodb_only
    def test_an_owner_that_reacquires_during_the_takeover_keeps_the_row(
        self, actors: list[str]
    ) -> None:
        from actingweb.db.dynamodb import property_lookup

        a, b, _ = actors
        x = _addr("x")
        assert _prop().set(actor_id=a, name="email", value=x)
        # The first check reads a moved away; a holds x again by the time
        # the transaction runs (it never moved, here), so the transaction's
        # condition refuses and the next attempt sees a collision.
        real = property_lookup.owner_holds
        calls = {"n": 0}

        def first_false(*args: Any) -> bool:
            calls["n"] += 1
            return False if calls["n"] == 1 else real(*args)

        with mock.patch.object(property_lookup, "owner_holds", first_false):
            assert _prop().set(actor_id=b, name="email", value=x)
        assert _lookup(x) == a
        assert _stored(b) == x

    @postgresql_only
    def test_a_takeover_waits_for_the_owners_write_in_flight(
        self, actors: list[str]
    ) -> None:
        """The owner's re-write of the value holds its property row; the
        takeover's ``FOR SHARE`` read waits, then sees the owner holding it."""
        from actingweb.db.postgresql.connection import get_connection

        a, b, _ = actors
        x = _addr("x")
        assert _prop().set(actor_id=a, name="email", value=x)
        _raw_set(a, _addr("moved"))  # stale: a's row for x stays
        done: dict[str, Any] = {}
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM properties WHERE id = %s AND name = 'email' "
                "FOR UPDATE",
                (a,),
            )
            cur.execute(
                "UPDATE properties SET value = %s WHERE id = %s AND name = 'email'",
                (x, a),
            )

            def write() -> None:
                try:
                    done["ok"] = _prop().set(actor_id=b, name="email", value=x)
                except Exception as e:  # noqa: BLE001 - asserted below
                    done["error"] = e

            t = threading.Thread(target=write)
            t.start()
            time.sleep(0.5)
            assert t.is_alive(), "the takeover did not wait for the owner"
            conn.commit()
        t.join(timeout=10)
        assert done.get("ok") is True, done
        assert _lookup(x) == a
        assert _stored(b) == x


class TestStaleHandle:
    def test_a_stale_handle_releases_the_value_it_replaces(
        self, actors: list[str]
    ) -> None:
        a = actors[0]
        x, y, z = _addr("x"), _addr("y"), _addr("z")
        assert _prop().set(actor_id=a, name="email", value=x)
        stale = _prop()
        assert stale.get(actor_id=a, name="email") == x
        assert _prop().set(actor_id=a, name="email", value=y)
        assert stale.set(actor_id=a, name="email", value=z)
        assert _stored(a) == z
        assert _lookup(z) == a
        assert _lookup(y) is None

    def test_a_second_write_on_one_handle_succeeds_at_once(
        self, actors: list[str]
    ) -> None:
        a = actors[0]
        handle = _prop()
        assert handle.set(actor_id=a, name="email", value=_addr("one"))
        latest = _addr("two")
        assert handle.set(actor_id=a, name="email", value=latest)
        assert _lookup(latest) == a

    def test_a_stale_handle_delete_releases_the_stored_value(
        self, actors: list[str]
    ) -> None:
        a = actors[0]
        x, y = _addr("x"), _addr("y")
        assert _prop().set(actor_id=a, name="email", value=x)
        stale = _prop()
        assert stale.get(actor_id=a, name="email") == x
        assert _prop().set(actor_id=a, name="email", value=y)
        assert stale.delete()
        assert _stored(a) is None
        assert _lookup(y) is None

    def test_writes_that_keep_losing_raise(
        self, actors: list[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        a = actors[0]
        cls = type(_prop())
        if BACKEND == "dynamodb":
            losing = mock.patch.object(cls, "_write_indexed", return_value=False)
        else:
            import psycopg

            losing = mock.patch.object(
                cls,
                "_update_lookup_entry_in_transaction",
                side_effect=psycopg.errors.DeadlockDetected("deadlock"),
            )
        with losing, caplog.at_level(logging.ERROR):
            with pytest.raises(DbError):
                _prop().set(actor_id=a, name="email", value=_addr("x"))
        assert any("PROPERTY_WRITE_RACE_EXHAUSTED" in r.message for r in caplog.records)
