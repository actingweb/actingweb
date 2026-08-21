"""Regression test for DbTrust.create()'s `approved` default.

Both backends used to declare `approved: str = ""` while PostgreSQL's
trusts.approved column is a genuine boolean, so calling create() without an
explicit `approved=` kwarg raised `invalid input syntax for type boolean` on
PostgreSQL — and DynamoDB tolerated the empty string silently, which is why
it went unnoticed. The default is now `approved: bool = False`, matching
TrustProtocol. This test pins the bare-default call on whichever backend the
suite runs against; no other in-tree caller exercises the default.
"""

import os
import uuid

import pytest

from actingweb.db import get_trust
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
        aw_type="urn:actingweb:test:trust_create_defaults",
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


class TestTrustCreateDefaults:
    def test_create_without_approved_kwarg_defaults_to_false(self, test_actor, aw_app):
        config = aw_app.get_config()
        peerid = f"peer-{uuid.uuid4()}"

        created = get_trust(config).create(
            actor_id=test_actor.id,
            peerid=peerid,
            baseuri="https://peer.example.com",
            relationship="friend",
            secret=f"s3cr3t-{uuid.uuid4()}",
        )
        assert created

        trust = get_trust(config).get(actor_id=test_actor.id, peerid=peerid)
        assert trust is not None
        assert trust["approved"] is False
