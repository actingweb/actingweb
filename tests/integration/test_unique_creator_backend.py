"""Creator uniqueness in the actor backends (3.16, PR 2 Phase 3).

With ``with_unique_creator()`` the database holds one actor per non-exempt
creator: DynamoDB through the ``creators`` table written in the same
transaction as the actor, PostgreSQL through the partial unique index
``ux_actors_creator``. Runs on an isolated store
(``tests/integration/_isolated_store.py``), in the ``unique_creator`` xdist
group because the store swap is process-wide.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest

from actingweb.db import get_actor
from actingweb.db.creator_rules import dup_value
from actingweb.db.exceptions import CreatorTaken

from .conftest import DATABASE_BACKEND

pytestmark = pytest.mark.xdist_group(name="unique_creator")

DYNAMODB = DATABASE_BACKEND == "dynamodb"


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _id() -> str:
    return uuid.uuid4().hex


def _create(config: Any, creator: str, actor_id: str | None = None) -> str:
    actor_id = actor_id or _id()
    assert get_actor(config).create(actor_id=actor_id, creator=creator, passphrase="pw")
    return actor_id


def _holder(config: Any, creator: str) -> str | None:
    return get_actor(config).get_creator_holder(creator)


def _stored_creator(config: Any, actor_id: str) -> str | None:
    row = get_actor(config).get(actor_id=actor_id)
    return row["creator"] if row else None


def _flag_off(config: Any) -> Any:
    """A copy of the config with the flag off: an old process, or a
    rolled-back flag."""
    import copy

    off = copy.copy(config)
    off.unique_creator = False
    return off


class TestCreates:
    def test_a_second_create_for_the_creator_raises(self, enforced_store: Any) -> None:
        creator = _email()
        first = _create(enforced_store, creator)
        second = _id()
        with pytest.raises(CreatorTaken):
            get_actor(enforced_store).create(
                actor_id=second, creator=creator, passphrase="pw"
            )
        assert get_actor(enforced_store).get(actor_id=second) is None
        assert _holder(enforced_store, creator) == first

    def test_the_creator_compares_lowercased_for_addresses(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        _create(enforced_store, creator)
        with pytest.raises(CreatorTaken):
            get_actor(enforced_store).create(
                actor_id=_id(), creator=creator.upper(), passphrase="pw"
            )

    def test_of_concurrent_creates_exactly_one_wins(self, enforced_store: Any) -> None:
        creator = _email()
        results: list[str] = []
        barrier = threading.Barrier(4)

        def attempt() -> None:
            barrier.wait()
            try:
                ok = get_actor(enforced_store).create(
                    actor_id=_id(), creator=creator, passphrase="pw"
                )
                results.append("created" if ok else "false")
            except CreatorTaken:
                results.append("taken")
            except Exception as e:  # noqa: BLE001 - recorded for the assert
                results.append(f"error:{type(e).__name__}")

        threads = [threading.Thread(target=attempt) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == ["created", "taken", "taken", "taken"], results

    @pytest.mark.parametrize("exempt", ["Trustee", "creator", ""])
    def test_exempt_values_accept_many(self, enforced_store: Any, exempt: str) -> None:
        if DYNAMODB and not exempt:
            pytest.skip("DynamoDB cannot store an empty creator (its index key)")
        ids = [_create(enforced_store, exempt) for _ in range(3)]
        for actor_id in ids:
            assert get_actor(enforced_store).get(actor_id=actor_id)

    def test_a_delete_frees_the_creator(self, enforced_store: Any) -> None:
        creator = _email()
        first = _create(enforced_store, creator)
        db = get_actor(enforced_store)
        assert db.get(actor_id=first)
        assert db.delete() is True
        assert _holder(enforced_store, creator) is None
        second = _create(enforced_store, creator)
        assert _holder(enforced_store, creator) == second


class TestChanges:
    def test_a_change_moves_the_creator(self, enforced_store: Any) -> None:
        old, new = _email(), _email()
        actor_id = _create(enforced_store, old)
        db = get_actor(enforced_store)
        db.get(actor_id=actor_id)
        assert db.modify(creator=new) is True
        assert _stored_creator(enforced_store, actor_id) == new
        assert _holder(enforced_store, new) == actor_id
        assert _holder(enforced_store, old) is None
        # The old address is free again.
        _create(enforced_store, old)

    def test_a_change_to_a_taken_creator_leaves_both_actors(
        self, enforced_store: Any
    ) -> None:
        first_creator, second_creator = _email(), _email()
        first = _create(enforced_store, first_creator)
        second = _create(enforced_store, second_creator)
        db = get_actor(enforced_store)
        db.get(actor_id=second)
        with pytest.raises(CreatorTaken):
            db.modify(creator=first_creator)
        assert _stored_creator(enforced_store, first) == first_creator
        assert _stored_creator(enforced_store, second) == second_creator
        assert _holder(enforced_store, first_creator) == first
        assert _holder(enforced_store, second_creator) == second

    def test_exempt_to_non_exempt_claims_the_creator(self, enforced_store: Any) -> None:
        creator = _email()
        actor_id = _create(enforced_store, "trustee")
        db = get_actor(enforced_store)
        db.get(actor_id=actor_id)
        assert db.modify(creator=creator) is True
        assert _holder(enforced_store, creator) == actor_id

    def test_non_exempt_to_exempt_releases_the_creator(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        actor_id = _create(enforced_store, creator)
        db = get_actor(enforced_store)
        db.get(actor_id=actor_id)
        assert db.modify(creator="trustee") is True
        assert _holder(enforced_store, creator) is None
        assert _stored_creator(enforced_store, actor_id) == "trustee"

    @pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
    def test_a_change_with_its_record_missing_still_lands(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb.creator import Creator

        old, new = _email(), _email()
        actor_id = _create(enforced_store, old)
        Creator(creator=old).delete()
        db = get_actor(enforced_store)
        db.get(actor_id=actor_id)
        assert db.modify(creator=new) is True
        assert _holder(enforced_store, new) == actor_id

    def test_a_passphrase_only_change_keeps_the_record(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        actor_id = _create(enforced_store, creator)
        db = get_actor(enforced_store)
        db.get(actor_id=actor_id)
        assert db.modify(passphrase=b"new-pw") is True
        row = get_actor(enforced_store).get(actor_id=actor_id)
        assert row is not None and row["passphrase"] == "new-pw"
        assert _holder(enforced_store, creator) == actor_id


@pytest.mark.skipif(
    not DYNAMODB,
    reason="PostgreSQL's index refuses the pre-enable duplicate outright",
)
class TestPreEnableDuplicates:
    """A duplicate an old process created during the rollout (DynamoDB: no
    record) never frees, or blocks on, the kept actor's record."""

    def _pair(self, config: Any) -> tuple[str, str, str]:
        creator = _email()
        kept = _create(config, creator)
        duplicate = _create(_flag_off(config), creator)
        return creator, kept, duplicate

    def test_deleting_it_leaves_the_kept_record(self, enforced_store: Any) -> None:
        creator, kept, duplicate = self._pair(enforced_store)
        db = get_actor(enforced_store)
        db.get(actor_id=duplicate)
        assert db.delete() is True
        assert _holder(enforced_store, creator) == kept

    def test_renaming_it_after_enable_leaves_the_kept_record(
        self, enforced_store: Any
    ) -> None:
        creator, kept, duplicate = self._pair(enforced_store)
        db = get_actor(enforced_store)
        db.get(actor_id=duplicate)
        target = dup_value(creator, duplicate)
        assert db.modify(creator=target) is True
        assert _stored_creator(enforced_store, duplicate) == target
        assert _holder(enforced_store, creator) == kept


