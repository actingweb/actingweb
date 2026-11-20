"""A store with no user actors enables creator uniqueness at the first start
(4.0; AC-13, AC-14, AC-50). On the isolated store (``AWS_DB_PREFIX`` set),
real probes, in the ``unique_creator`` group."""

from __future__ import annotations

import threading
from typing import Any
from unittest import mock

import pytest

from actingweb.db import get_actor
from actingweb.db.creator_rules import BACKFILL_KEY
from actingweb.interface import ActingWebApp, UniqueCreatorNotReady
from actingweb.maintenance import unique_creators

from .conftest import DATABASE_BACKEND

DYNAMODB = DATABASE_BACKEND == "dynamodb"

pytestmark = [
    pytest.mark.xdist_group(name="unique_creator"),
    pytest.mark.usefixtures("real_unique_probe"),
]


def _app() -> ActingWebApp:
    return ActingWebApp(
        aw_type="urn:actingweb:test:unique_creator_empty",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
    ).with_indexed_properties([])


@pytest.mark.skipif(not DYNAMODB, reason="DynamoDB")
def test_dynamodb_empty_store_starts(fresh_store: Any) -> None:
    from actingweb.db.creator_rules import BACKFILL_KEY
    from actingweb.db.dynamodb.creator import Creator

    _app().check_ready()
    assert unique_creators.missing_enforcement(fresh_store) is None
    assert Creator.get(BACKFILL_KEY, consistent_read=True)


@pytest.mark.skipif(DYNAMODB, reason="PostgreSQL")
def test_postgresql_empty_store_starts(fresh_store: Any) -> None:
    from actingweb.db.postgresql.actor import reset_index_probe

    _app().check_ready()
    reset_index_probe()
    assert unique_creators.postgresql_index_state() == "valid"


@pytest.mark.skipif(DYNAMODB, reason="PostgreSQL")
def test_postgresql_without_ddl_refuses_with_the_command(fresh_store: Any) -> None:
    import psycopg

    with mock.patch.object(
        unique_creators,
        "_enable_empty_postgresql",
        side_effect=psycopg.errors.InsufficientPrivilege("permission denied"),
    ):
        with pytest.raises(UniqueCreatorNotReady) as raised:
            _app().check_ready()
    assert "actingweb-unique-creators enable --apply" in str(raised.value)
    assert raised.value.unavailable is False


@pytest.mark.skipif(DYNAMODB, reason="PostgreSQL")
def test_two_first_starts_at_once_both_start(fresh_store: Any) -> None:
    errors: list[BaseException] = []

    def start() -> None:
        try:
            _app().check_ready()
        except BaseException as e:  # noqa: BLE001 - collected
            errors.append(e)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == []
    assert unique_creators.postgresql_index_state() == "valid"


@pytest.mark.skipif(not DYNAMODB, reason="the race is DynamoDB's")
def test_an_actor_created_during_the_enable_is_recorded(fresh_store: Any) -> None:
    """AC-50: an older process creates an actor (no creator record) between
    the empty verdict and the backfill marker; it is recorded, never left
    unrecorded behind a complete marker."""
    from actingweb.db.creator_rules import BACKFILL_KEY
    from actingweb.db.dynamodb.actor import Actor as ActorModel
    from actingweb.db.dynamodb.creator import Creator

    real_save = Creator.save
    late = {"id": "late0actor0id", "creator": "late@example.com"}

    def save(self: Any, *a: Any, **k: Any) -> Any:
        if self.creator == BACKFILL_KEY and not ActorModel.count(late["id"]):
            # What a 3.15.1 process writes: the actor row only.
            ActorModel(id=late["id"], creator=late["creator"], passphrase="p").save()
        return real_save(self, *a, **k)

    with mock.patch.object(Creator, "save", save):
        _app().check_ready()
    assert unique_creators.missing_enforcement(fresh_store) is None
    record = Creator.get(late["creator"], consistent_read=True)
    assert record.actor_id == late["id"]
    assert get_actor(fresh_store).get(actor_id=late["id"]) is not None


@pytest.mark.usefixtures("real_dynamodb_backfill_probe", "real_pg_index_probe")
def test_a_trust_type_registered_before_the_start_on_a_fresh_store(
    fresh_store: Any,
) -> None:
    """Iterations 2 and 15 (verification issue 17; second verification,
    issue 2): an application that registers a trust type at import, before
    ``integrate_*()``, creates the system actor before the empty-store
    enable; on a fresh store of either backend that must not crash, and the
    start then enables the store with the system actor covered."""
    from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR
    from actingweb.permission_integration import AccessControlConfig

    app = _app()
    AccessControlConfig(app.get_config()).add_trust_type(
        name="viewer",
        display_name="Viewer",
        permissions={"properties": ["*"]},
        description="read-only",
    )
    app.check_ready()
    assert unique_creators.missing_enforcement(fresh_store) is None
    if DYNAMODB:
        from actingweb.db.dynamodb.creator import Creator

        assert Creator.get("system", consistent_read=True).actor_id == (
            ACTINGWEB_SYSTEM_ACTOR
        )
    else:
        from actingweb.db.postgresql.actor import reset_index_probe

        reset_index_probe()
        assert unique_creators.postgresql_index_state() == "valid"
    assert get_actor(fresh_store).get(actor_id=ACTINGWEB_SYSTEM_ACTOR) is not None


@pytest.mark.usefixtures("real_dynamodb_backfill_probe", "real_pg_index_probe")
def test_only_the_system_actors_own_ids_skip_the_record(fresh_store: Any) -> None:
    """Iteration 15 (second verification, issue 4): the exemption is for the
    library's system actors at their fixed ids; another id with a system
    creator is refused before the store is enabled."""
    from actingweb.db.exceptions import DbError

    with pytest.raises(DbError):
        get_actor(fresh_store).create(
            actor_id="not0a0system0actor",
            creator="system",
            passphrase="p",
        )


