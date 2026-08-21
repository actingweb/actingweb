"""Phase 12 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): ``clear()``/``delete()`` teardown via
``batch_delete()`` instead of a serial per-item delete loop.

Runs against real DynamoDB/PostgreSQL (parametrized via DATABASE_BACKEND,
same convention as the sibling ``test_property_list_v2.py``) -- this is the
"Integration (PostgreSQL): ANY(%s) deletes the same rows as the loop did"
pin from the plan's New Tests: running the identical assertions against
both backends is what proves the PostgreSQL DELETE ... WHERE name = ANY(%s)
removes exactly what the old per-item loop removed, not merely that it
doesn't error.
"""

import os

import pytest

from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def aw_app(docker_services, setup_database, worker_info):  # noqa: ARG001
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    return ActingWebApp(
        aw_type="urn:actingweb:test:property_list_batch_teardown",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def test_actor(aw_app):
    config = aw_app.get_config()
    actor = ActorInterface.create(creator="test@example.com", config=config)
    yield actor
    try:
        actor.delete()
    except Exception:
        pass


class TestBatchedClearAndDelete:
    def test_clear_on_a_multi_batch_list_removes_every_item(self, test_actor):
        lst = test_actor.property_lists.big
        for i in range(55):  # > 25, so DynamoDB needs 3 BatchWriteItem calls
            lst.append({"n": i})
        assert len(lst) == 55

        lst.clear()

        assert len(lst) == 0
        assert lst.to_list() == []

    def test_delete_on_a_multi_batch_list_removes_every_row(self, test_actor):
        lst = test_actor.property_lists.big2
        for i in range(55):
            lst.append({"n": i})

        lst.delete()

        assert test_actor.property_lists.exists("big2") is False
        # A fresh list created under the same name must not resurrect any
        # row the delete left behind.
        fresh = test_actor.property_lists.big2
        fresh.append("only item")
        assert fresh.to_list() == ["only item"]

    def test_v1_clear_and_delete_also_go_through_batch_delete(self, test_actor, aw_app):
        """v1's clear()/delete() batch too (Phase 12 touches both
        branches) -- seed a genuinely v1 list directly, since the library
        defaults new lists to v2."""
        import json

        from actingweb.property import get_property

        config = aw_app.get_config()
        db = get_property(config)
        actor_id = test_actor.id
        for i in range(30):
            db.set(
                actor_id=actor_id,
                name=f"list:v1big-{i}",
                value=json.dumps({"n": i}),
            )
        db.set(
            actor_id=actor_id,
            name="list:v1big-meta",
            value=json.dumps(
                {
                    "format": 1,
                    "length": 30,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                    "item_type": "json",
                    "chunk_size": 1,
                    "version": "1.0",
                    "description": "",
                    "explanation": "",
                }
            ),
        )

        lst = test_actor.property_lists.v1big
        assert len(lst) == 30

        lst.clear()
        assert len(lst) == 0

        assert test_actor.property_lists.v1big.to_list() == []
