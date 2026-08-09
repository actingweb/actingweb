"""Smoke test for scripts/verify_property_lists.py's sweep logic.

Calls sweep_actor() directly (the script's per-actor unit) rather than
shelling out to main() -- exercises the same verify()/compact() codepath
against a seeded actor with a punched hole, and pins the report shape.
"""

import datetime
import json
import os
import sys
from pathlib import Path

import pytest

from actingweb.db import get_property
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def _seed_v1_list(config, actor_id, name, items):
    """Directly write a v1-format list (meta + dense-integer item rows) --
    ListProperty.append() now creates v2 (fractional rank key) lists by
    default (Phase 4), which have no dense-integer rows to punch a hole
    into. The sweep script must keep detecting/repairing v1 lists."""
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
        aw_type="urn:actingweb:test:verify_script",
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


class TestSweepActor:
    def test_dry_run_reports_unhealthy_without_repairing(self, test_actor):
        import verify_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(
            test_actor.config, test_actor.id, "sweep_test_list", ["a", "b", "c"]
        )
        prop_list = test_actor.property_lists.sweep_test_list

        db = get_property(test_actor.config)
        assert db.set(actor_id=test_actor.id, name="list:sweep_test_list-1", value=None)

        checked, unhealthy, errored = script.sweep_actor(
            test_actor.id,
            test_actor.config,
            repair=False,
            limiter=script.RateLimiter(0),
        )

        assert checked >= 1
        assert unhealthy >= 1
        assert errored == 0

        # Dry run must not have written anything -- the hole is still there.
        assert prop_list.verify()["healthy"] is False

    def test_repair_fixes_the_hole(self, test_actor):
        import verify_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(
            test_actor.config, test_actor.id, "sweep_test_list_2", ["a", "b", "c"]
        )

        db = get_property(test_actor.config)
        assert db.set(
            actor_id=test_actor.id, name="list:sweep_test_list_2-1", value=None
        )

        checked, unhealthy, errored = script.sweep_actor(
            test_actor.id,
            test_actor.config,
            repair=True,
            limiter=script.RateLimiter(0),
        )

        assert checked >= 1
        assert unhealthy == 0
        assert errored == 0

        # A fresh handle -- `prop_list` cached the pre-repair metadata
        # in-process, same as any long-lived caller would; the repair ran
        # through the script's own ListProperty instance.
        fresh = test_actor.property_lists.sweep_test_list_2
        assert fresh.verify()["healthy"] is True
        assert fresh.to_list() == ["a", "c"]

    def test_v2_lists_swept_alongside_v1_without_crashing(self, test_actor):
        """A v2 list's verify() report has a different shape than v1's
        (format/length/max_rank_length vs. stored_length/missing_indices/
        orphan_indices) -- sweep_actor() must not KeyError on it, and a
        healthy v2 list mixed into the same actor as an unhealthy v1 list
        must not affect the v1 repair outcome."""
        import verify_property_lists as script  # type: ignore[import-not-found]

        healthy_v2 = test_actor.property_lists.sweep_v2_healthy
        for item in ["a", "b"]:
            healthy_v2.append(item)

        _seed_v1_list(
            test_actor.config, test_actor.id, "sweep_v1_holed", ["x", "y", "z"]
        )
        db = get_property(test_actor.config)
        assert db.set(actor_id=test_actor.id, name="list:sweep_v1_holed-1", value=None)

        checked, unhealthy, errored = script.sweep_actor(
            test_actor.id,
            test_actor.config,
            repair=True,
            limiter=script.RateLimiter(0),
        )

        assert checked >= 2
        assert errored == 0
        assert unhealthy == 0

        fresh_v2 = test_actor.property_lists.sweep_v2_healthy
        assert fresh_v2.to_list() == ["a", "b"]
        fresh_v1 = test_actor.property_lists.sweep_v1_holed
        assert fresh_v1.verify()["healthy"] is True
        assert fresh_v1.to_list() == ["x", "z"]

    def test_v2_unhealthy_list_repaired_by_rank_rebalance(self, test_actor):
        """An unhealthy v2 list (rank keys grown long from repeated
        insert-between) has no missing_indices/orphan_indices to gate on --
        the repair must fire anyway, unlike v1's duplicate-only case."""
        import fractional_indexing as fi
        import verify_property_lists as script  # type: ignore[import-not-found]

        name = "sweep_v2_rebalance"
        # A real 140+-char rank takes hundreds of real insert() calls to
        # grow via repeated bisection -- too slow for a test. Precompute
        # one directly (pure library calls, no DB) and seed it, which is
        # equivalent to what those inserts would have produced.
        lo, hi = "a0", "a1"
        k = lo
        while len(k) < 141:
            k = fi.generate_key_between(lo, hi)
            lo = k

        db = get_property(test_actor.config)
        now = datetime.datetime.now().isoformat()
        meta = {
            "format": 2,
            "created_at": now,
            "updated_at": now,
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "",
            "explanation": "",
        }
        assert db.set(
            actor_id=test_actor.id, name=f"list:{name}-meta", value=json.dumps(meta)
        )
        assert db.set(
            actor_id=test_actor.id,
            name=f"list:{name}-#{lo}",
            value=json.dumps("left"),
        )
        assert db.set(
            actor_id=test_actor.id,
            name=f"list:{name}-#{hi}",
            value=json.dumps("right"),
        )

        lst = test_actor.property_lists.sweep_v2_rebalance
        before = lst.verify()
        assert before["healthy"] is False
        assert before["max_rank_length"] >= 141

        checked, unhealthy, errored = script.sweep_actor(
            test_actor.id,
            test_actor.config,
            repair=True,
            limiter=script.RateLimiter(0),
        )

        assert checked >= 1
        assert errored == 0
        assert unhealthy == 0

        fresh = test_actor.property_lists.sweep_v2_rebalance
        after = fresh.verify()
        assert after["healthy"] is True
        assert after["max_rank_length"] < 10
        assert after["length"] == 2
        assert fresh.to_list() == ["left", "right"]

    def test_checkpoint_round_trips(self, tmp_path):
        import verify_property_lists as script  # type: ignore[import-not-found]

        path = str(tmp_path / "checkpoint.json")
        cp = script.Checkpoint(path)
        assert not cp.is_done("actor-1")
        cp.mark_done("actor-1")
        assert cp.is_done("actor-1")

        cp2 = script.Checkpoint(path)
        assert cp2.is_done("actor-1")
        assert not cp2.is_done("actor-2")