@pytest.mark.skipif(not DYNAMODB, reason="the race is DynamoDB's")
def test_a_fault_after_the_marker_removes_it(fresh_store: Any) -> None:
    """Iteration 4 (verification issue 3): a fault while recording an actor
    created during the enable removes the complete marker again, so the
    next start does not pass over an unrecorded actor."""
    from actingweb.db.dynamodb import actor as dynamodb_actor
    from actingweb.db.dynamodb.actor import Actor as ActorModel
    from actingweb.db.dynamodb.creator import Creator
    from actingweb.db.exceptions import DbError

    real_save = Creator.save
    late = {"id": "late1actor1id", "creator": "late1@example.com"}

    def save(self: Any, *a: Any, **k: Any) -> Any:
        if self.creator == BACKFILL_KEY and not ActorModel.count(late["id"]):
            ActorModel(id=late["id"], creator=late["creator"], passphrase="p").save()
        return real_save(self, *a, **k)

    def faulting_record(creator: str, row: Any) -> bool:
        raise DbError("creator record")

    with (
        mock.patch.object(Creator, "save", save),
        mock.patch.object(dynamodb_actor, "record_for_actor_as_read", faulting_record),
        pytest.raises(UniqueCreatorNotReady),
    ):
        _app().check_ready()
    assert unique_creators.missing_enforcement(fresh_store) is not None


@pytest.mark.skipif(not DYNAMODB, reason="the marker is DynamoDB's")
def test_a_failing_enable_never_removes_another_starts_marker(
    fresh_store: Any,
) -> None:
    """Iterations 14 and 20 (second verification, issue 1; third, issue 1):
    two first starts at once. Start B has written the complete marker; start
    C, whose first scan saw the empty store, finds it when it would write
    its own. C runs the same late pass over what was created meanwhile, and
    when that fails C refuses its own start but leaves B's marker in place."""
    from actingweb.db.dynamodb import actor as dynamodb_actor
    from actingweb.db.dynamodb.creator import Creator
    from actingweb.db.exceptions import DbError

    real_scan = dynamodb_actor.Actor.scan
    calls = {"n": 0}

    def scan(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        rows = list(real_scan(*a, **k))
        if calls["n"] == 1:
            # B finishes between C's first scan and C's marker write, and a
            # user signs up through B.
            Creator(creator=BACKFILL_KEY).save()
            dynamodb_actor.Actor(
                id="b0user0id", creator="b-user@example.com", passphrase="p"
            ).save()
        return iter(rows)

    def faulting_record(creator: str, row: Any) -> bool:
        raise DbError("creator record")

    with (
        mock.patch.object(dynamodb_actor.Actor, "scan", scan),
        mock.patch.object(dynamodb_actor, "record_for_actor_as_read", faulting_record),
        pytest.raises(unique_creators.EnableRefused) as refused,
    ):
        unique_creators.enable_empty_store(fresh_store)
    # Refused, not a retryable fault: a retried check would find the marker.
    assert "enable --apply" in str(refused.value)
    assert Creator.get(BACKFILL_KEY, consistent_read=True)


@pytest.mark.skipif(not DYNAMODB, reason="the marker is DynamoDB's")
def test_a_start_that_finds_the_marker_records_what_was_created_meanwhile(
    fresh_store: Any,
) -> None:
    """Iteration 20 (third verification, issue 1): the start that accepts
    another start's marker records an actor an older process created in the
    window, instead of trusting a writer that may not have finished."""
    from actingweb.db.dynamodb import actor as dynamodb_actor
    from actingweb.db.dynamodb.creator import Creator

    real_scan = dynamodb_actor.Actor.scan
    calls = {"n": 0}

    def scan(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        rows = list(real_scan(*a, **k))
        if calls["n"] == 1:
            Creator(creator=BACKFILL_KEY).save()
            # What a 3.15.1 process writes: the actor row only.
            dynamodb_actor.Actor(
                id="old0proc0id", creator="old@example.com", passphrase="p"
            ).save()
        return iter(rows)

    with mock.patch.object(dynamodb_actor.Actor, "scan", scan):
        unique_creators.enable_empty_store(fresh_store)
    assert Creator.get("old@example.com", consistent_read=True).actor_id == (
        "old0proc0id"
    )
    assert Creator.get(BACKFILL_KEY, consistent_read=True)


@pytest.mark.skipif(not DYNAMODB, reason="the race is DynamoDB's")
def test_a_system_actor_written_during_the_enable_is_recorded(
    fresh_store: Any,
) -> None:
    """Iteration 14 (second verification, issue 5): a system actor another
    worker writes (without a record) between the first scan and the marker
    is recorded by the late pass."""
    from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR
    from actingweb.db.dynamodb.actor import Actor as ActorModel
    from actingweb.db.dynamodb.creator import Creator

    real_save = Creator.save

    def save(self: Any, *a: Any, **k: Any) -> Any:
        if self.creator == BACKFILL_KEY and not ActorModel.count(
            ACTINGWEB_SYSTEM_ACTOR
        ):
            ActorModel(
                id=ACTINGWEB_SYSTEM_ACTOR, creator="system", passphrase="p"
            ).save()
        return real_save(self, *a, **k)

    with mock.patch.object(Creator, "save", save):
        unique_creators.enable_empty_store(fresh_store)
    assert Creator.get("system", consistent_read=True).actor_id == (
        ACTINGWEB_SYSTEM_ACTOR
    )
