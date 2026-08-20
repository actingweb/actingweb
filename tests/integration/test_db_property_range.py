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


class TestConditionalDelete:
    """delete_if_value_equals() against the real backend (both, via
    DATABASE_BACKEND) -- the primitive pop()/remove() rely on to guarantee
    they act on the value they read."""

    def test_deletes_only_on_an_exact_value_match(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:cd-#a0", value='"original"')

        refused = get_property(config).delete_if_value_equals(
            actor_id=actor_id, name="list:cd-#a0", value='"something-else"'
        )
        assert refused is False
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cd-#a0")
            == '"original"'
        )

        deleted = get_property(config).delete_if_value_equals(
            actor_id=actor_id, name="list:cd-#a0", value='"original"'
        )
        assert deleted is True
        assert get_property(config).get(actor_id=actor_id, name="list:cd-#a0") is None

    def test_missing_row_reports_false_not_an_error(self, config, actor_id):
        assert (
            get_property(config).delete_if_value_equals(
                actor_id=actor_id, name="list:cd-#never", value='"x"'
            )
            is False
        )

    def test_overwritten_row_is_not_deleted(self, config, actor_id):
        assert get_property(config).set(
            actor_id=actor_id, name="list:cd-#b0", value='"v1"'
        )
        read = get_property(config).get(actor_id=actor_id, name="list:cd-#b0")
        assert read == '"v1"'

        # Another writer replaces it before our conditional delete lands.
        assert get_property(config).set(
            actor_id=actor_id, name="list:cd-#b0", value='"v2"'
        )

        assert (
            get_property(config).delete_if_value_equals(
                actor_id=actor_id, name="list:cd-#b0", value=read
            )
            is False
        )
        assert get_property(config).get(actor_id=actor_id, name="list:cd-#b0") == '"v2"'


class TestConditionalSet:
    """set_if_value_equals() against the real backend (both, via
    DATABASE_BACKEND) -- Phase 8 of thoughts/plans/2026-08-20-v2-
    positional-access-cost.md. Compare-and-swap, the write-side
    counterpart to TestConditionalDelete above."""

    def test_sets_only_on_an_exact_value_match(self, config, actor_id):
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:cs-#a0", value='"original"')

        refused = get_property(config).set_if_value_equals(
            actor_id=actor_id,
            name="list:cs-#a0",
            expected='"something-else"',
            value='"new"',
        )
        assert refused is False
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cs-#a0")
            == '"original"'
        )

        updated = get_property(config).set_if_value_equals(
            actor_id=actor_id,
            name="list:cs-#a0",
            expected='"original"',
            value='"new"',
        )
        assert updated is True
        assert (
            get_property(config).get(actor_id=actor_id, name="list:cs-#a0") == '"new"'
        )

    def test_missing_row_reports_false_not_an_error(self, config, actor_id):
        assert (
            get_property(config).set_if_value_equals(
                actor_id=actor_id,
                name="list:cs-#never",
                expected='"x"',
                value='"y"',
            )
            is False
        )

    def test_overwritten_row_is_not_set(self, config, actor_id):
        assert get_property(config).set(
            actor_id=actor_id, name="list:cs-#b0", value='"v1"'
        )
        read = get_property(config).get(actor_id=actor_id, name="list:cs-#b0")
        assert read == '"v1"'

        # Another writer replaces it before our conditional set lands.
        assert get_property(config).set(
            actor_id=actor_id, name="list:cs-#b0", value='"v2"'
        )

        assert (
            get_property(config).set_if_value_equals(
                actor_id=actor_id, name="list:cs-#b0", expected=read, value='"v3"'
            )
            is False
        )
        assert get_property(config).get(actor_id=actor_id, name="list:cs-#b0") == '"v2"'

    def test_condition_failure_returns_false_not_dberror(self, config, actor_id):
        """The distinction the whole retry design rests on: a condition
        miss is a normal outcome, not a fault."""
        assert get_property(config).set(
            actor_id=actor_id, name="list:cs-#c0", value='"v1"'
        )
        result = get_property(config).set_if_value_equals(
            actor_id=actor_id, name="list:cs-#c0", expected='"wrong"', value='"v2"'
        )
        assert result is False  # no exception raised


class TestGetLastInRange:
    """get_last_in_range() against the real backend -- Phase 9B's
    append() reads a list's highest rank key from this instead of the
    whole-list range read."""

    def test_returns_the_bytewise_greatest_name(self, config, actor_id):
        db = get_property(config)
        for rank in ["a0", "a1", "a2"]:
            assert db.set(actor_id=actor_id, name=f"list:gl-#{rank}", value='"x"')

        result = get_property(config).get_last_in_range(
            actor_id=actor_id, lower="list:gl-#", upper="list:gl-$"
        )
        assert result == "list:gl-#a2"

    def test_empty_range_returns_none(self, config, actor_id):
        result = get_property(config).get_last_in_range(
            actor_id=actor_id, lower="list:glempty-#", upper="list:glempty-$"
        )
        assert result is None

    def test_case_boundary_is_byte_order_not_locale_order(self, config, actor_id):
        """The regression a locale collation fails: max("Z", "a") is "a"
        bytewise (0x5A < 0x61) but "Z" under en_US-style locale collation.
        A wrong answer here becomes a mid-list append."""
        db = get_property(config)
        assert db.set(actor_id=actor_id, name="list:glcase-#Z", value='"upper"')
        assert db.set(actor_id=actor_id, name="list:glcase-#a", value='"lower"')

        result = get_property(config).get_last_in_range(
            actor_id=actor_id, lower="list:glcase-#", upper="list:glcase-$"
        )
        assert result == "list:glcase-#a"  # bytewise-greatest, not locale-greatest