class TestMainCommandLineWorkflow:
    """Exercises script.main() itself (argparse + checkpoint lifecycle), not
    just sweep_actor(). A dry-run that finds corruption must not leave a
    checkpoint behind -- a later --repair run resuming from it would skip
    every actor and report false-clean."""

    def test_dry_run_does_not_poison_checkpoint_for_later_repair_run(
        self, test_actor, monkeypatch, tmp_path
    ):
        import verify_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(
            test_actor.config, test_actor.id, "main_workflow_holed", ["a", "b", "c"]
        )
        db = get_property(test_actor.config)
        assert db.set(
            actor_id=test_actor.id, name="list:main_workflow_holed-1", value=None
        )

        checkpoint_file = str(tmp_path / "checkpoint.json")

        monkeypatch.setattr(
            sys,
            "argv",
            ["verify_property_lists.py", "--checkpoint-file", checkpoint_file],
        )
        assert script.main() == 1
        assert not os.path.exists(checkpoint_file), (
            "a dry-run that found corruption must not leave a checkpoint "
            "behind -- a later --repair run would resume from it and skip "
            "every actor, reporting false-clean"
        )

        prop_list = test_actor.property_lists.main_workflow_holed
        assert prop_list.verify()["healthy"] is False

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "verify_property_lists.py",
                "--repair",
                "--checkpoint-file",
                checkpoint_file,
            ],
        )
        assert script.main() == 0

        fresh = test_actor.property_lists.main_workflow_holed
        assert fresh.verify()["healthy"] is True
        assert fresh.to_list() == ["a", "c"]
