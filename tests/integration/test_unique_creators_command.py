"""``actingweb-unique-creators`` against seeded duplicates (3.16, PR 2).

Runs on an isolated store (``tests/integration/_isolated_store.py``) in the
``unique_creator`` xdist group; each test starts from an empty store.
"""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb.actor import Actor
from actingweb.db import get_actor
from actingweb.db.creator_rules import dup_value
from actingweb.db.exceptions import CreatorTaken
from actingweb.maintenance import unique_creators

from .conftest import DATABASE_BACKEND

pytestmark = pytest.mark.xdist_group(name="unique_creator")

DYNAMODB = DATABASE_BACKEND == "dynamodb"


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _off(config: Any) -> Any:
    off = copy.copy(config)
    off.unique_creator = False
    return off


def _seed(
    config: Any,
    creator: str,
    *,
    marker: str | None = "app",
    created: int | None = None,
    email: str | None = None,
) -> str:
    """An actor created with the flag off (as before ``enable``)."""
    actor = Actor(config=_off(config))
    assert actor.create(
        url="https://test.example.com/",
        creator=creator,
        passphrase="pw",
        auth_method=marker or "app",
    )
    assert actor.store is not None and actor.id
    if marker is None:
        actor.store.auth_method = None
    if created is not None:
        actor.store.created_at = str(created)
    if email is not None:
        actor.store.email = email
    return actor.id


def _raw_actor(creator: str) -> str:
    """An actor row written as stored, bypassing the lowercasing (a legacy
    mixed-case address)."""
    actor_id = uuid.uuid4().hex
    if DYNAMODB:
        from actingweb.db.dynamodb.actor import Actor as ActorModel

        ActorModel(id=actor_id, creator=creator, passphrase="pw").save()
    else:
        from actingweb.db.postgresql.connection import get_connection

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO actors (id, creator, passphrase, created_at) "
                    "VALUES (%s, %s, 'pw', NOW())",
                    (actor_id, creator),
                )
            conn.commit()
    return actor_id


def _creator(config: Any, actor_id: str) -> str | None:
    row = get_actor(config).get(actor_id=actor_id)
    return row["creator"] if row else None


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="unique_creators")
    return caplog


class TestReport:
    def test_a_clean_store_exits_zero(self, fresh_store: Any) -> None:
        _seed(fresh_store, _email())
        assert unique_creators.main(["report"]) == 0

    def test_exact_and_case_only_duplicates_exit_one(
        self, fresh_store: Any, logs: pytest.LogCaptureFixture
    ) -> None:
        exact = _email()
        first, second = _seed(fresh_store, exact), _seed(fresh_store, exact)
        mixed = _email()
        lower_id = _seed(fresh_store, mixed)
        upper_id = _raw_actor(mixed.upper())
        provider_ids = (_raw_actor("apple:ABC"), _raw_actor("apple:abc"))

        assert unique_creators.main(["report"]) == 1
        text = logs.text
        assert (
            f"duplicate creator={exact!r} ids={','.join(sorted([first, second]))}"
            in (text)
        )
        assert (
            f"case-only duplicate creator={mixed!r} "
            f"ids={','.join(sorted([lower_id, upper_id]))}" in text
        )
        # Provider ids keep their case: never a case-only group.
        assert not any(i in text for i in provider_ids)

    @pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
    def test_orphaned_records_exit_one(
        self, enforced_store: Any, logs: pytest.LogCaptureFixture
    ) -> None:
        from actingweb.db.dynamodb.creator import Creator

        gone = _email()
        Creator(creator=gone, actor_id="no-such-actor").save()
        moved = _email()
        actor_id = _seed(enforced_store, _email())
        Creator(creator=moved, actor_id=actor_id).save()

        assert unique_creators.main(["report"]) == 1
        assert f"orphaned record creator={gone!r} actor=no-such-actor (missing)" in (
            logs.text
        )
        assert f"orphaned record creator={moved!r} actor={actor_id} (mismatch)" in (
            logs.text
        )

    @pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
    def test_an_actor_without_its_record_after_enable_exits_one(
        self, enforced_store: Any, logs: pytest.LogCaptureFixture
    ) -> None:
        actor_id = _seed(enforced_store, _email())  # an old process's create
        assert unique_creators.main(["report"]) == 1
        assert f"unrecorded actor id={actor_id}" in logs.text
        assert unique_creators.main(["enable", "--apply"]) == 0
        assert unique_creators.main(["report"]) == 0


