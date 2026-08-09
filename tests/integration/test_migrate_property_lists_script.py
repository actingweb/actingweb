"""Smoke test for scripts/migrate_property_lists.py.

Calls migrate_actor()/downgrade_to_v1() directly (the script's per-actor
units) rather than shelling out to main() -- exercises the same
migrate_to_v2() codepath the standalone migration tests already cover in
detail, and pins this script's dry-run/refusal/downgrade reporting.
"""

import datetime
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from actingweb.db import get_property
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp
from actingweb.property_list import ListProperty

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def _seed_v1_list(config, actor_id, name, items):
    db = get_property(config)
    now = datetime.datetime.now().isoformat()
    meta = {
        "length": len(items),
        "created_at": now,
        "updated_at": now,
        "item_type": "json",
        "chunk_size": 1,
        "version": "1.0",
        "description": "",
        "explanation": "",
    }
    assert db.set(actor_id=actor_id, name=f"list:{name}-meta", value=json.dumps(meta))
    for i, item in enumerate(items):
        assert db.set(
            actor_id=actor_id, name=f"list:{name}-{i}", value=json.dumps(item)
        )


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
        aw_type="urn:actingweb:test:migrate_script",
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


class TestMigrateActor:
    def test_dry_run_reports_without_migrating(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_script_dry", ["a", "b"]
        )

        checked, migrated, errored, refused = script.migrate_actor(
            test_actor.id,
            test_actor.config,
            migrate=False,
            limiter=script.RateLimiter(0),
        )

        assert checked >= 1
        assert migrated >= 1
        assert errored == 0
        assert refused == []

        # Dry run wrote nothing -- still v1.
        fresh = test_actor.property_lists.migrate_script_dry
        assert fresh.verify().get("format") != 2

    def test_migrate_flag_performs_migration(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_script_real", ["a", "b", "c"]
        )

        checked, migrated, errored, refused = script.migrate_actor(
            test_actor.id,
            test_actor.config,
            migrate=True,
            limiter=script.RateLimiter(0),
        )

        assert checked == 1
        assert migrated == 1
        assert errored == 0
        assert refused == []

        fresh = test_actor.property_lists.migrate_script_real
        assert fresh.verify()["format"] == 2
        assert fresh.to_list() == ["a", "b", "c"]

    def test_hash_named_list_is_refused_and_reported(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(test_actor.config, test_actor.id, "bad-#name", ["a"])

        checked, migrated, errored, refused = script.migrate_actor(
            test_actor.id,
            test_actor.config,
            migrate=True,
            limiter=script.RateLimiter(0),
        )

        assert checked == 1
        assert migrated == 0
        assert errored == 0
        assert refused == [(f"{test_actor.id}/bad-#name", "rename required")]

        fresh = getattr(test_actor.property_lists, "bad-#name")
        assert fresh.verify().get("format") != 2
        assert fresh.to_list() == ["a"]

    def test_dry_run_names_a_holed_list_instead_of_saying_would_migrate(
        self, test_actor
    ):
        """The dry run's whole job is to tell an operator what --migrate
        will do. A holed list must come back as a refusal, not as a bare
        "would migrate".

        This is the defect this test exists for: the dry run warned about
        duplicate residue and said nothing whatsoever about holes, so a
        sweep over a fleet containing one reported "0 refused, 0 errors"
        and the operator went ahead. Migration then closed the hole, and
        because a migrated list verifies healthy, that was the last moment
        anyone could have found out.
        """
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(
            test_actor.config, test_actor.id, "dry_run_holed", ["a", "b", "c"]
        )
        db = get_property(test_actor.config)
        assert db.set(actor_id=test_actor.id, name="list:dry_run_holed-1", value=None)

        checked, migrated, errored, refused = script.migrate_actor(
            test_actor.id,
            test_actor.config,
            migrate=False,
            limiter=script.RateLimiter(0),
        )

        assert checked == 1
        assert migrated == 0, "a list that would be refused is not 'would migrate'"
        assert errored == 0
        assert refused == [(f"{test_actor.id}/dry_run_holed", "repair required")]

    def test_migrate_refuses_a_holed_list_and_leaves_it_v1(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_holed_script", ["a", "b", "c"]
        )
        db = get_property(test_actor.config)
        assert db.set(
            actor_id=test_actor.id, name="list:migrate_holed_script-1", value=None
        )

        checked, migrated, errored, refused = script.migrate_actor(
            test_actor.id,
            test_actor.config,
            migrate=True,
            limiter=script.RateLimiter(0),
        )

        assert checked == 1
        assert migrated == 0
        assert errored == 0
        assert refused == [(f"{test_actor.id}/migrate_holed_script", "repair required")]

        fresh = ListProperty(test_actor.id, "migrate_holed_script", test_actor.config)
        assert fresh.verify().get("format") != 2
        assert fresh.verify()["missing_indices"] == [1]

    def test_migrate_damaged_flag_migrates_the_holed_list(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(
            test_actor.config, test_actor.id, "migrate_damaged_ok", ["a", "b", "c"]
        )
        db = get_property(test_actor.config)
        assert db.set(
            actor_id=test_actor.id, name="list:migrate_damaged_ok-1", value=None
        )

        checked, migrated, errored, refused = script.migrate_actor(
            test_actor.id,
            test_actor.config,
            migrate=True,
            limiter=script.RateLimiter(0),
            allow_damaged=True,
        )

        assert checked == 1
        assert migrated == 1
        assert errored == 0
        assert refused == []

        fresh = ListProperty(test_actor.id, "migrate_damaged_ok", test_actor.config)
        assert fresh.verify()["format"] == 2
        assert fresh.to_list() == ["a", "c"]

    def test_already_v2_lists_are_skipped(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        v2_list = test_actor.property_lists.already_v2_script
        v2_list.append("x")

        checked, migrated, errored, refused = script.migrate_actor(
            test_actor.id,
            test_actor.config,
            migrate=True,
            limiter=script.RateLimiter(0),
        )

        assert checked == 0
        assert migrated == 0
        assert errored == 0
        assert refused == []


def _only_this_actor(monkeypatch, actor_id):
    """Restrict main()'s actor sweep to one actor.

    main() sweeps every actor in the table, but the test database is shared
    with whatever other tests are running (xdist workers included), so its
    exit code and checkpoint contents would otherwise depend on unrelated
    actors' lists. Patching the actor listing keeps argparse, the sweep
    loop and the checkpoint lifecycle -- the things these tests exist to
    exercise -- while making the outcome deterministic.
    """

    class _OneActor:
        def fetch(self):
            return [{"id": actor_id}]

    monkeypatch.setattr("actingweb.db.get_actor_list", lambda config: _OneActor())


class TestMainCommandLineWorkflow:
    """Exercises script.main() itself (argparse + checkpoint lifecycle), not
    just the per-actor units the other tests in this file call directly.

    Pins the operator workflow documented in property-lists.rst: a dry-run
    followed by --migrate must actually perform the migration, not silently
    no-op because the dry-run itself created a checkpoint that made the
    --migrate run skip every actor."""

    def test_dry_run_does_not_poison_checkpoint_for_later_migrate_run(
        self, test_actor, monkeypatch, tmp_path
    ):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _only_this_actor(monkeypatch, test_actor.id)

        _seed_v1_list(
            test_actor.config, test_actor.id, "main_workflow_target", ["a", "b"]
        )

        checkpoint_file = str(tmp_path / "checkpoint.json")

        monkeypatch.setattr(
            sys,
            "argv",
            ["migrate_property_lists.py", "--checkpoint-file", checkpoint_file],
        )
        assert script.main() == 0
        assert not os.path.exists(checkpoint_file), (
            "dry-run must not leave a checkpoint file behind -- a later "
            "--migrate run would resume from it and skip every actor"
        )

        # Still v1 -- dry run wrote nothing.
        fresh = test_actor.property_lists.main_workflow_target
        assert fresh.verify().get("format") != 2

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "migrate_property_lists.py",
                "--migrate",
                "--checkpoint-file",
                checkpoint_file,
            ],
        )
        assert script.main() == 0

        migrated = test_actor.property_lists.main_workflow_target
        assert migrated.verify()["format"] == 2
        assert migrated.to_list() == ["a", "b"]

    def test_dry_run_exits_nonzero_when_a_list_needs_repair(
        self, test_actor, monkeypatch, tmp_path
    ):
        """ "Dry run came back 0" is what an operator checks before
        committing to the migration, so a fleet with a damaged list in it
        must not produce one."""
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _only_this_actor(monkeypatch, test_actor.id)

        _seed_v1_list(test_actor.config, test_actor.id, "dry_exit_holed", ["a", "b"])
        db = get_property(test_actor.config)
        assert db.set(actor_id=test_actor.id, name="list:dry_exit_holed-0", value=None)

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "migrate_property_lists.py",
                "--checkpoint-file",
                str(tmp_path / "checkpoint.json"),
            ],
        )
        assert script.main() == 1

    def test_concurrently_migrated_list_is_not_reported_as_refused(self, test_actor):
        """A list that another writer migrates between the sweep's verify()
        and migrate_to_v2()'s own fresh format re-read comes back as
        {"migrated": False, "reason": "already_v2"}.

        That is success -- the list IS in the requested format. Counting it
        as a refusal fails the run and, since only clean actors are
        checkpointed, makes the sweep re-do that actor on every run forever.
        The case only became reachable once migrate_to_v2() started
        re-reading the stored format itself. Regression for the second-round
        P2 on PR #121.
        """
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(test_actor.config, test_actor.id, "raced_list", ["a", "b"])

        real_migrate = ListProperty.migrate_to_v2

        def _migrate_after_someone_else_did(self, allow_damaged=False):
            # Stand in for a concurrent lazy migration landing in the gap.
            if self.name == "raced_list":
                other = ListProperty(
                    actor_id=self.actor_id, name=self.name, config=self.config
                )
                real_migrate(other)
            return real_migrate(self, allow_damaged=allow_damaged)

        with mock.patch.object(
            ListProperty, "migrate_to_v2", _migrate_after_someone_else_did
        ):
            _checked, _migrated, errored, refused = script.migrate_actor(
                test_actor.id,
                test_actor.config,
                migrate=True,
                limiter=script.RateLimiter(0),
            )

        assert refused == [], "a concurrently-migrated list is not a refusal"
        assert errored == 0
        assert test_actor.property_lists.raced_list.verify()["format"] == 2
        assert test_actor.property_lists.raced_list.to_list() == ["a", "b"]

    def test_actor_with_a_refused_list_is_not_checkpointed(
        self, test_actor, monkeypatch, tmp_path
    ):
        """An actor whose lists didn't all migrate must NOT be checkpointed.

        A '#'-named list is refused until an operator renames it. If the
        actor were checkpointed anyway, the next --migrate run would skip
        it, observe zero refusals, delete the checkpoint and exit 0 --
        reporting success over a list that was never migrated. Regression
        for the P1 raised on PR #121.
        """
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _only_this_actor(monkeypatch, test_actor.id)

        _seed_v1_list(test_actor.config, test_actor.id, "refused-#list", ["a"])
        _seed_v1_list(test_actor.config, test_actor.id, "fine_list", ["b", "c"])

        checkpoint_file = str(tmp_path / "checkpoint.json")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "migrate_property_lists.py",
                "--migrate",
                "--checkpoint-file",
                checkpoint_file,
            ],
        )
        assert script.main() == 1

        # The healthy list did migrate...
        assert test_actor.property_lists.fine_list.verify()["format"] == 2
        # ...but the actor is not claimed as done.
        if os.path.exists(checkpoint_file):
            with open(checkpoint_file) as fh:
                done = json.load(fh)
            assert test_actor.id not in done, (
                "an actor with a refused list must not be checkpointed -- "
                "the next --migrate run would skip it and exit 0"
            )

        # Second run still surfaces the refusal instead of skipping the actor.
        assert script.main() == 1


