"""``DbActor.rename_creator`` on both backends (3.16, email-as-creator
Phase 1).

One operation moves the creator, the uniqueness record and writes to the
``_internal`` bucket, each with its own condition, and checks the vouch
marker; any failed condition cancels all of it. Runs on the isolated store
in the ``unique_creator`` group, as the other creator-uniqueness suites do.
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any
from unittest import mock

import pytest

from actingweb.db import get_actor, get_attribute
from actingweb.db.creator_rename import AttrWrite, RenameOutcome
from actingweb.db.exceptions import AttributeKeyCollision, CreatorTaken, DbError

from .conftest import DATABASE_BACKEND

pytestmark = pytest.mark.xdist_group(name="unique_creator")

DYNAMODB = DATABASE_BACKEND == "dynamodb"
IB = "_internal"


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _flag_off(config: Any) -> Any:
    off = copy.copy(config)
    off.unique_creator = False
    return off


def _actor(config: Any, creator: str, **internal: Any) -> str:
    # The isolated store creates the attributes table on first use; the
    # rename's transaction writes to it whatever touched it before.
    get_attribute(config)
    actor_id = uuid.uuid4().hex
    assert get_actor(config).create(actor_id=actor_id, creator=creator, passphrase="pw")
    for name, value in internal.items():
        get_attribute(config).set_attr(actor_id, IB, name, value)
    return actor_id


def _vouched(config: Any, creator: str) -> str:
    return _actor(
        config, creator, auth_method="google", email=creator, vouched_creator=creator
    )


def _row(config: Any, actor_id: str) -> dict[str, Any] | None:
    return get_actor(config).get(actor_id=actor_id)


def _internal(config: Any, actor_id: str) -> dict[str, Any]:
    bucket = get_attribute(config).get_bucket(actor_id, IB) or {}
    return {name: entry["data"] for name, entry in bucket.items()}


def _holder(config: Any, creator: str) -> str | None:
    return get_actor(config).get_creator_holder(creator)


def _rename(config: Any, actor_id: str, expected: str | None, creator: str, **kw: Any):
    return get_actor(config).rename_creator(
        actor_id, expected=expected, creator=creator, **kw
    )


def _full(new: str, old: str) -> dict[str, Any]:
    return {
        "internal": (
            AttrWrite("email", new, "equals", old),
            AttrWrite("vouched_creator", new),
            AttrWrite("vouched_creator_pending", None),
        ),
        "marker": "google",
    }


def _snapshot(config: Any, actor_id: str) -> tuple[Any, ...]:
    return (_row(config, actor_id), _internal(config, actor_id))


class TestApplied:
    def test_the_creator_record_and_attributes_move_together(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        get_attribute(enforced_store).set_attr(aid, IB, "vouched_creator_pending", old)
        outcome = _rename(enforced_store, aid, old, new, **_full(new, old))
        assert outcome is RenameOutcome.APPLIED
        assert _row(enforced_store, aid)["creator"] == new  # type: ignore[index]
        stored = _internal(enforced_store, aid)
        assert stored["email"] == new
        assert stored["vouched_creator"] == new
        assert "vouched_creator_pending" not in stored
        assert stored["auth_method"] == "google"
        assert _holder(enforced_store, new) == aid
        assert _holder(enforced_store, old) is None

    def test_the_same_creator_runs_only_the_attribute_writes(
        self, enforced_store: Any
    ) -> None:
        old = _email()
        aid = _vouched(enforced_store, old)
        outcome = _rename(
            enforced_store, aid, old, old, internal=(AttrWrite("note", "x"),)
        )
        assert outcome is RenameOutcome.APPLIED
        assert _internal(enforced_store, aid)["note"] == "x"
        assert _holder(enforced_store, old) == aid

    def test_an_exempt_target_moves_no_record(self, enforced_store: Any) -> None:
        old = _email()
        aid = _vouched(enforced_store, old)
        assert _rename(enforced_store, aid, old, "trustee") is RenameOutcome.APPLIED
        assert _row(enforced_store, aid)["creator"] == "trustee"  # type: ignore[index]
        assert _holder(enforced_store, old) is None

    def test_with_uniqueness_off_the_row_and_attributes_move(
        self, fresh_store: Any
    ) -> None:
        off = _flag_off(fresh_store)
        old, new = _email(), _email()
        aid = _vouched(off, old)
        assert _rename(off, aid, old, new, **_full(new, old)) is RenameOutcome.APPLIED
        assert _row(off, aid)["creator"] == new  # type: ignore[index]
        assert _internal(off, aid)["email"] == new

    def test_the_same_call_twice_changes_nothing_the_second_time(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        assert _rename(enforced_store, aid, old, new, **_full(new, old)) is (
            RenameOutcome.APPLIED
        )
        before = _snapshot(enforced_store, aid)
        assert _rename(enforced_store, aid, old, new, **_full(new, old)) is (
            RenameOutcome.ROW_CHANGED
        )
        assert _snapshot(enforced_store, aid) == before

    def test_a_handle_is_updated_after_the_rename(self, enforced_store: Any) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        db = get_actor(enforced_store)
        db.get(actor_id=aid)
        assert db.rename_creator(aid, expected=old, creator=new) is (
            RenameOutcome.APPLIED
        )
        # A following modify on the same handle is conditioned on the new
        # creator, not the stale one.
        assert db.modify(passphrase=b"rotated")
        assert _row(enforced_store, aid)["passphrase"] == "rotated"  # type: ignore[index]

    @pytest.mark.parametrize("unique", [True, False])
    def test_a_passphrase_rotated_since_the_load_survives(
        self, enforced_store: Any, unique: bool
    ) -> None:
        config = enforced_store if unique else _flag_off(enforced_store)
        old, new = _email(), _email()
        aid = _vouched(config, old)
        loaded = get_actor(config)
        loaded.get(actor_id=aid)
        other = get_actor(config)
        other.get(actor_id=aid)
        assert other.modify(passphrase=b"rotated")
        assert loaded.rename_creator(aid, expected=old, creator=new) is (
            RenameOutcome.APPLIED
        )
        row = _row(config, aid)
        assert row == {"id": aid, "creator": new, "passphrase": "rotated"}


class TestRefused:
    def test_a_wrong_expected_creator_changes_nothing(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        before = _snapshot(enforced_store, aid)
        outcome = _rename(enforced_store, aid, _email(), new, **_full(new, old))
        assert outcome is RenameOutcome.ROW_CHANGED
        assert _snapshot(enforced_store, aid) == before
        assert _holder(enforced_store, new) is None

    def test_a_deleted_actor_is_not_re_created(self, enforced_store: Any) -> None:
        get_attribute(enforced_store)
        aid = uuid.uuid4().hex
        new = _email()
        outcome = _rename(
            enforced_store, aid, None, new, internal=(AttrWrite("email", new),)
        )
        assert outcome is RenameOutcome.ROW_CHANGED
        assert _row(enforced_store, aid) is None
        assert _internal(enforced_store, aid) == {}
        assert _holder(enforced_store, new) is None

    def test_a_creator_another_actor_holds_raises_and_changes_nothing(
        self, enforced_store: Any
    ) -> None:
        old, taken = _email(), _email()
        aid = _vouched(enforced_store, old)
        other = _actor(enforced_store, taken)
        before = _snapshot(enforced_store, aid)
        with pytest.raises(CreatorTaken):
            _rename(enforced_store, aid, old, taken, **_full(taken, old))
        assert _snapshot(enforced_store, aid) == before
        assert _holder(enforced_store, taken) == other
        assert _holder(enforced_store, old) == aid

    @pytest.mark.parametrize("marker", ["factory", None])
    def test_a_changed_or_missing_marker_changes_nothing(
        self, enforced_store: Any, marker: str | None
    ) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        get_attribute(enforced_store).set_attr(aid, IB, "auth_method", marker)
        before = _snapshot(enforced_store, aid)
        outcome = _rename(enforced_store, aid, old, new, **_full(new, old))
        assert outcome is RenameOutcome.MARKER_CHANGED
        assert _snapshot(enforced_store, aid) == before
        assert _holder(enforced_store, new) is None

    def test_the_row_is_decided_before_the_marker(self, enforced_store: Any) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        get_attribute(enforced_store).set_attr(aid, IB, "auth_method", "factory")
        outcome = _rename(enforced_store, aid, _email(), new, **_full(new, old))
        assert outcome is RenameOutcome.ROW_CHANGED

    def test_an_absent_write_over_a_live_row_changes_nothing(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        before = _snapshot(enforced_store, aid)
        outcome = _rename(
            enforced_store, aid, old, new, internal=(AttrWrite("email", new, "absent"),)
        )
        assert outcome is RenameOutcome.ATTR_CONDITION
        assert _snapshot(enforced_store, aid) == before
        assert _holder(enforced_store, new) is None

    def test_an_equals_write_on_another_value_changes_nothing(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        before = _snapshot(enforced_store, aid)
        outcome = _rename(
            enforced_store,
            aid,
            old,
            new,
            internal=(AttrWrite("email", new, "equals", _email()),),
        )
        assert outcome is RenameOutcome.ATTR_CONDITION
        assert _snapshot(enforced_store, aid) == before

    def test_an_absent_write_over_an_expired_row_applies(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        aid = _actor(enforced_store, old)
        _expired_row(aid, "seed", "stale")
        outcome = _rename(
            enforced_store,
            aid,
            old,
            new,
            internal=(AttrWrite("seed", "fresh", "absent"),),
        )
        assert outcome is RenameOutcome.APPLIED
        assert _internal(enforced_store, aid)["seed"] == "fresh"

    @pytest.mark.parametrize("when", ["always", "absent", "equals"])
    def test_a_key_another_bucket_holds_is_a_collision(
        self, enforced_store: Any, when: str
    ) -> None:
        # "_internal" + "x:y" and "_internal:x" + "y" share a key.
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        get_attribute(enforced_store).set_attr(aid, IB + ":x", "y", "theirs")
        before = _snapshot(enforced_store, aid)
        write = AttrWrite("x:y", "mine", when, "theirs" if when == "equals" else None)  # type: ignore[arg-type]
        with pytest.raises(AttributeKeyCollision):
            _rename(enforced_store, aid, old, new, internal=(write,))
        assert _snapshot(enforced_store, aid) == before
        assert (
            get_attribute(enforced_store).get_bucket(aid, IB + ":x")["y"][  # type: ignore[index]
                "data"
            ]
            == "theirs"
        )
        assert _holder(enforced_store, new) is None

    def test_a_changed_row_is_decided_before_a_collision(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        get_attribute(enforced_store).set_attr(aid, IB + ":x", "y", "theirs")
        outcome = _rename(
            enforced_store, aid, _email(), new, internal=(AttrWrite("x:y", "mine"),)
        )
        assert outcome is RenameOutcome.ROW_CHANGED

    def test_a_changed_marker_is_decided_before_a_collision(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        get_attribute(enforced_store).set_attr(aid, IB + ":x", "y", "theirs")
        outcome = _rename(
            enforced_store,
            aid,
            old,
            new,
            internal=(AttrWrite("x:y", "mine"),),
            marker="factory",
        )
        assert outcome is RenameOutcome.MARKER_CHANGED

    @pytest.mark.parametrize(
        ("internal", "marker"),
        [
            ((AttrWrite("email", "a"), AttrWrite("email", "b")), None),
            ((AttrWrite("auth_method", "google"),), "google"),
        ],
    )
    def test_a_call_it_cannot_run_raises_value_error(
        self, enforced_store: Any, internal: tuple[AttrWrite, ...], marker: str | None
    ) -> None:
        old = _email()
        aid = _vouched(enforced_store, old)
        with pytest.raises(ValueError):
            _rename(
                enforced_store, aid, old, _email(), internal=internal, marker=marker
            )


class TestFaults:
    def test_a_fault_after_the_actor_row_was_written_changes_nothing(
        self, enforced_store: Any
    ) -> None:
        """PostgreSQL: the actor row has been updated inside the
        transaction when the attribute write faults; the explicit rollback
        leaves neither. (A DynamoDB transaction has no such midpoint.)"""
        if DYNAMODB:
            pytest.skip("one statement per transaction on DynamoDB")
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        before = _snapshot(enforced_store, aid)

        def fail_attribute_write(sql: str, _cur: Any) -> None:
            if "UPDATE attributes" in sql or "INSERT INTO attributes" in sql:
                raise RuntimeError("connection lost (simulated)")

        with _pg_hooked(before_execute=fail_attribute_write):
            with pytest.raises(DbError):
                _rename(enforced_store, aid, old, new, **_full(new, old))
        assert _snapshot(enforced_store, aid) == before

    def test_a_fault_raises_and_changes_nothing(self, enforced_store: Any) -> None:
        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        before = _snapshot(enforced_store, aid)
        with _backend_down():
            with pytest.raises(DbError) as raised:
                _rename(enforced_store, aid, old, new, **_full(new, old))
        assert not isinstance(raised.value, CreatorTaken)
        assert _snapshot(enforced_store, aid) == before
        assert _holder(enforced_store, new) is None

    def test_a_failed_release_of_the_old_record_still_answers_applied(
        self, enforced_store: Any
    ) -> None:
        if not DYNAMODB:
            pytest.skip("PostgreSQL holds no separate record")
        from actingweb.db.dynamodb import actor as dynamodb_actor

        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        with mock.patch.object(
            dynamodb_actor.Creator, "delete", side_effect=RuntimeError("throttled")
        ):
            assert _rename(enforced_store, aid, old, new) is RenameOutcome.APPLIED
        assert _holder(enforced_store, new) == aid
        # The leftover still names this actor; report lists it.
        assert _holder(enforced_store, old) == aid


class TestConcurrency:
    def test_crossing_renames_end_coherently(self, enforced_store: Any) -> None:
        for _ in range(5):
            x, y = _email(), _email()
            a = _actor(enforced_store, x)
            b = _actor(enforced_store, y)
            results = _together(
                partial(_rename, enforced_store, a, x, y),
                partial(_rename, enforced_store, b, y, x),
            )
            for r in results:
                assert isinstance(r, RenameOutcome | CreatorTaken), r
            row_a, row_b = _row(enforced_store, a), _row(enforced_store, b)
            assert row_a and row_b and row_a["creator"] != row_b["creator"]

    def test_a_rename_racing_a_bucket_delete_does_not_fault(
        self, enforced_store: Any
    ) -> None:
        for _ in range(5):
            old, new = _email(), _email()
            aid = _vouched(enforced_store, old)
            results = _together(
                partial(_rename, enforced_store, aid, old, new, **_full(new, old)),
                partial(get_attribute(enforced_store).delete_bucket, aid, IB),
            )
            assert not any(isinstance(r, BaseException) for r in results), results

    def test_an_absent_key_written_after_the_lock_is_a_lost_condition(
        self, enforced_store: Any
    ) -> None:
        """PostgreSQL: the locking read cannot lock a key with no row. A
        sign-in's seed that commits between that read and the rename's own
        write must still win, as it does on DynamoDB."""
        if DYNAMODB:
            pytest.skip("the condition is evaluated by DynamoDB itself")
        old, new = _email(), _email()
        aid = _actor(enforced_store, old, auth_method="google")

        def seed_after_lock(sql: str, _cur: Any) -> None:
            if "FOR UPDATE" in sql:
                get_attribute(enforced_store).set_attr(aid, IB, "email", old)

        with _pg_hooked(after_execute=seed_after_lock):
            outcome = _rename(
                enforced_store,
                aid,
                old,
                new,
                internal=(AttrWrite("email", new, "absent"),),
                marker="google",
            )
        assert outcome is RenameOutcome.ATTR_CONDITION
        assert _row(enforced_store, aid)["creator"] == old  # type: ignore[index]
        assert _internal(enforced_store, aid)["email"] == old

    def test_an_unvouch_holding_the_marker_row_is_seen_by_the_rename(
        self, enforced_store: Any
    ) -> None:
        """PostgreSQL: the rename's locking read waits for a transaction
        that holds the marker row and then reads what it committed."""
        if DYNAMODB:
            pytest.skip("PostgreSQL row locks")
        from actingweb.db.postgresql.connection import get_connection

        old, new = _email(), _email()
        aid = _vouched(enforced_store, old)
        locked = threading.Event()

        def unvouch() -> None:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE attributes SET data = %s::jsonb "
                        "WHERE id = %s AND bucket_name = %s",
                        ('"factory"', aid, IB + ":auth_method"),
                    )
                    locked.set()
                    time.sleep(0.5)
                conn.commit()

        t = threading.Thread(target=unvouch)
        t.start()
        locked.wait(5)
        outcome = _rename(enforced_store, aid, old, new, **_full(new, old))
        t.join()
        assert outcome is RenameOutcome.MARKER_CHANGED
        assert _row(enforced_store, aid)["creator"] == old  # type: ignore[index]


def _together(*calls: Any) -> list[Any]:
    """Run the calls at once on threads; each one's result or exception."""
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)

    def run(i: int, call: Any) -> None:
        barrier.wait()
        try:
            results[i] = call()
        except BaseException as e:  # noqa: BLE001
            results[i] = e

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@contextmanager
def _pg_hooked(
    *, before_execute: Any = None, after_execute: Any = None
) -> Iterator[None]:
    """PostgreSQL: run a hook around each statement the rename executes
    (the attribute backend's own connections are untouched)."""
    from actingweb.db.postgresql import actor as pg_actor

    real = pg_actor.get_connection

    class _Cursor:
        def __init__(self, cur: Any) -> None:
            self._cur = cur

        def __enter__(self) -> _Cursor:
            self._cur.__enter__()
            return self

        def __exit__(self, *exc: Any) -> Any:
            return self._cur.__exit__(*exc)

        def execute(self, sql: str, params: Any = None) -> Any:
            if before_execute:
                before_execute(sql, self._cur)
            result = self._cur.execute(sql, params)
            if after_execute:
                after_execute(sql, self._cur)
            return result

        def __getattr__(self, name: str) -> Any:
            return getattr(self._cur, name)

    @contextmanager
    def hooked() -> Iterator[Any]:
        with real() as conn:

            class _Conn:
                def cursor(self) -> _Cursor:
                    return _Cursor(conn.cursor())

                def __getattr__(self, name: str) -> Any:
                    return getattr(conn, name)

            yield _Conn()

    with mock.patch.object(pg_actor, "get_connection", hooked):
        yield


@contextmanager
def _backend_down() -> Iterator[None]:
    if DYNAMODB:
        from actingweb.db.dynamodb import actor as dynamodb_actor

        def down(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("ProvisionedThroughputExceededException (simulated)")

        with mock.patch.object(dynamodb_actor, "TransactWrite", down):
            yield
        return
    from actingweb.db.postgresql import actor as pg_actor

    def refused(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("connection refused (simulated)")

    with mock.patch.object(pg_actor, "get_connection", refused):
        yield


def _expired_row(actor_id: str, name: str, value: Any) -> None:
    past = int(time.time()) - 3600
    if DYNAMODB:
        from actingweb.db.dynamodb.attribute import Attribute

        Attribute(
            id=actor_id,
            bucket_name=IB + ":" + name,
            bucket=IB,
            name=name,
            data=value,
            ttl_timestamp=past,
        ).save()
        return
    import json

    from actingweb.db.postgresql.connection import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attributes (id, bucket_name, bucket, name, data, "
                "ttl_timestamp) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    actor_id,
                    IB + ":" + name,
                    IB,
                    name,
                    json.dumps(value),
                    past,
                ),
            )
        conn.commit()
