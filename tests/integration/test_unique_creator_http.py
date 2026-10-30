"""Creator uniqueness over HTTP and at the fixed-id creates (3.16, PR 2).

The HTTP tests run against a harness with ``with_unique_creator()`` on the
isolated store (``unique_creator_app``); the bootstrap and startup tests call
the library in process on the same store. ``unique_creator`` xdist group.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any
from unittest import mock

import pytest
import requests

from actingweb.actor import Actor
from actingweb.db import get_actor
from actingweb.db.exceptions import CreatorTaken, DbError
from actingweb.interface import ActingWebApp, UniqueCreatorNotReady
from actingweb.maintenance import unique_creators

from .conftest import DATABASE_BACKEND

pytestmark = pytest.mark.xdist_group(name="unique_creator")

DYNAMODB = DATABASE_BACKEND == "dynamodb"


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _factory(url: str, creator: str, passphrase: str = "pw") -> requests.Response:
    return requests.post(
        f"{url}/",
        json={"creator": creator, "passphrase": passphrase},
        headers={"Accept": "application/json"},
        timeout=10,
    )


class TestFactory:
    def test_a_matching_passphrase_answers_403(
        self, unique_creator_app: str, enforced_store: Any
    ) -> None:
        creator = _email()
        first = _factory(unique_creator_app, creator)
        assert first.status_code == 201
        again = _factory(unique_creator_app, creator)
        assert again.status_code == 403
        body = again.json()
        assert body["message"] == "Creator already exists"
        assert first.json()["id"] not in again.text

    @pytest.mark.parametrize(
        "creator",
        [
            "#meta#backfill",
            "#x",
            "someone@example.com#dup-1a2b3c4d",
            "Someone@Example.com#DUP-1A2B3C4D",
            "system",
            "oauth2-system",
        ],
    )
    def test_reserved_creators_answer_400(
        self, unique_creator_app: str, enforced_store: Any, creator: str
    ) -> None:
        response = _factory(unique_creator_app, creator)
        assert response.status_code == 400
        assert get_actor(enforced_store).get_creator_holder(creator) is None

    def test_the_form_redirects_an_existing_creator_to_login(
        self, unique_creator_app: str, enforced_store: Any
    ) -> None:
        creator = _email()
        actor_id = _factory(unique_creator_app, creator).json()["id"]
        response = requests.post(
            f"{unique_creator_app}/",
            data={"creator": creator, "passphrase": "anything"},
            allow_redirects=False,
            timeout=10,
        )
        assert response.status_code == 302
        location = response.headers["Location"]
        assert location.endswith("/login")
        assert actor_id not in location


class TestTrusteeCreatorChange:
    def test_a_taken_creator_answers_409_and_changes_nothing(
        self, unique_creator_app: str, enforced_store: Any
    ) -> None:
        held, own = _email(), _email()
        other = _factory(unique_creator_app, held).json()
        mine = _factory(unique_creator_app, own).json()
        response = requests.put(
            f"{unique_creator_app}/{mine['id']}/trust/trustee",
            json={"creator": held, "trustee_root": "https://elsewhere.example/"},
            auth=(own, mine["passphrase"]),
            timeout=10,
        )
        assert response.status_code == 409
        assert response.json()["status_code"] == 409
        db = get_actor(enforced_store)
        assert (db.get(actor_id=mine["id"]) or {}).get("creator") == own
        assert (db.get(actor_id=other["id"]) or {}).get("creator") == held
        assert db.get_creator_holder(held) == other["id"]
        # Nothing else from the request was applied.
        store = Actor(actor_id=mine["id"], config=enforced_store).store
        assert store is not None and store.trustee_root is None

    @pytest.mark.parametrize(
        "suffix_or_value", ["#dup-00000000", "#DUP-0A0B0C0D", "system", "oauth2-system"]
    )
    def test_a_reserved_creator_answers_400(
        self, unique_creator_app: str, enforced_store: Any, suffix_or_value: str
    ) -> None:
        own = _email()
        mine = _factory(unique_creator_app, own).json()
        value = (
            f"{own.upper()}{suffix_or_value}"
            if suffix_or_value.startswith("#")
            else suffix_or_value
        )
        response = requests.put(
            f"{unique_creator_app}/{mine['id']}/trust/trustee",
            json={"creator": value},
            auth=(own, mine["passphrase"]),
            timeout=10,
        )
        assert response.status_code == 400
        row = get_actor(enforced_store).get(actor_id=mine["id"])
        assert row is not None and row["creator"] == own


def _race(target: Any, n: int = 2) -> list[Any]:
    barrier = threading.Barrier(n)
    results: list[Any] = []

    def run() -> None:
        barrier.wait()
        try:
            results.append(target())
        except Exception as e:  # noqa: BLE001 - recorded for the assert
            results.append(e)

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _winner_then_taken(config: Any, creator: str) -> Any:
    """``Actor.create`` as the loser of a bootstrap race under the flag: a
    concurrent request creates the actor, and this one's create hits the
    creator condition."""
    real_create = Actor.create

    def create(self: Actor, *args: Any, **kwargs: Any) -> bool:
        assert real_create(Actor(config=config), *args, **kwargs)
        raise CreatorTaken(creator)

    return mock.patch.object(Actor, "create", create)


class TestFixedIdCreates:
    def test_concurrent_oauth2_system_bootstraps_both_load_it(
        self, enforced_store: Any
    ) -> None:
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth2_server.system_actor import ensure_oauth2_system_actor

        results = _race(lambda: ensure_oauth2_system_actor(enforced_store))
        assert results == [OAUTH2_SYSTEM_ACTOR, OAUTH2_SYSTEM_ACTOR]
        assert Actor(OAUTH2_SYSTEM_ACTOR, config=enforced_store).actor

    def test_the_oauth2_system_bootstrap_loads_the_winner_on_creator_taken(
        self, enforced_store: Any
    ) -> None:
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth2_server.system_actor import ensure_oauth2_system_actor

        with _winner_then_taken(enforced_store, "oauth2-system"):
            assert ensure_oauth2_system_actor(enforced_store) == OAUTH2_SYSTEM_ACTOR
        assert Actor(OAUTH2_SYSTEM_ACTOR, config=enforced_store).actor

    def test_the_registry_loads_the_winner_on_creator_taken(
        self, enforced_store: Any
    ) -> None:
        from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR
        from actingweb.trust_type_registry import TrustTypeRegistry

        with _winner_then_taken(enforced_store, "system"):
            sys_actor = TrustTypeRegistry(enforced_store)._get_system_actor()
        assert sys_actor is not None and sys_actor.id == ACTINGWEB_SYSTEM_ACTOR

    def test_concurrent_registry_bootstraps_both_load_it(
        self, enforced_store: Any
    ) -> None:
        from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR
        from actingweb.trust_type_registry import TrustTypeRegistry

        results = _race(lambda: TrustTypeRegistry(enforced_store)._get_system_actor())
        assert [getattr(r, "id", r) for r in results] == [
            ACTINGWEB_SYSTEM_ACTOR,
            ACTINGWEB_SYSTEM_ACTOR,
        ]

    def _mcp(self, config: Any) -> Any:
        from tests.mcp_helpers import make_mcp_handler

        return make_mcp_handler(cfg=config)

    def test_two_mcp_bridge_requests_on_one_id_both_load_it(
        self, enforced_store: Any
    ) -> None:
        handler = self._mcp(enforced_store)
        actor_id = f"mcp{uuid.uuid4().hex}"
        email = _email()
        with _winner_then_taken(enforced_store, email):
            result = handler._get_or_create_actor_cached(
                actor_id, {"email": email}, 0.0
            )
        assert result is not None and result.id == actor_id

    def test_an_mcp_bridge_create_for_a_held_email_fails_closed(
        self, enforced_store: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        email = _email()
        holder = uuid.uuid4().hex
        assert get_actor(enforced_store).create(
            actor_id=holder, creator=email, passphrase="pw"
        )
        handler = self._mcp(enforced_store)
        actor_id = f"mcp{uuid.uuid4().hex}"
        with caplog.at_level(logging.ERROR):
            result = handler._get_or_create_actor_cached(
                actor_id, {"email": email}, 0.0
            )
        assert result is None
        assert f"Failed to create ActingWeb actor {actor_id}" in caplog.text
        assert get_actor(enforced_store).get(actor_id=actor_id) is None
        assert get_actor(enforced_store).get_creator_holder(email) == holder


def _app(unique: bool = True) -> ActingWebApp:
    return ActingWebApp(
        aw_type="urn:actingweb:test:unique_creator",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
    ).with_unique_creator(enable=unique)


class TestStartupCheck:
    def test_a_store_never_enabled_refuses_with_the_command_name(
        self, fresh_store: Any
    ) -> None:
        with pytest.raises(UniqueCreatorNotReady, match="actingweb-unique-creators"):
            _app().check_ready()

    @pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
    def test_a_table_without_its_backfill_item_refuses(self, fresh_store: Any) -> None:
        from actingweb.db.dynamodb.creator import Creator

        Creator.create_table(wait=True)
        with pytest.raises(UniqueCreatorNotReady, match="not backfilled"):
            _app().check_ready()

    @pytest.mark.skipif(DYNAMODB, reason="the index is PostgreSQL's")
    def test_an_invalid_index_refuses(self, enforced_store: Any) -> None:
        with mock.patch.object(
            unique_creators, "postgresql_index_state", return_value="invalid"
        ):
            with pytest.raises(UniqueCreatorNotReady, match="INVALID"):
                _app().check_ready()

    def test_an_enabled_store_starts(self, enforced_store: Any) -> None:
        _app().check_ready()

    def test_a_probe_fault_refuses_to_start(self, fresh_store: Any) -> None:
        # K8 (owner): fails closed, like definite absence.
        with mock.patch.object(
            unique_creators, "missing_enforcement", side_effect=DbError("probe")
        ):
            with pytest.raises(UniqueCreatorNotReady, match="could not be checked"):
                _app().check_ready()

    def test_the_flag_off_never_checks(self, fresh_store: Any) -> None:
        with mock.patch.object(
            unique_creators, "missing_enforcement", side_effect=AssertionError
        ):
            _app(unique=False).check_ready()

    def test_it_runs_once_per_process(self, enforced_store: Any) -> None:
        app = _app()
        app.check_ready()
        with mock.patch.object(
            unique_creators, "missing_enforcement", side_effect=AssertionError
        ):
            app.check_ready()
