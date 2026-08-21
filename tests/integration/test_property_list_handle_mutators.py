"""Phase 10 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): value-addressed handle mutators
(``delete_by_handle``/``update_by_handle``) and the universal ``_where``
wrappers (``remove_where``/``update_where``), against a real backend.

Runs against real DynamoDB/PostgreSQL (parametrized via DATABASE_BACKEND,
same convention as the sibling ``test_property_list_v2.py``).
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
        aw_type="urn:actingweb:test:property_list_handle_mutators",
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


class TestHandleMutatorsAgainstRealBackend:
    def test_delete_by_handle_and_update_by_handle_round_trip(self, test_actor):
        lst = test_actor.property_lists.items
        for item in [{"id": 1}, {"id": 2}, {"id": 3}]:
            lst.append(item)

        pairs = lst.items_with_handles()
        assert [item for _, item in pairs] == [{"id": 1}, {"id": 2}, {"id": 3}]

        handle_2 = pairs[1][0]
        assert lst.update_by_handle(handle_2, {"id": 200}) is True
        assert lst.to_list() == [{"id": 1}, {"id": 200}, {"id": 3}]

        handle_1 = lst.items_with_handles()[0][0]
        assert lst.delete_by_handle(handle_1) is True
        assert lst.to_list() == [{"id": 200}, {"id": 3}]

    def test_delete_by_handle_returns_false_on_reused_stale_handle(self, test_actor):
        lst = test_actor.property_lists.items
        lst.append({"id": 1})

        handle, _ = lst.items_with_handles()[0]
        assert lst.delete_by_handle(handle) is True
        # Same handle, already-deleted row -- no exception, just False.
        assert lst.delete_by_handle(handle) is False

    def test_remove_where_and_update_where_end_to_end(self, test_actor):
        lst = test_actor.property_lists.items
        for item in [
            {"id": 1, "status": "open"},
            {"id": 2, "status": "closed"},
            {"id": 3, "status": "open"},
            {"id": 4, "status": "open"},
        ]:
            lst.append(item)

        updated = lst.update_where("status", "open", {"status": "archived"})
        assert updated == 3
        statuses = [item["status"] for item in lst.to_list()]
        assert statuses.count("archived") == 3
        assert statuses.count("closed") == 1

        removed = lst.remove_where("status", "archived")
        assert removed == 3
        assert lst.to_list() == [{"id": 2, "status": "closed"}]

    def test_remove_where_first_only_against_real_backend(self, test_actor):
        lst = test_actor.property_lists.items
        for item in [{"id": 1, "tag": "a"}, {"id": 2, "tag": "a"}]:
            lst.append(item)

        removed = lst.remove_where("tag", "a", first_only=True)
        assert removed == 1
        assert len(lst.to_list()) == 1
