"""A store with no user actors enables creator uniqueness at the first start
(4.0; AC-13, AC-14, AC-50). On the isolated store (``AWS_DB_PREFIX`` set),
real probes, in the ``unique_creator`` group."""

from __future__ import annotations

import threading
from typing import Any
from unittest import mock

import pytest

from actingweb.db import get_actor
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