class TestResolve:
    def test_without_apply_nothing_is_written(self, fresh_store: Any) -> None:
        creator = _email()
        ids = [_seed(fresh_store, creator), _seed(fresh_store, creator)]
        assert unique_creators.main(["resolve"]) == 0
        assert [_creator(fresh_store, i) for i in ids] == [creator, creator]

    def test_an_unmarked_old_owner_beats_a_newer_factory_squatter(
        self, fresh_store: Any, logs: pytest.LogCaptureFixture
    ) -> None:
        creator = _email()
        owner = _seed(fresh_store, creator, marker=None, created=1000)
        squatter = _seed(
            fresh_store, creator, marker="factory", created=2000, email=creator
        )
        assert unique_creators.main(["resolve", "--apply"]) == 0
        assert _creator(fresh_store, owner) == creator
        assert _creator(fresh_store, squatter) == dup_value(creator, squatter)
        assert f"keep creator={creator!r} id={owner} (unvouched)" in logs.text
        # The stored email is cleared, so force_email_prop_as_creator cannot
        # undo the rename on the next load.
        forced = copy.copy(fresh_store)
        forced.force_email_prop_as_creator = True
        assert Actor(actor_id=squatter, config=forced).creator == dup_value(
            creator, squatter
        )

    def test_two_vouched_actors_are_decided_by_age_and_logged(
        self, fresh_store: Any, logs: pytest.LogCaptureFixture
    ) -> None:
        creator = _email()
        newer = _seed(fresh_store, creator, created=2000)
        older = _seed(fresh_store, creator, created=1000)
        if not DYNAMODB:
            # PostgreSQL ranks by its created_at column: make it agree.
            from actingweb.db.postgresql.connection import get_connection

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE actors SET created_at = NOW() - interval '1 day' "
                        "WHERE id = %s",
                        (older,),
                    )
                conn.commit()
        assert unique_creators.main(["resolve", "--apply"]) == 0
        assert _creator(fresh_store, older) == creator
        assert _creator(fresh_store, newer) == dup_value(creator, newer)
        assert f"id={older} (vouched, age decided)" in logs.text

    def test_a_group_with_an_unreadable_marker_is_skipped(
        self, fresh_store: Any, logs: pytest.LogCaptureFixture
    ) -> None:
        creator = _email()
        ids = [_seed(fresh_store, creator), _seed(fresh_store, creator)]
        with mock.patch("actingweb.oauth2.classify_marker", return_value=None):
            assert unique_creators.main(["resolve", "--apply"]) == 1
        assert [_creator(fresh_store, i) for i in ids] == [creator, creator]
        assert "a marker could not be read; skipped" in logs.text

    def test_keep_overrides_the_rule(self, fresh_store: Any) -> None:
        creator = _email()
        vouched = _seed(fresh_store, creator)
        factory = _seed(fresh_store, creator, marker="factory")
        assert unique_creators.main(["resolve", "--apply", "--keep", factory]) == 0
        assert _creator(fresh_store, factory) == creator
        assert _creator(fresh_store, vouched) == dup_value(creator, vouched)

    def test_keep_outside_every_group_is_refused(self, fresh_store: Any) -> None:
        creator = _email()
        _seed(fresh_store, creator)
        _seed(fresh_store, creator)
        with pytest.raises(SystemExit) as exc:
            unique_creators.main(["resolve", "--keep", "no-such-id"])
        assert exc.value.code == 2

    def test_a_case_only_group_resolves_to_one_lowercase_actor(
        self, fresh_store: Any
    ) -> None:
        mixed = _email()
        lower_id = _seed(fresh_store, mixed, created=1000)
        upper_id = _raw_actor(mixed.upper())
        assert unique_creators.main(["resolve", "--apply"]) == 0
        assert unique_creators.main(["report"]) == 0
        creators = {_creator(fresh_store, lower_id), _creator(fresh_store, upper_id)}
        assert mixed in creators


