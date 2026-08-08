"""
Property list repair and detection tests (Phase 2 of
thoughts/plans/2026-08-08-property-list-index-integrity.md).

Punches holes and orphans directly via raw property writes (bypassing
ListProperty, which is what a real interrupted delete/insert shift leaves
behind -- see thoughts/research/2026-08-07-property-list-index-integrity.md)
and verifies verify()/compact() detect and repair them correctly.
"""

import json
import os

import pytest

from actingweb.db import get_property
from actingweb.interface.actor_interface import ActorInterface
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
        aw_type="urn:actingweb:test:property_list_repair",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def test_actor(aw_app):
    """Create a test actor with automatic cleanup."""
    config = aw_app.get_config()
    actor = ActorInterface.create(
        creator="test@example.com",
        config=config,
    )
    yield actor
    try:
        actor.delete()
    except Exception:
        pass


def _punch_hole(config, actor_id, name, index):
    """Directly delete a list item row, bypassing ListProperty -- the
    residue an interrupted delete/insert shift leaves behind."""
    db = get_property(config)
    assert db.set(actor_id=actor_id, name=f"list:{name}-{index}", value=None)


def _write_orphan(config, actor_id, name, index, value):
    """Directly write a list item row past the recorded length."""
    db = get_property(config)
    assert db.set(
        actor_id=actor_id, name=f"list:{name}-{index}", value=json.dumps(value)
    )


def _raw_item(config, actor_id, name, index):
    db = get_property(config)
    return db.get(actor_id=actor_id, name=f"list:{name}-{index}")


class TestVerifyDetectsCorruption:
    def test_reports_missing_and_orphan_indices(self, test_actor):
        prop_list = test_actor.property_lists.repair_list_a
        for item in ["a", "b", "c", "d"]:
            prop_list.append(item)

        _punch_hole(test_actor.config, test_actor.id, "repair_list_a", 1)
        _write_orphan(test_actor.config, test_actor.id, "repair_list_a", 10, "orphan")

        report = prop_list.verify()

        assert report["stored_length"] == 4
        assert report["readable_count"] == 3
        assert report["missing_indices"] == [1]
        assert report["orphan_indices"] == [10]
        assert report["adjacent_duplicates"] == []
        assert report["healthy"] is False


class TestCompactRepairsHoles:
    def test_compact_closes_holes_preserves_metadata_removes_orphans(self, test_actor):
        prop_list = test_actor.property_lists.repair_list_b
        prop_list.set_description("my description")
        prop_list.set_explanation("my explanation")
        for item in ["a", "b", "c", "d"]:
            prop_list.append(item)

        created_at_before = prop_list._list_prop.get_metadata()["created_at"]

        _punch_hole(test_actor.config, test_actor.id, "repair_list_b", 1)
        _write_orphan(test_actor.config, test_actor.id, "repair_list_b", 10, "orphan")

        report = prop_list.compact()

        # compact() returns the pre-repair verify() report.
        assert report["missing_indices"] == [1]
        assert report["orphan_indices"] == [10]

        assert prop_list.to_list() == ["a", "c", "d"]
        assert len(prop_list) == 3
        assert prop_list.get_description() == "my description"
        assert prop_list.get_explanation() == "my explanation"
        assert prop_list._list_prop.get_metadata()["created_at"] == created_at_before

        # Orphan row is gone.
        assert _raw_item(test_actor.config, test_actor.id, "repair_list_b", 10) is None

        post = prop_list.verify()
        assert post["healthy"] is True

    def test_compact_on_duplicate_residue_leaves_both_rows_and_reports(
        self, test_actor
    ):
        prop_list = test_actor.property_lists.repair_list_c
        for item in ["a", "b", "c", "d"]:
            prop_list.append(item)

        # Simulate the exact-duplicate residue a crash between a shift's
        # move-write and delete-of-old-position leaves: index 2 now holds
        # the same value as index 1.
        _write_orphan(test_actor.config, test_actor.id, "repair_list_c", 2, "b")

        report = prop_list.verify()
        assert report["adjacent_duplicates"] == [(1, 2)]
        assert report["missing_indices"] == []
        assert report["orphan_indices"] == []
        assert report["healthy"] is False

        compact_report = prop_list.compact()
        assert compact_report["adjacent_duplicates"] == [(1, 2)]

        # Both rows survive untouched -- compact() never rewrites duplicates.
        assert prop_list.to_list() == ["a", "b", "b", "d"]
        assert len(prop_list) == 4

        # Still reported unhealthy after compact(): duplicate residue is
        # never auto-repaired.
        post = prop_list.verify()
        assert post["adjacent_duplicates"] == [(1, 2)]
        assert post["healthy"] is False

    def test_pop_works_again_after_compact_on_trailing_hole_list(self, test_actor):
        prop_list = test_actor.property_lists.repair_list_d
        for item in ["a", "b", "c"]:
            prop_list.append(item)

        # Trailing hole: the permanent-wedge case from the research --
        # pop() always targets the last index, which is the hole.
        _punch_hole(test_actor.config, test_actor.id, "repair_list_d", 2)

        with pytest.raises(IndexError):
            prop_list.pop()

        prop_list.compact()

        assert len(prop_list) == 2
        result = prop_list.pop()
        assert result == "b"
        assert prop_list.to_list() == ["a"]


class TestResyncSkipsCorruptedListsOnly:
    """Phase 3: a holed list must not abort a subscription full-state
    resync -- actor.py:_get_full_state_for_subscription() logs and skips
    only the corrupted list, other lists (and scalar properties) are still
    included."""

    def test_full_resync_skips_only_the_holed_list(self, test_actor):
        healthy = test_actor.property_lists.resync_healthy
        for item in ["a", "b"]:
            healthy.append(item)

        holed = test_actor.property_lists.resync_holed
        for item in ["x", "y", "z"]:
            holed.append(item)
        _punch_hole(test_actor.config, test_actor.id, "resync_holed", 1)

        test_actor.properties.scalar_prop = "scalar-value"

        state = test_actor._core_actor._get_full_state_for_subscription(
            "properties", None
        )

        assert "resync_healthy" in state
        assert state["resync_healthy"]["items"] == ["a", "b"]
        assert "scalar_prop" in state
        assert state["scalar_prop"] == "scalar-value"

        # The corrupted list is skipped, not raised through.
        assert "resync_holed" not in state

    def test_specific_subtarget_resync_on_holed_list_returns_empty(self, test_actor):
        holed = test_actor.property_lists.resync_holed_2
        for item in ["x", "y", "z"]:
            holed.append(item)
        _punch_hole(test_actor.config, test_actor.id, "resync_holed_2", 1)

        state = test_actor._core_actor._get_full_state_for_subscription(
            "properties", "resync_holed_2"
        )

        assert state == {}
