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

import pytest

from actingweb.db import get_property
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp

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
        assert refused == [f"{test_actor.id}/bad-#name"]

        fresh = getattr(test_actor.property_lists, "bad-#name")
        assert fresh.verify().get("format") != 2
        assert fresh.to_list() == ["a"]

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

    def test_downgrade_v1_list_is_a_noop(self, test_actor):
        import migrate_property_lists as script  # type: ignore[import-not-found]

        _seed_v1_list(test_actor.config, test_actor.id, "already_v1_target", ["a"])

        result = script.downgrade_to_v1(
            test_actor.id, "already_v1_target", test_actor.config
        )

        assert result == {"downgraded": False, "reason": "not_v2"}
