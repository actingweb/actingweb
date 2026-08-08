"""Smoke test for scripts/verify_property_lists.py's sweep logic.

Calls sweep_actor() directly (the script's per-actor unit) rather than
shelling out to main() -- exercises the same verify()/compact() codepath
against a seeded actor with a punched hole, and pins the report shape.
"""

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

        prop_list = test_actor.property_lists.sweep_test_list
        for item in ["a", "b", "c"]:
            prop_list.append(item)

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

        prop_list = test_actor.property_lists.sweep_test_list_2
        for item in ["a", "b", "c"]:
            prop_list.append(item)

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
