"""Reverse-lookup readiness against a real store (both backends).

Runs on the isolated store (``tests/integration/_isolated_store.py``) in the
``unique_creator`` xdist group; each test starts from an empty store. The
apps here say ``with_unique_creator(enable=False)`` explicitly: the uniqueness
default is a separate change and these tests are about the lookup check only.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from actingweb.config import Config
from actingweb.db import get_actor
from actingweb.interface import ActingWebApp, PropertyLookupNotReady
from actingweb.interface.actor_interface import ActorInterface
from actingweb.maintenance import property_lookup

from .conftest import DATABASE_BACKEND

pytestmark = [
    pytest.mark.xdist_group(name="unique_creator"),
    pytest.mark.usefixtures("real_lookup_probe"),
]

DYNAMODB = DATABASE_BACKEND == "dynamodb"


def _backfill(tmp_path: Path, *extra: str) -> int:
    """``backfill`` with a checkpoint file of its own: the default one is
    relative to the working directory, which parallel workers share."""
    return property_lookup.main(
        ["backfill", "--checkpoint-file", str(tmp_path / "ckpt.json"), *extra]
    )


def _app() -> ActingWebApp:
    return ActingWebApp(
        aw_type="urn:actingweb:test:lookup_readiness",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
    ).with_unique_creator(enable=False)


def _config() -> Config:
    return Config(
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="https://",
        aw_type="urn:actingweb:test:lookup_readiness",
        unique_creator=False,
        force_email_prop_as_creator=False,
    )


def _seed(config: Config, count: int) -> dict[str, str]:
    """Actors with an ``email`` property row and no lookup row, as the data
    of a deployment that predates the lookup table looks."""
    seeded: dict[str, str] = {}
    if DYNAMODB:
        from actingweb.db.dynamodb._ensure import ensure_table
        from actingweb.db.dynamodb.property import Property

        ensure_table(Property)
    for _ in range(count):
        actor_id = f"ready-{uuid.uuid4().hex}"
        email = f"{actor_id}@example.test"
        assert get_actor(config).create(
            actor_id=actor_id, creator=email, passphrase="x"
        )
        if DYNAMODB:
            Property(id=actor_id, name="email", value=email).save()
        else:
            from actingweb.db.postgresql.connection import get_connection

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO properties (id, name, value) VALUES (%s, 'email', %s)",
                    (actor_id, email),
                )
                conn.commit()
        seeded[actor_id] = email
    return seeded


class TestFreshStore:
    def test_an_empty_store_starts_twice_without_refusal(
        self, fresh_store: Any
    ) -> None:
        _app().check_ready()
        _app().check_ready()

    def test_a_standalone_check_ready_prewarms_a_missing_table(
        self, fresh_store: Any
    ) -> None:
        """``check_ready()`` alone, on a store with no tables yet, passes (it
        pre-warms the DynamoDB tables first, as ``integrate_*`` always did)."""
        _app().check_ready()

    def test_the_harness_integrates_on_an_empty_store(self, fresh_store: Any) -> None:
        from .test_harness import create_test_app

        create_test_app(
            fqdn="test.example.com",
            proto="https://",
            enable_oauth=False,
            enable_mcp=False,
            enable_devtest=False,
        )


class TestStoreWithData:
    def test_unbackfilled_data_refuses_then_the_backfill_makes_it_ready(
        self, fresh_store: Any, tmp_path: Path
    ) -> None:
        config = _config()
        seeded = _seed(config, 3)

        with pytest.raises(PropertyLookupNotReady) as raised:
            _app().check_ready()
        assert "actingweb-property-lookup" in str(raised.value)
        assert "email" in str(raised.value)

        assert _backfill(tmp_path, "--apply", "--segments", "2") == 0

        _app().check_ready()
        for actor_id, email in seeded.items():
            found = ActorInterface.get_by_property("email", email, config)
            assert found is not None and found.id == actor_id

    def test_a_dry_run_changes_nothing(self, fresh_store: Any, tmp_path: Path) -> None:
        _seed(_config(), 1)
        assert _backfill(tmp_path, "--segments", "1") == 0
        with pytest.raises(PropertyLookupNotReady):
            _app().check_ready()

    def test_unmark_makes_the_next_start_refuse(
        self, fresh_store: Any, tmp_path: Path
    ) -> None:
        _seed(_config(), 1)
        assert _backfill(tmp_path, "--apply", "--segments", "1") == 0
        _app().check_ready()
        assert property_lookup.main(["unmark", "--apply", "--properties", "email"]) == 0
        with pytest.raises(PropertyLookupNotReady):
            _app().check_ready()

    def test_mark_complete_refuses_unbackfilled_data(self, fresh_store: Any) -> None:
        _seed(_config(), 1)
        assert (
            property_lookup.main(["mark-complete", "--apply", "--properties", "email"])
            == 1
        )
        with pytest.raises(PropertyLookupNotReady):
            _app().check_ready()

    def test_no_indexed_names_needs_no_lookup_table(self, fresh_store: Any) -> None:
        _seed(_config(), 1)
        _app().with_indexed_properties([]).check_ready()
