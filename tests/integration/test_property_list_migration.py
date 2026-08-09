"""
v1 -> v2 list-property migration -- Phase 5 of
thoughts/plans/2026-08-08-property-list-index-integrity.md.

Covers ListProperty.migrate_to_v2() directly (idempotency, holes,
duplicates, refusal) and the lazy trigger wired into append()/insert()/
__setitem__()/__delitem__() for small (<=50 item) v1 lists.
"""

import datetime
import json
import os

import pytest

from actingweb.db import get_property
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp
from actingweb.property_list import ListProperty

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
        aw_type="urn:actingweb:test:property_list_migration",
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


def _seed_v1_list(config, actor_id, name, items, description="", explanation=""):
    """Directly write a v1-format list (meta + dense-integer item rows),
    bypassing ListProperty.append() (which creates v2 lists by default)."""
    db = get_property(config)
    now = datetime.datetime.now().isoformat()
    meta = {
        "length": len(items),
        "created_at": now,
        "updated_at": now,
        "item_type": "json",
        "chunk_size": 1,
        "version": "1.0",
        "description": description,
        "explanation": explanation,
    }
    assert db.set(actor_id=actor_id, name=f"list:{name}-meta", value=json.dumps(meta))
    for i, item in enumerate(items):
        assert db.set(
            actor_id=actor_id, name=f"list:{name}-{i}", value=json.dumps(item)
        )


def _punch_hole(config, actor_id, name, index):
    db = get_property(config)
    assert db.set(actor_id=actor_id, name=f"list:{name}-{index}", value=None)


def _raw_v1_rows(config, actor_id, name, stored_length):
    db = get_property(config)
    return [
        db.get(actor_id=actor_id, name=f"list:{name}-{i}") for i in range(stored_length)
    ]


class TestMigrateToV2Direct:
    def test_migrates_small_list_end_to_end(self, test_actor):
        _seed_v1_list(
            test_actor.config,
            test_actor.id,
            "migrate_basic",
            ["a", "b", "c"],
            description="my desc",
            explanation="my expl",
        )
        prop_list = ListProperty(test_actor.id, "migrate_basic", test_actor.config)

        result = prop_list.migrate_to_v2()

        assert result == {
            "migrated": True,
            "item_count": 3,
            "had_holes": False,
            "duplicate_count": 0,
        }

        fresh = ListProperty(test_actor.id, "migrate_basic", test_actor.config)
        assert fresh.verify()["format"] == 2
        assert fresh.to_list() == ["a", "b", "c"]
        assert fresh.get_description() == "my desc"
        assert fresh.get_explanation() == "my expl"

        # v1 rows are gone.
        assert _raw_v1_rows(test_actor.config, test_actor.id, "migrate_basic", 3) == [
            None,
            None,
            None,
        ]

    def test_rest_behaviour_identical_before_and_after(self, test_actor):
        _seed_v1_list(test_actor.config, test_actor.id, "migrate_rest", ["x", "y", "z"])
        prop_list = ListProperty(test_actor.id, "migrate_rest", test_actor.config)
        before_items = prop_list.to_list_from_rows(
            {
                "list:migrate_rest-0": json.dumps("x"),
                "list:migrate_rest-1": json.dumps("y"),
                "list:migrate_rest-2": json.dumps("z"),
            }
        )
        before_indexed = prop_list.to_indexed_list()

        prop_list.migrate_to_v2()

        fresh = ListProperty(test_actor.id, "migrate_rest", test_actor.config)
        assert fresh.to_list() == before_items
        assert fresh.to_indexed_list() == before_indexed

    def test_holed_list_migrates_with_hole_closed(self, test_actor):
        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_holed", ["a", "b", "c", "d"]
        )
        _punch_hole(test_actor.config, test_actor.id, "migrate_holed", 1)

        prop_list = ListProperty(test_actor.id, "migrate_holed", test_actor.config)
        result = prop_list.migrate_to_v2()

        assert result["had_holes"] is True
        assert result["item_count"] == 3

        fresh = ListProperty(test_actor.id, "migrate_holed", test_actor.config)
        assert fresh.to_list() == ["a", "c", "d"]
        assert fresh.verify()["healthy"] is True

    def test_duplicate_residue_migrates_preserved_and_reported(self, test_actor):
        _seed_v1_list(test_actor.config, test_actor.id, "migrate_dup", ["a", "b", "c"])
        db = get_property(test_actor.config)
        # Duplicate residue: index 2 holds the same value as index 1.
        assert db.set(
            actor_id=test_actor.id,
            name="list:migrate_dup-2",
            value=json.dumps("b"),
        )

        prop_list = ListProperty(test_actor.id, "migrate_dup", test_actor.config)
        result = prop_list.migrate_to_v2()

        assert result["duplicate_count"] == 1
        fresh = ListProperty(test_actor.id, "migrate_dup", test_actor.config)
        assert fresh.to_list() == ["a", "b", "b"]

    def test_refuses_name_with_hash_and_keeps_serving_v1(self, test_actor):
        _seed_v1_list(test_actor.config, test_actor.id, "a-#x", ["a", "b"])
        prop_list = ListProperty(test_actor.id, "a-#x", test_actor.config)

        result = prop_list.migrate_to_v2()

        assert result == {"migrated": False, "reason": "name_contains_hash"}
        fresh = ListProperty(test_actor.id, "a-#x", test_actor.config)
        assert "format" not in fresh.verify()
        assert fresh.to_list() == ["a", "b"]

    def test_already_v2_list_is_a_noop(self, test_actor):
        prop_list = test_actor.property_lists.already_v2
        prop_list.append("x")

        result = prop_list._list_prop.migrate_to_v2()

        assert result == {"migrated": False, "reason": "already_v2"}


