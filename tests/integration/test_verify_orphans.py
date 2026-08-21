"""Phase 13 of the v2 list read cost release (thoughts/plans/2026-08-20-
v2-positional-access-cost.md): the orphan-row scan
(``actingweb.maintenance.verify_orphans``) against a real backend.

Runs against real DynamoDB/PostgreSQL (parametrized via DATABASE_BACKEND,
same convention as the sibling ``test_property_list_batch_teardown.py``).
Two things a unit test with fake rows cannot prove:

- A just-created actor's rows are never reported orphaned -- proves the
  actor-id read is actually consistent, not merely coded to ask for
  ``consistent_read=True``.
- The exact same classification comes out of the real DynamoDB Scan and
  the real PostgreSQL SELECT, for the same seeded live/ghost row set.

The full-table scans this test exercises run against a shared test
database that other tests may also be writing to, so assertions filter the
classification down to rows belonging to THIS test's own actor/ghost ids
(both UUID-suffixed) rather than asserting exact global counts.
"""

import os
import uuid

import pytest

from actingweb.db import get_attribute, get_property, get_trust
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp
from actingweb.maintenance import verify_orphans as vo

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
        aw_type="urn:actingweb:test:verify_orphans",
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


def _sweep(config):
    backend = getattr(config, "database", "dynamodb")
    actor_ids = vo._read_actor_ids(backend)
    limiter = vo.RateLimiter(0)  # unlimited: this is a test, not a prod sweep
    rows = []
    for table in vo.ROW_TYPES:
        rows.extend(vo._rows_for(backend, table, limiter))
    return actor_ids, vo.classify_rows(actor_ids, rows)


def _for_actor(rows, actor_id):
    return [row for row in rows if row[0] == actor_id]


class TestOrphanClassificationAgainstARealBackend:
    def test_live_rows_are_clean_and_ghost_rows_are_orphaned(self, test_actor, aw_app):
        config = aw_app.get_config()

        # Live rows: everything hangs off an actor that genuinely exists.
        test_actor.properties["marker"] = "alive"
        test_actor.property_lists.mylist.append({"n": 1})
        get_attribute(config).set_attr(
            actor_id=test_actor.id, bucket="testbucket", name="k", data={"v": 1}
        )
        get_trust(config).create(
            actor_id=test_actor.id,
            peerid=f"peer-{uuid.uuid4()}",
            baseuri="https://peer.example.com",
            relationship="friend",
            secret="s3cr3t",
            approved=True,
        )

        # Ghost rows: an actor id that was never created -- what
        # Actor.delete() being interrupted, or a late webhook write, leaves
        # behind.
        ghost_id = f"ghost-{uuid.uuid4()}"
        get_property(config).set(actor_id=ghost_id, name="orphaned", value="1")
        get_attribute(config).set_attr(
            actor_id=ghost_id, bucket="testbucket", name="k", data={"v": 1}
        )
        get_trust(config).create(
            actor_id=ghost_id,
            peerid=f"peer-{uuid.uuid4()}",
            baseuri="https://peer.example.com",
            relationship="friend",
            secret="s3cr3t",
            approved=True,
        )

        # The ghost rows are deliberately never cleaned up here: this tool
        # reports orphans and never deletes them, and an operator would
        # remove them with their own tooling after reviewing the report --
        # this test leaves them in place for the same reason. The test
        # containers are torn down after the run either way.
        actor_ids, result = _sweep(config)

        # Consistent read: the actor created moments ago is present.
        assert test_actor.id in actor_ids

        for table in vo.ROW_TYPES:
            assert _for_actor(result["orphans"][table], test_actor.id) == []
            assert len(_for_actor(result["orphans"][table], ghost_id)) == 1
            assert _for_actor(result["reserved"][table], test_actor.id) == []
            assert _for_actor(result["reserved"][table], ghost_id) == []
