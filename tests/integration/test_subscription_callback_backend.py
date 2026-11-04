"""A subscription's ``callback`` flag round-trips as a bool on both backends
(3.16: a non-bool raises ``TypeError``; ``tests/test_subscription_callback_type.py``)."""

import os
import uuid

import pytest

from actingweb.db import get_subscription
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
        aw_type="urn:actingweb:test:subscription_callback",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    ).with_unique_creator(False)


@pytest.fixture
def test_actor(aw_app):
    config = aw_app.get_config()
    actor = ActorInterface.create(creator="test@example.com", config=config)
    yield actor
    try:
        actor.delete()
    except Exception:
        pass


class TestSubscriptionCallbackFlag:
    @pytest.mark.parametrize("flag", [True, False])
    def test_create_stores_the_bool(self, test_actor, aw_app, flag):
        config = aw_app.get_config()
        peerid = f"peer-{uuid.uuid4().hex}"
        subid = uuid.uuid4().hex
        db = get_subscription(config)
        assert db.create(
            actor_id=test_actor.id,
            peerid=peerid,
            subid=subid,
            granularity="high",
            target="properties",
            callback=flag,
        )
        try:
            row = get_subscription(config).get(
                actor_id=test_actor.id, peerid=peerid, subid=subid
            )
            assert row is not None
            assert row["callback"] is flag
        finally:
            db.delete()
