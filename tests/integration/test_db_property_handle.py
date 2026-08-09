"""Regression test for the DbProperty stale-handle bug (both backends).

A DbProperty instance whose cached ``handle`` was populated by a prior
get()/set() call for one ``(actor_id, name)`` must serve a get()/set() for a
DIFFERENT ``(actor_id, name)`` correctly rather than reading or writing
through the stale handle. This is the mechanism behind the
``ListProperty.insert()`` DynamoDB data-destruction bug
(``property_list.py``'s ``insert()`` worked around it by taking fresh
handles per call; this test pins the backend-level fix that makes the class
safe regardless of caller discipline).

Lives under tests/integration/ (not tests/) because PostgreSQL needs the
migrated schema the session fixtures below provision; DynamoDB self-creates
its table on DbProperty() construction but PostgreSQL does not.
"""

import os
import uuid

import pytest

from actingweb.db import get_property
from actingweb.interface.app import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def aw_app(docker_services, setup_database, worker_info):  # noqa: ARG001
    """Create ActingWeb app for testing (same pattern as
    test_property_lists_advanced.py)."""
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    return ActingWebApp(
        aw_type="urn:actingweb:test:db_property_handle",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def db_property(aw_app):
    config = aw_app.get_config()
    return get_property(config)


@pytest.fixture
def actor_id():
    return f"handle-test-{uuid.uuid4()}"


class TestDbPropertyHandleIsolation:
    def test_get_after_get_serves_correct_row(self, db_property, actor_id):
        assert db_property.set(actor_id=actor_id, name="rowA", value="valueA")
        assert db_property.set(actor_id=actor_id, name="rowB", value="valueB")

        # Prime the handle on row A.
        assert db_property.get(actor_id=actor_id, name="rowA") == "valueA"
        # A get() for a DIFFERENT name must not be served from row A's handle.
        assert db_property.get(actor_id=actor_id, name="rowB") == "valueB"

    def test_set_after_get_writes_correct_row(self, db_property, actor_id):
        assert db_property.set(actor_id=actor_id, name="rowA", value="valueA")
        assert db_property.set(actor_id=actor_id, name="rowB", value="valueB")

        assert db_property.get(actor_id=actor_id, name="rowA") == "valueA"
        # A set() for a DIFFERENT name must not overwrite row A.
        assert db_property.set(actor_id=actor_id, name="rowB", value="updated")

        assert db_property.get(actor_id=actor_id, name="rowA") == "valueA"
        assert db_property.get(actor_id=actor_id, name="rowB") == "updated"

    def test_set_after_set_writes_correct_row(self, db_property, actor_id):
        assert db_property.set(actor_id=actor_id, name="rowA", value="first")
        # A second set() for a different name must not silently update rowA.
        assert db_property.set(actor_id=actor_id, name="rowB", value="second")

        assert db_property.get(actor_id=actor_id, name="rowA") == "first"
        assert db_property.get(actor_id=actor_id, name="rowB") == "second"

    def test_get_after_different_actor_get(self, db_property, actor_id):
        other_actor = f"handle-test-other-{uuid.uuid4()}"
        assert db_property.set(actor_id=actor_id, name="shared", value="mine")
        assert db_property.set(actor_id=other_actor, name="shared", value="theirs")

        assert db_property.get(actor_id=actor_id, name="shared") == "mine"
        assert db_property.get(actor_id=other_actor, name="shared") == "theirs"