class TestEnableDisable:
    def test_enable_refuses_with_duplicates_then_works_after_resolve(
        self, fresh_store: Any
    ) -> None:
        creator = _email()
        kept = _seed(fresh_store, creator)
        _seed(fresh_store, creator, marker="factory")
        assert unique_creators.main(["enable", "--apply"]) == 1
        assert unique_creators.missing_enforcement(fresh_store) is not None

        assert unique_creators.main(["resolve", "--apply"]) == 0
        assert unique_creators.main(["enable", "--apply"]) == 0
        assert unique_creators.missing_enforcement(fresh_store) is None
        assert get_actor(fresh_store).get_creator_holder(creator) == kept
        # A second run is a no-op.
        assert unique_creators.main(["enable", "--apply"]) == 0
        with pytest.raises(CreatorTaken):
            get_actor(fresh_store).create(
                actor_id=uuid.uuid4().hex, creator=creator, passphrase="pw"
            )

    def test_enable_without_apply_writes_nothing(self, fresh_store: Any) -> None:
        _seed(fresh_store, _email())
        assert unique_creators.main(["enable"]) == 0
        assert unique_creators.missing_enforcement(fresh_store) is not None

    @pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
    def test_an_interrupted_dynamodb_enable_can_be_rerun(
        self, fresh_store: Any
    ) -> None:
        from actingweb.db.dynamodb.creator import Creator

        creators = [_email() for _ in range(3)]
        ids = [_seed(fresh_store, c) for c in creators]
        Creator.create_table(wait=True)
        # Stopped after the first record, before the backfill-complete item.
        Creator(creator=creators[0], actor_id=ids[0]).save()
        assert unique_creators.missing_enforcement(fresh_store) is not None
        assert unique_creators.main(["enable", "--apply"]) == 0
        assert unique_creators.missing_enforcement(fresh_store) is None
        for creator, actor_id in zip(creators, ids, strict=True):
            assert get_actor(fresh_store).get_creator_holder(creator) == actor_id

    @pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
    def test_a_record_naming_another_actor_stops_enable(self, fresh_store: Any) -> None:
        from actingweb.db.dynamodb.creator import Creator

        creator = _email()
        _seed(fresh_store, creator)
        Creator.create_table(wait=True)
        Creator(creator=creator, actor_id="someone-else").save()
        assert unique_creators.main(["enable", "--apply"]) == 1
        assert unique_creators.missing_enforcement(fresh_store) is not None

    def test_disable_reverses_enable(self, fresh_store: Any) -> None:
        creator = _email()
        _seed(fresh_store, creator)
        assert unique_creators.main(["enable", "--apply"]) == 0
        assert unique_creators.main(["disable"]) == 0  # dry run
        assert unique_creators.missing_enforcement(fresh_store) is None
        assert unique_creators.main(["disable", "--apply"]) == 0
        assert unique_creators.missing_enforcement(fresh_store) is not None
        # Nothing enforces now: a second actor for the creator is accepted.
        assert get_actor(_off(fresh_store)).create(
            actor_id=uuid.uuid4().hex, creator=creator, passphrase="pw"
        )

    @pytest.mark.skipif(DYNAMODB, reason="the index is PostgreSQL's")
    def test_an_invalid_index_is_dropped_and_rebuilt(self, fresh_store: Any) -> None:
        with mock.patch.object(
            unique_creators,
            "postgresql_index_state",
            side_effect=["invalid", "valid"],
        ):
            assert unique_creators.missing_enforcement(fresh_store) is not None
        # A real INVALID index is hard to make on demand; the path that drops
        # it runs on a valid one here, then the build succeeds.
        states = iter(["invalid", "valid"])
        real = unique_creators.postgresql_index_state
        with mock.patch.object(
            unique_creators,
            "postgresql_index_state",
            side_effect=lambda: next(states, None) or real(),
        ):
            assert unique_creators.main(["enable", "--apply"]) == 0
        assert unique_creators.postgresql_index_state() == "valid"


