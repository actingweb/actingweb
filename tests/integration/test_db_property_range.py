"""DbProperty.get_range() / create_if_not_exists() (both backends).

These back the v2 fractional-rank-key list storage format (Phase 4 of
thoughts/plans/2026-08-08-property-list-index-integrity.md): get_range()
reads a list's item rows in one query instead of one per item;
create_if_not_exists() gives collision-free conditional inserts for
generated rank keys. Lives under tests/integration/ because PostgreSQL
needs the migrated schema the session fixtures below provision.
"""

import os
import uuid

import pytest

from actingweb.db import get_property
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
        aw_type="urn:actingweb:test:db_property_range",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def config(aw_app):
    return aw_app.get_config()


@pytest.fixture
def actor_id():
    return f"range-test-{uuid.uuid4()}"


class TestGetRange:
    def test_range_returns_only_rows_in_bounds(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:foo-#a0", value='"first"')
        assert db.set(actor_id=actor_id, name="list:foo-#a1", value='"second"')
        # Outside the range: v1 item row, meta row, unrelated property.
        assert db.set(actor_id=actor_id, name="list:foo-0", value='"v1-item"')
        assert db.set(actor_id=actor_id, name="list:foo-meta", value="{}")
        assert db.set(actor_id=actor_id, name="unrelated", value="x")

        result = get_property(config).get_range(
            actor_id=actor_id, lower="list:foo-#", upper="list:foo-$"
        )

        assert result == {
            "list:foo-#a0": '"first"',
            "list:foo-#a1": '"second"',
        }

    def test_range_excludes_sibling_list_with_shared_prefix(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:foo-#a0", value='"foo-item"')
        assert db.set(actor_id=actor_id, name="list:foo-x-#a0", value='"sibling"')

        result = get_property(config).get_range(
            actor_id=actor_id, lower="list:foo-#", upper="list:foo-$"
        )

        assert result == {"list:foo-#a0": '"foo-item"'}

    def test_keys_only_returns_empty_values(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:bar-#a0", value='"x"')
        assert db.set(actor_id=actor_id, name="list:bar-#a1", value='"y"')

        result = get_property(config).get_range(
            actor_id=actor_id, lower="list:bar-#", upper="list:bar-$", keys_only=True
        )

        assert result == {"list:bar-#a0": "", "list:bar-#a1": ""}

    def test_empty_range_returns_empty_dict(self, config, actor_id):
        result = get_property(config).get_range(
            actor_id=actor_id, lower="list:nothere-#", upper="list:nothere-$"
        )
        assert result == {}


class TestCreateIfNotExists:
    def test_create_succeeds_on_absent_row(self, config, actor_id):
        db = get_property(config)
        assert db.create_if_not_exists(
            actor_id=actor_id, name="list:cine-#a0", value='"item"'
        )
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cine-#a0")
            == '"item"'
        )

    def test_create_fails_on_existing_row_without_overwriting(self, config, actor_id):
        db = get_property(config)
        assert db.create_if_not_exists(
            actor_id=actor_id, name="list:cine-#a0", value='"original"'
        )
        collided = get_property(config).create_if_not_exists(
            actor_id=actor_id, name="list:cine-#a0", value='"colliding"'
        )
        assert collided is False
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cine-#a0")
            == '"original"'
        )