class TestSwap:
    def test_the_swap_moves_the_creator_and_the_squatter_delete_keeps_it(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        squatter = _create(enforced_store, creator)
        successor = _id()
        db = get_actor(enforced_store)
        assert db.create(
            actor_id=successor,
            creator=creator,
            passphrase="pw",
            replace_holder=squatter,
        )
        assert _holder(enforced_store, creator) == successor
        if not DYNAMODB:
            # PostgreSQL renamed the squatter in the same transaction.
            assert _stored_creator(enforced_store, squatter) == dup_value(
                creator, squatter
            )
        old = get_actor(enforced_store)
        assert old.get(actor_id=squatter)
        assert old.delete() is True
        assert get_actor(enforced_store).get(actor_id=squatter) is None
        assert _holder(enforced_store, creator) == successor

    def test_a_stale_holder_raises_and_writes_nothing(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        holder = _create(enforced_store, creator)
        successor = _id()
        with pytest.raises(CreatorTaken):
            get_actor(enforced_store).replace_creator_holder(
                _id(), actor_id=successor, creator=creator, passphrase="pw"
            )
        assert get_actor(enforced_store).get(actor_id=successor) is None
        assert _holder(enforced_store, creator) == holder
        assert _stored_creator(enforced_store, holder) == creator


@pytest.mark.skipif(DYNAMODB, reason="the unique index is PostgreSQL's")
class TestPostgresIndexWithFlagOff:
    def test_a_violation_with_the_flag_off_raises_not_false(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        _create(enforced_store, creator)
        with pytest.raises(CreatorTaken):
            get_actor(_flag_off(enforced_store)).create(
                actor_id=_id(), creator=creator, passphrase="pw"
            )

    def test_a_flag_off_rename_onto_a_taken_creator_raises(
        self, enforced_store: Any
    ) -> None:
        first_creator = _email()
        _create(enforced_store, first_creator)
        second = _create(enforced_store, _email())
        db = get_actor(_flag_off(enforced_store))
        db.get(actor_id=second)
        with pytest.raises(CreatorTaken):
            db.modify(creator=first_creator)

    def test_autogenerate_does_not_propose_dropping_the_index(
        self, enforced_store: Any
    ) -> None:
        import os

        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import create_engine, text

        from actingweb.db.postgresql.connection import get_schema_name
        from actingweb.db.postgresql.schema import Base, include_object

        url = (
            f"postgresql+psycopg://{os.environ['PG_DB_USER']}:"
            f"{os.environ['PG_DB_PASSWORD']}@{os.environ['PG_DB_HOST']}:"
            f"{os.environ['PG_DB_PORT']}/{os.environ['PG_DB_NAME']}"
        )
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                conn.execute(text(f"SET search_path TO {get_schema_name()}"))
                context = MigrationContext.configure(
                    conn, opts={"include_object": include_object}
                )
                diff = compare_metadata(context, Base.metadata)
                unfiltered = compare_metadata(
                    MigrationContext.configure(conn), Base.metadata
                )
        finally:
            engine.dispose()
        assert not [d for d in diff if "ux_actors_creator" in str(d)], diff
        # The filter is what hides it: without it the drop is proposed.
        assert [d for d in unfiltered if "ux_actors_creator" in str(d)]


class TestReleasesTheStoredCreator:
    """F7: a delete releases the record of the creator the row had."""

    def test_a_stale_handle_delete_releases_the_current_record(
        self, enforced_store: Any
    ) -> None:
        old, new = _email(), _email()
        actor_id = _create(enforced_store, old)
        stale = get_actor(enforced_store)
        assert stale.get(actor_id=actor_id)
        renamer = get_actor(enforced_store)
        renamer.get(actor_id=actor_id)
        assert renamer.modify(creator=new) is True
        assert stale.delete() is True
        assert get_actor(enforced_store).get(actor_id=actor_id) is None
        assert _holder(enforced_store, new) is None
        _create(enforced_store, new)  # the address is free again

    @pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
    def test_a_legacy_mixed_case_row_releases_its_lowercase_record(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb.actor import Actor as ActorModel
        from actingweb.db.dynamodb.creator import Creator

        creator = _email()
        actor_id = _id()
        ActorModel(id=actor_id, creator=creator.upper(), passphrase="pw").save()
        Creator(creator=creator, actor_id=actor_id).save()
        db = get_actor(enforced_store)
        assert db.get(actor_id=actor_id)
        assert db.delete() is True
        assert _holder(enforced_store, creator) is None


class TestFlagAndReservedParity:
    def test_the_holder_read_needs_the_flag_on_both_backends(
        self, enforced_store: Any
    ) -> None:
        with pytest.raises(ValueError):
            get_actor(_flag_off(enforced_store)).get_creator_holder(_email())

    @pytest.mark.parametrize(
        "creator", ["#x", "someone@example.com#dup-1a2b3c4d", "A@B.COM#DUP-1A2B3C4D"]
    )
    def test_actor_create_refuses_reserved_creators(
        self, enforced_store: Any, creator: str
    ) -> None:
        from actingweb.actor import Actor

        actor = Actor(config=enforced_store)
        assert (
            actor.create(
                url="https://test.example.com/", creator=creator, passphrase=""
            )
            is False
        )
        assert actor.id is None