class TestDowngradeToV1:
    def test_downgrade_v2_list_to_v1(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        v2_list = test_actor.property_lists.downgrade_target
        for item in ["a", "b", "c"]:
            v2_list.append(item)

        result = script.downgrade_to_v1(
            test_actor.id, "downgrade_target", test_actor.config
        )

        assert result == {"downgraded": True, "item_count": 3}

        # Readable via v1 raw rows directly.
        db = get_property(test_actor.config)
        assert db.get(
            actor_id=test_actor.id, name="list:downgrade_target-0"
        ) == json.dumps("a")
        assert db.get(
            actor_id=test_actor.id, name="list:downgrade_target-2"
        ) == json.dumps("c")

        fresh = test_actor.property_lists.downgrade_target
        assert fresh.verify().get("format") != 2
        assert fresh.to_list() == ["a", "b", "c"]

    def test_downgrade_does_not_delete_a_hash_named_sibling_list(self, test_actor):
        """--downgrade's v2 cleanup must not delete a legacy '#'-named
        sibling list's rows.

        A list named "foo-#bar" stores "list:foo-#bar-0", which sorts inside
        the byte range v2 list "foo" occupies. The cleanup loop deletes every
        row it is handed, so reading that range directly (rather than through
        the rank-shape filter) silently emptied the sibling. Same failure mode
        as the P1 fixed in the library, reached from a call site that bypassed
        the filtered helper. Found by review, not by the existing downgrade
        tests -- none of them had a hash-named sibling present.
        """
        import migrate_property_lists as script  # type: ignore[import-not-found]

        # The innocent bystander: a pre-Phase-4 list whose name contains '#'.
        # Migration refuses these, so they stay v1 indefinitely, by design.
        _seed_v1_list(
            test_actor.config, test_actor.id, "sibling-#legacy", ["keep-1", "keep-2"]
        )

        # The downgrade target: a v2 list whose name is a prefix of it.
        target = test_actor.property_lists.sibling
        target.append("a")
        target.append("b")
        assert target.verify()["format"] == 2

        result = script.downgrade_to_v1(test_actor.id, "sibling", test_actor.config)
        assert result["downgraded"] is True
        assert result["item_count"] == 2

        # The target came back as v1 with its content intact...
        downgraded = test_actor.property_lists.sibling
        assert downgraded.verify().get("format") != 2
        assert downgraded.to_list() == ["a", "b"]

        # ...and the sibling was not touched.
        sibling = getattr(test_actor.property_lists, "sibling-#legacy")
        assert sibling.to_list() == ["keep-1", "keep-2"]

    def test_downgrade_v1_list_is_a_noop(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(test_actor.config, test_actor.id, "already_v1_target", ["a"])

        result = script.downgrade_to_v1(
            test_actor.id, "already_v1_target", test_actor.config
        )

        assert result == {"downgraded": False, "reason": "not_v2"}
