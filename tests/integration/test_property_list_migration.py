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

    def test_holed_list_is_refused_and_keeps_serving_v1(self, test_actor):
        """A hole must block migration by default.

        Migrating a holed list is not merely lossy -- it is UNREPORTABLY
        lossy. The survivors are renumbered, the hole is gone, and the
        migrated list verifies healthy, so nothing afterwards can tell
        that an item went missing. Refusing keeps the damage on the books
        until an operator decides what to do about it."""
        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_holed", ["a", "b", "c", "d"]
        )
        _punch_hole(test_actor.config, test_actor.id, "migrate_holed", 1)

        prop_list = ListProperty(test_actor.id, "migrate_holed", test_actor.config)
        result = prop_list.migrate_to_v2()

        assert result["migrated"] is False
        assert result["reason"] == "damaged"
        assert result["missing_indices"] == [1]

        fresh = ListProperty(test_actor.id, "migrate_holed", test_actor.config)
        assert fresh.verify().get("format") != 2
        # Still v1, still damaged, still saying so.
        assert fresh.verify()["missing_indices"] == [1]

    def test_holed_list_migrates_with_hole_closed_when_allowed(self, test_actor):
        """--migrate-damaged's library equivalent: the operator asked, so
        the hole is closed -- and note what the assertions below pin, which
        is exactly why the default is a refusal. After this call there is
        no way left to discover that ``b`` was ever there."""
        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_holed_ok", ["a", "b", "c", "d"]
        )
        _punch_hole(test_actor.config, test_actor.id, "migrate_holed_ok", 1)

        prop_list = ListProperty(test_actor.id, "migrate_holed_ok", test_actor.config)
        result = prop_list.migrate_to_v2(allow_damaged=True)

        assert result["had_holes"] is True
        assert result["item_count"] == 3

        fresh = ListProperty(test_actor.id, "migrate_holed_ok", test_actor.config)
        assert fresh.to_list() == ["a", "c", "d"]
        assert fresh.verify()["healthy"] is True

    def test_orphan_row_is_refused_too(self, test_actor):
        """Orphans (rows past the recorded length) gate the same way holes
        do -- migration drops them silently, since it only reads
        ``[0, stored_length)``."""
        _seed_v1_list(test_actor.config, test_actor.id, "migrate_orphan", ["a", "b"])
        db = get_property(test_actor.config)
        assert db.set(
            actor_id=test_actor.id,
            name="list:migrate_orphan-2",
            value=json.dumps("stranded"),
        )

        prop_list = ListProperty(test_actor.id, "migrate_orphan", test_actor.config)
        result = prop_list.migrate_to_v2()

        assert result["migrated"] is False
        assert result["reason"] == "damaged"
        assert result["orphan_indices"] == [2]

    def test_duplicate_residue_migrates_preserved_and_reported(self, test_actor):
        """Duplicates migrate freely, unlike holes, and this test says why:
        the last assertion shows the duplicate is STILL reported after the
        migration. Nothing is hidden by converting it, so there is nothing
        for a refusal to protect."""
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

        assert result["migrated"] is True
        assert result["duplicate_count"] == 1
        fresh = ListProperty(test_actor.id, "migrate_dup", test_actor.config)
        assert fresh.to_list() == ["a", "b", "b"]
        assert fresh.verify()["adjacent_duplicates"]

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


@pytest.fixture(autouse=True)
def _lazy_migration_on(monkeypatch):
    """Lazy migration is OFF by default as of rc5 -- it is a rollback-safety
    control, since a pre-v2 process reads a converted list as empty. These
    tests exercise the trigger itself, so they opt in explicitly."""
    monkeypatch.setenv("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH", "50")


class TestLazyMigrationDefault:
    def test_lazy_migration_is_off_unless_asked_for(self, test_actor, monkeypatch):
        """The default must not convert existing data. A release that
        silently changes storage format is a release you cannot roll back
        from: an older process reads a converted list as empty, and a write
        from it forks the list across both formats."""
        monkeypatch.delenv("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH", raising=False)
        _seed_v1_list(test_actor.config, test_actor.id, "default_off", ["a", "b"])

        test_actor.property_lists.default_off.append("c")

        fresh = test_actor.property_lists.default_off
        assert fresh.verify().get("format") != 2, (
            "the default must leave existing lists on v1"
        )
        assert fresh.to_list() == ["a", "b", "c"]

    def test_new_lists_are_still_v2_with_lazy_migration_off(
        self, test_actor, monkeypatch
    ):
        """Defaulting to off does not make v2 opt-in -- it defers conversion
        of data that already exists. Everything created from now on is v2."""
        monkeypatch.delenv("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH", raising=False)

        brand_new = test_actor.property_lists.born_v2
        brand_new.append("x")
        brand_new.append("y")

        assert test_actor.property_lists.born_v2.verify()["format"] == 2
        assert test_actor.property_lists.born_v2.to_list() == ["x", "y"]


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