class TestMigrateToV2Idempotency:
    def test_rerun_after_step4_crash_is_convergent(self, test_actor):
        """Kill migration after step 4 (v2 rows written, meta not flipped
        -- v1 stays authoritative) by seeding the exact v2-row residue that
        state would leave, then re-run migrate_to_v2() for real."""
        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_crash", ["a", "b", "c"]
        )

        prop_list = ListProperty(test_actor.id, "migrate_crash", test_actor.config)
        # Simulate steps 1-4 only: write v2 rows, do NOT flip the meta.
        import fractional_indexing as fi

        db = get_property(test_actor.config)
        ranks = fi.generate_n_keys_between(None, None, 3)
        for rank, item in zip(ranks, ["a", "b", "c"], strict=True):
            assert db.set(
                actor_id=test_actor.id,
                name=f"list:migrate_crash-#{rank}",
                value=json.dumps(item),
            )
        # v1 is still authoritative -- verify() must not see the v2 scratch
        # rows at all (they're outside v1's range).
        assert prop_list.verify().get("format") != 2

        result = prop_list.migrate_to_v2()

        assert result["migrated"] is True
        fresh = ListProperty(test_actor.id, "migrate_crash", test_actor.config)
        assert fresh.to_list() == ["a", "b", "c"]
        assert fresh.verify()["healthy"] is True

    def test_rerun_after_v1_mutation_between_attempts_is_convergent(self, test_actor):
        """The scenario the plan's idempotency claim didn't originally
        cover: migration is interrupted after step 4, then the v1 list is
        mutated (through the still-authoritative v1 path) before the
        second attempt. migrate_to_v2() must still converge -- it clears
        any leftover v2 scratch rows at the start of every attempt rather
        than trying to reconcile with a previous attempt's rank count."""
        import fractional_indexing as fi

        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_interrupted", ["a", "b", "c"]
        )

        # Simulate an interrupted first attempt: v2 rows for a 3-item
        # migration, meta still v1.
        db = get_property(test_actor.config)
        stale_ranks = fi.generate_n_keys_between(None, None, 3)
        for rank, item in zip(stale_ranks, ["a", "b", "c"], strict=True):
            assert db.set(
                actor_id=test_actor.id,
                name=f"list:migrate_interrupted-#{rank}",
                value=json.dumps(item),
            )

        # A v1 mutation happens between attempts (still v1-authoritative,
        # so this goes through the v1 path and changes length from 3 to 4)
        # -- append() would normally lazy-migrate a <=50-item list, so call
        # the underlying v1 machinery directly via a raw write instead, to
        # isolate this test from that separate behavior.
        assert db.set(
            actor_id=test_actor.id,
            name="list:migrate_interrupted-3",
            value=json.dumps("d"),
        )
        meta_str = db.get(actor_id=test_actor.id, name="list:migrate_interrupted-meta")
        assert meta_str is not None
        meta = json.loads(meta_str)
        meta["length"] = 4
        assert db.set(
            actor_id=test_actor.id,
            name="list:migrate_interrupted-meta",
            value=json.dumps(meta),
        )

        prop_list = ListProperty(
            test_actor.id, "migrate_interrupted", test_actor.config
        )
        result = prop_list.migrate_to_v2()

        assert result["migrated"] is True
        assert result["item_count"] == 4

        fresh = ListProperty(test_actor.id, "migrate_interrupted", test_actor.config)
        assert fresh.to_list() == ["a", "b", "c", "d"]
        assert fresh.verify()["healthy"] is True
        # No leftover stale-rank rows from the interrupted first attempt.
        assert fresh.verify()["length"] == 4

    def test_rerun_after_full_success_is_a_noop(self, test_actor):
        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_done_twice", ["a", "b"]
        )
        prop_list = ListProperty(test_actor.id, "migrate_done_twice", test_actor.config)
        first = prop_list.migrate_to_v2()
        assert first["migrated"] is True

        second = prop_list.migrate_to_v2()
        assert second == {"migrated": False, "reason": "already_v2"}

        fresh = ListProperty(test_actor.id, "migrate_done_twice", test_actor.config)
        assert fresh.to_list() == ["a", "b"]