class TestCapitalsAndOrder:
    """G7: mixed-case addresses are lowercased, and in the right order."""

    def test_a_case_group_keeping_the_mixed_case_actor_ends_lowercase(
        self, fresh_store: Any
    ) -> None:
        mixed = _email()
        lower_id = _seed(fresh_store, mixed)
        upper_id = _raw_actor(mixed.upper())
        assert unique_creators.main(["resolve", "--apply", "--keep", upper_id]) == 0
        assert _creator(fresh_store, upper_id) == mixed
        assert _creator(fresh_store, lower_id) == dup_value(mixed, lower_id)
        assert unique_creators.main(["report"]) == 0

    def test_a_lone_address_with_capitals_is_reported_and_lowercased(
        self, fresh_store: Any, logs: pytest.LogCaptureFixture
    ) -> None:
        mixed = _email()
        actor_id = _raw_actor(mixed.upper())
        assert unique_creators.main(["report"]) == 1
        assert f"address with capitals id={actor_id}" in logs.text
        assert unique_creators.main(["enable", "--apply"]) == 1  # refused
        assert unique_creators.main(["resolve", "--apply"]) == 0
        assert _creator(fresh_store, actor_id) == mixed
        assert unique_creators.main(["report"]) == 0
        assert unique_creators.main(["enable", "--apply"]) == 0


@pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
class TestRecordsStayTrue:
    """D7, E7 and the resolve half of A7: the command never leaves a record
    naming an actor that holds another creator."""

    def test_enable_refuses_while_an_orphaned_record_remains(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb.creator import Creator

        Creator(creator=_email(), actor_id="no-such-actor").save()
        assert unique_creators.main(["enable", "--apply"]) == 1
        assert unique_creators.main(["resolve", "--apply"]) == 0
        assert unique_creators.main(["enable", "--apply"]) == 0

    def test_enable_skips_an_actor_renamed_after_its_scan(
        self, fresh_store: Any
    ) -> None:
        from actingweb.db.dynamodb.actor import Actor as ActorModel

        old, new = _email(), _email()
        actor_id = _seed(fresh_store, old)
        report = unique_creators.collect(fresh_store, consistent=True)
        row = ActorModel.get(actor_id, consistent_read=True)
        row.update(actions=[ActorModel.creator.set(new)])
        assert unique_creators.enable(fresh_store, report, apply=True) == "backfilled"
        db = get_actor(fresh_store)
        assert db.get_creator_holder(old) is None

    def test_disable_deletes_every_record(self, fresh_store: Any) -> None:
        from actingweb.db.dynamodb.creator import Creator

        _seed(fresh_store, _email())
        _seed(fresh_store, _email())
        assert unique_creators.main(["enable", "--apply"]) == 0
        assert unique_creators.main(["disable", "--apply"]) == 0
        assert list(Creator.scan()) == []

    def test_renaming_the_recorded_actor_releases_its_record(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        recorded = _seed(enforced_store, creator)
        assert unique_creators.main(["enable", "--apply"]) == 0
        assert get_actor(enforced_store).get_creator_holder(creator) == recorded
        kept = _seed(enforced_store, creator)  # an old process, no record
        assert unique_creators.main(["resolve", "--apply", "--keep", kept]) == 0
        # D8: the record moved to the kept actor, with no gap for a sign-in.
        assert get_actor(enforced_store).get_creator_holder(creator) == kept
        assert unique_creators.main(["report"]) == 0