class TestConcurrentWriteDuringMigration:
    """A retained ListProperty instance holding pre-migration metadata must
    not revert a completed migration.

    Phase 1 of thoughts/plans/2026-08-15-property-list-metadata-integrity.md.
    Metadata used to be persisted by writing a whole cached dict back, so an
    instance that read a list before it was migrated restored ``format: 1``
    over the flip on its next write. Metadata then claimed v1 while every
    item lived in v2 rows nothing read, and migration's step 6 deletes the
    v1 rows -- the list came back EMPTY, with no error. Against real storage
    on both backends, because the failure is a storage-level one.
    """

    def test_concurrent_append_does_not_revert_the_migration(self, test_actor):
        _seed_v1_list(
            test_actor.config,
            test_actor.id,
            "concurrent_append",
            ["a", "b", "c"],
            description="kept across the migration",
        )

        # An instance the application retained, holding v1 metadata.
        retained = ListProperty(test_actor.id, "concurrent_append", test_actor.config)
        assert retained.to_list() == ["a", "b", "c"]

        # Another process migrates it.
        migrator = ListProperty(test_actor.id, "concurrent_append", test_actor.config)
        assert migrator.migrate_to_v2()["migrated"] is True

        # ...and the retained instance writes, still believing it is v1.
        retained.append("d")

        fresh = ListProperty(test_actor.id, "concurrent_append", test_actor.config)
        assert fresh.storage_format() == 2, "the format flip must survive the write"
        assert fresh.to_list() == ["a", "b", "c"], "no migrated item may be lost"
        assert fresh.get_description() == "kept across the migration"

    def test_a_v2_metadata_row_never_acquires_a_length(self, test_actor):
        """`length` is authoritative for v1 and absent for v2. A stale v1
        writer computed one against a different view of the list."""
        _seed_v1_list(
            test_actor.config, test_actor.id, "concurrent_length", ["a", "b", "c"]
        )
        retained = ListProperty(test_actor.id, "concurrent_length", test_actor.config)
        assert len(retained) == 3

        ListProperty(
            test_actor.id, "concurrent_length", test_actor.config
        ).migrate_to_v2()
        retained.append("d")

        raw_meta = get_property(test_actor.config).get(
            actor_id=test_actor.id, name="list:concurrent_length-meta"
        )
        assert raw_meta is not None
        meta = json.loads(raw_meta)
        assert meta["format"] == 2
        assert "length" not in meta

    def test_concurrent_delete_is_not_undone(self, test_actor):
        """An absent metadata row means a concurrent delete() won.
        Recreating it from a stale cache resurrects the list -- and
        ``exists()``/``list_all()`` key off exactly that row."""
        _seed_v1_list(
            test_actor.config, test_actor.id, "concurrent_delete", ["a", "b", "c"]
        )
        retained = ListProperty(test_actor.id, "concurrent_delete", test_actor.config)
        assert len(retained) == 3

        ListProperty(test_actor.id, "concurrent_delete", test_actor.config).delete()

        retained.append("d")

        assert (
            get_property(test_actor.config).get(
                actor_id=test_actor.id, name="list:concurrent_delete-meta"
            )
            is None
        )
        assert "concurrent_delete" not in test_actor.property_lists.list_all()