class TestLazyMigrationTrigger:
    def test_append_on_small_v1_list_migrates_it(self, test_actor):
        _seed_v1_list(test_actor.config, test_actor.id, "lazy_small", ["a", "b"])
        prop_list = test_actor.property_lists.lazy_small

        prop_list.append("c")

        assert prop_list.to_list() == ["a", "b", "c"]
        fresh = test_actor.property_lists.lazy_small
        assert fresh.verify()["format"] == 2

    def test_setitem_on_small_v1_list_migrates_it(self, test_actor):
        _seed_v1_list(test_actor.config, test_actor.id, "lazy_setitem", ["a", "b"])
        prop_list = test_actor.property_lists.lazy_setitem

        prop_list[0] = "A"

        assert prop_list.to_list() == ["A", "b"]
        fresh = test_actor.property_lists.lazy_setitem
        assert fresh.verify()["format"] == 2

    def test_delitem_on_small_v1_list_migrates_it(self, test_actor):
        _seed_v1_list(test_actor.config, test_actor.id, "lazy_delitem", ["a", "b", "c"])
        prop_list = test_actor.property_lists.lazy_delitem

        del prop_list[1]

        assert prop_list.to_list() == ["a", "c"]
        fresh = test_actor.property_lists.lazy_delitem
        assert fresh.verify()["format"] == 2

    def test_insert_on_small_v1_list_migrates_it(self, test_actor):
        _seed_v1_list(test_actor.config, test_actor.id, "lazy_insert", ["a", "c"])
        prop_list = test_actor.property_lists.lazy_insert

        prop_list.insert(1, "b")

        assert prop_list.to_list() == ["a", "b", "c"]
        fresh = test_actor.property_lists.lazy_insert
        assert fresh.verify()["format"] == 2

    def test_51_item_v1_list_not_migrated_by_append(self, test_actor):
        items = [f"item-{i}" for i in range(51)]
        _seed_v1_list(test_actor.config, test_actor.id, "lazy_bound_over", items)
        prop_list = test_actor.property_lists.lazy_bound_over

        prop_list.append("item-51")

        fresh = test_actor.property_lists.lazy_bound_over
        report = fresh.verify()
        assert "format" not in report
        assert fresh.to_list() == [*items, "item-51"]
        # Confirmed still v1: raw dense-integer rows are readable directly.
        db = get_property(test_actor.config)
        assert db.get(
            actor_id=test_actor.id, name="list:lazy_bound_over-0"
        ) == json.dumps("item-0")

    def test_50_item_v1_list_is_migrated_by_append(self, test_actor):
        items = [f"item-{i}" for i in range(50)]
        _seed_v1_list(test_actor.config, test_actor.id, "lazy_bound_at", items)
        prop_list = test_actor.property_lists.lazy_bound_at

        prop_list.append("item-50")

        fresh = test_actor.property_lists.lazy_bound_at
        assert fresh.verify()["format"] == 2
        assert fresh.to_list() == [*items, "item-50"]

    def test_read_paths_never_trigger_migration(self, test_actor):
        """to_list()/__getitem__/verify() must never migrate -- only the
        four mutation entry points do."""
        _seed_v1_list(test_actor.config, test_actor.id, "lazy_read_only", ["a", "b"])
        prop_list = test_actor.property_lists.lazy_read_only

        assert prop_list.to_list() == ["a", "b"]
        assert prop_list[0] == "a"
        assert len(prop_list) == 2
        report = prop_list.verify()
        assert report.get("format") != 2

        db = get_property(test_actor.config)
        assert db.get(
            actor_id=test_actor.id, name="list:lazy_read_only-0"
        ) == json.dumps("a")

    def test_failed_lazy_migration_does_not_fail_the_mutation(
        self, test_actor, monkeypatch
    ):
        """A lazy-migration failure is logged and swallowed -- the
        original v1 mutation must still succeed."""
        _seed_v1_list(
            test_actor.config, test_actor.id, "lazy_migrate_fails", ["a", "b"]
        )
        prop_list = test_actor.property_lists.lazy_migrate_fails

        def _broken_migrate(self):
            raise RuntimeError("simulated migration failure")

        monkeypatch.setattr(
            "actingweb.property_list.ListProperty.migrate_to_v2", _broken_migrate
        )

        prop_list.append("c")

        assert prop_list.to_list() == ["a", "b", "c"]
        fresh = test_actor.property_lists.lazy_migrate_fails
        assert fresh.verify().get("format") != 2