class TestInterruptedMigrationConverges:
    """A migration interrupted between its metadata flip (step 5) and its v1
    cleanup (step 6) left the v1 rows behind permanently: every re-run saw
    format 2 and returned before reaching step 6, and the bulk script skipped
    the list without calling migrate_to_v2() at all.

    Phase 2 of thoughts/plans/2026-08-15-property-list-metadata-integrity.md.
    """

    @staticmethod
    def _crash_after_the_flip(config, actor_id, name, items):
        """Drive a REAL migrate_to_v2() and abort it at the format flip, so
        the resulting state is produced by the code under test rather than
        hand-seeded."""

        class _Interrupt(Exception):
            pass

        real = ListProperty._replace_metadata  # noqa: SLF001

        def _flip_then_die(self, meta):
            real(self, meta)
            raise _Interrupt

        ListProperty._replace_metadata = _flip_then_die  # noqa: SLF001
        try:
            ListProperty(actor_id, name, config).migrate_to_v2()
        except _Interrupt:
            pass
        finally:
            ListProperty._replace_metadata = real  # noqa: SLF001

    def test_rerunning_migrate_to_v2_sweeps_the_v1_rows(self, test_actor):
        _seed_v1_list(
            test_actor.config, test_actor.id, "converge_direct", ["a", "b", "c"]
        )
        self._crash_after_the_flip(
            test_actor.config, test_actor.id, "converge_direct", ["a", "b", "c"]
        )

        crashed = ListProperty(test_actor.id, "converge_direct", test_actor.config)
        assert crashed.storage_format() == 2
        assert _raw_v1_rows(test_actor.config, test_actor.id, "converge_direct", 3) == [
            json.dumps(v) for v in ["a", "b", "c"]
        ], "the crash window requires the v1 rows to still be present"
        # Residue is reported but does not fail healthy.
        report = crashed.verify()
        assert report["foreign_format_rows"] == 3
        assert report["healthy"] is True

        assert crashed.migrate_to_v2() == {"migrated": False, "reason": "already_v2"}

        fresh = ListProperty(test_actor.id, "converge_direct", test_actor.config)
        assert fresh.to_list() == ["a", "b", "c"]
        assert fresh.verify()["foreign_format_rows"] == 0
        assert _raw_v1_rows(test_actor.config, test_actor.id, "converge_direct", 3) == [
            None,
            None,
            None,
        ]

    def test_the_bulk_script_reaches_that_cleanup(self, test_actor):
        """The load-bearing one: migrate_actor() gated on
        ``if already_v2: continue``, so the fix above was unreachable from
        the command operators actually run."""
        from actingweb.maintenance.migrate_property_lists import (
            RateLimiter,
            migrate_actor,
        )

        _seed_v1_list(
            test_actor.config, test_actor.id, "converge_script", ["a", "b", "c"]
        )
        self._crash_after_the_flip(
            test_actor.config, test_actor.id, "converge_script", ["a", "b", "c"]
        )

        _checked, _migrated, errored, refused = migrate_actor(
            test_actor.id, test_actor.config, migrate=True, limiter=RateLimiter(0)
        )

        assert (errored, refused) == (0, [])
        assert _raw_v1_rows(test_actor.config, test_actor.id, "converge_script", 3) == [
            None,
            None,
            None,
        ], "the script's already_v2 path must sweep, not skip"
        fresh = ListProperty(test_actor.id, "converge_script", test_actor.config)
        assert fresh.to_list() == ["a", "b", "c"]

    def test_a_deleted_list_does_not_resurrect_inside_its_successor(self, test_actor):
        """Cross-format residue outlives the list: ``exists()`` and
        ``list_all()`` key off the metadata row, so nothing reports it until
        a new list is created under the same name and adopts it."""
        _seed_v1_list(
            test_actor.config, test_actor.id, "converge_reuse", ["old-a", "old-b"]
        )
        self._crash_after_the_flip(
            test_actor.config, test_actor.id, "converge_reuse", ["old-a", "old-b"]
        )

        ListProperty(test_actor.id, "converge_reuse", test_actor.config).delete()

        recreated = ListProperty(test_actor.id, "converge_reuse", test_actor.config)
        assert recreated.to_list() == []
        recreated.append("new-a")
        assert recreated.to_list() == ["new-a"]

    def test_clear_empties_both_namespaces(self, test_actor):
        _seed_v1_list(test_actor.config, test_actor.id, "converge_clear", ["a", "b"])
        self._crash_after_the_flip(
            test_actor.config, test_actor.id, "converge_clear", ["a", "b"]
        )

        prop_list = ListProperty(test_actor.id, "converge_clear", test_actor.config)
        prop_list.clear()

        assert prop_list.to_list() == []
        assert _raw_v1_rows(test_actor.config, test_actor.id, "converge_clear", 2) == [
            None,
            None,
        ]

    def test_a_digit_named_sibling_list_survives_the_sweep(self, test_actor):
        """A list named 'sweep_owner-5' stores 'list:sweep_owner-5-0', which
        sorts inside list 'sweep_owner''s v1 byte range. Only the ^\\d+$
        suffix filter keeps the sweep off it."""
        _seed_v1_list(test_actor.config, test_actor.id, "sweep_owner", ["a", "b"])
        _seed_v1_list(
            test_actor.config, test_actor.id, "sweep_owner-5", ["keep-1", "keep-2"]
        )
        self._crash_after_the_flip(
            test_actor.config, test_actor.id, "sweep_owner", ["a", "b"]
        )

        owner = ListProperty(test_actor.id, "sweep_owner", test_actor.config)
        owner.sweep_foreign_format_rows()

        assert owner.to_list() == ["a", "b"]
        sibling = ListProperty(test_actor.id, "sweep_owner-5", test_actor.config)
        assert sibling.to_list() == ["keep-1", "keep-2"]
