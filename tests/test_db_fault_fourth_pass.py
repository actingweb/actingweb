"""Fourth iteration on the fault contract: the follow-ons from
``thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-3.md``
(C3, F3, G3, I3) and the five items bundled from the follow-ups todo.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb.actor import Actor
from actingweb.db import get_actor, get_attribute
from actingweb.db.exceptions import DbError
from tests._adoption_helpers import (
    aid,
    backend_fault,
    istore,
    make_config,
    raise_db_error,
    uuid_email,
)


def _raise(*_a: Any, **_k: Any) -> Any:
    raise DbError("simulated backend fault")


class TestC3ErrorCors:
    def test_the_spa_routes_get_the_allowlist_headers(self) -> None:
        from actingweb.interface.integrations._errors import error_cors_headers

        config = make_config()
        for path in (
            "/oauth/session",
            "/oauth/revoke",
            "/oauth/config",
            "/oauth/spa/token",
        ):
            headers = error_cors_headers(path, "https://spa.example.com", config)
            assert (
                headers.get("Access-Control-Allow-Origin") == "https://spa.example.com"
            )

    def test_the_oauth2_endpoints_get_wildcard_headers(self) -> None:
        from actingweb.interface.integrations._errors import error_cors_headers

        headers = error_cors_headers(
            "/oauth/token", "https://x.example.com", make_config()
        )
        assert headers.get("Access-Control-Allow-Origin") == "*"
        assert "Retry-After" in headers.get("Access-Control-Expose-Headers", "")

    def test_other_routes_get_none(self) -> None:
        from actingweb.interface.integrations._errors import error_cors_headers

        assert error_cors_headers("/abc/properties", "https://x", make_config()) == {}


class TestF3McpPermanentFault:
    def test_a_permanent_fault_answers_500_without_retry_after(self) -> None:
        from tests.mcp_helpers import make_mcp_handler

        handler = make_mcp_handler()
        cause = Exception("Item size has exceeded the maximum allowed size")
        cause.cause_response_code = "ValidationException"  # type: ignore[attr-defined]

        def permanent(*_a: Any, **_k: Any) -> Any:
            raise DbError("attribute set") from cause

        with (
            mock.patch.object(handler, "_handle_tools_list", permanent),
            mock.patch.object(
                handler, "authenticate_and_get_actor_cached", return_value=mock.Mock()
            ),
        ):
            handler.post({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})

        assert handler.response.status_code == 500
        assert "Retry-After" not in handler.response.headers


class TestG3MarkerFault:
    def test_a_marker_write_fault_raises_and_leaves_no_actor(self) -> None:
        config = make_config()
        actor_id = f"g3{uuid.uuid4().hex}"
        actor = Actor(config=config)

        with (
            backend_fault(
                config,
                "set_attr",
                lambda a, b, n: b == "_internal" and n == "auth_method",
                raise_db_error,
            ),
            pytest.raises(DbError),
        ):
            actor.create(
                url="https://test.example.com/",
                creator=uuid_email(),
                passphrase="pw",
                actor_id=actor_id,
                auth_method="factory",
            )

        assert actor.id is None
        assert not Actor(actor_id=actor_id, config=config).id


class TestI3ProviderBookkeeping:
    def test_a_vouched_sign_in_survives_a_provider_write_fault(self) -> None:
        from actingweb import oauth2 as oauth2_module
        from actingweb.oauth2 import OAuth2Provider

        config = make_config()
        actor = Actor(config=config)
        assert actor.create(
            url="https://test.example.com/",
            creator=uuid_email(),
            passphrase="pw",
            auth_method="google_oauth2",
        )
        provider = OAuth2Provider("google", {"client_id": "c", "client_secret": "s"})

        with backend_fault(
            config,
            "set_attr",
            lambda a, b, n: a == aid(actor) and n == "oauth_provider",
            raise_db_error,
        ):
            result = oauth2_module.adopt_actor(
                Actor(actor_id=aid(actor), config=config),
                provider=provider,
                config=config,
                hooks=None,
            )

        assert result is not None and result.id == aid(actor)


class TestBundledMaintenanceExitCodes:
    @pytest.mark.parametrize(
        "module", ["migrate_property_lists", "verify_property_lists"]
    )
    def test_an_unreadable_actor_list_exits_2(
        self, module: str, monkeypatch: Any
    ) -> None:
        import importlib

        tool = importlib.import_module(f"actingweb.maintenance.{module}")
        failing = mock.Mock()
        failing.return_value.fetch.side_effect = DbError("actor list fetch")
        monkeypatch.setattr("sys.argv", [module])
        monkeypatch.setattr("actingweb.db.get_actor_list", failing)
        assert tool.main() == 2

    @pytest.mark.parametrize(
        "module", ["migrate_property_lists", "verify_property_lists"]
    )
    def test_a_folded_actor_list_exits_2_not_0(
        self, module: str, monkeypatch: Any
    ) -> None:
        import importlib

        tool = importlib.import_module(f"actingweb.maintenance.{module}")
        folding = mock.Mock()
        folding.return_value.fetch.return_value = False
        monkeypatch.setattr("sys.argv", [module])
        monkeypatch.setattr("actingweb.db.get_actor_list", folding)
        assert tool.main() == 2


class TestBundledRegistryRetry:
    def test_a_fault_registering_the_defaults_is_retried(self) -> None:
        from actingweb import trust_type_registry as registry_module

        config = make_config()
        monkey_target = registry_module._register_default_types
        registry_module._registry = None
        with (
            mock.patch.object(registry_module, "_register_default_types", _raise),
            pytest.raises(DbError),
        ):
            registry_module.get_registry(config)
        assert registry_module._registry is None

        with mock.patch.object(
            registry_module, "_register_default_types", wraps=monkey_target
        ) as registered:
            registry_module.get_registry(config)
        registered.assert_called_once()


class TestBundledStoreCache:
    def test_a_failed_write_is_not_cached(self) -> None:
        from tests._adoption_helpers import create_core_actor

        config = make_config()
        actor = create_core_actor(config, uuid_email())
        store = istore(actor)
        store.loaded  # noqa: B018 - load before the fault
        with (
            backend_fault(
                config,
                "set_attr",
                lambda a, b, n: n == "oauth_provider",
                raise_db_error,
            ),
            pytest.raises(DbError),
        ):
            store.oauth_provider = "github"
        assert store.oauth_provider is None


class TestBundledCreatorFallback:
    def test_a_pick_deleted_after_the_ranking_falls_back_to_the_next(self) -> None:
        config = make_config()
        creator = uuid_email()
        first = Actor(config=config)
        assert first.create(
            url="https://x/",
            creator=creator,
            passphrase="p",
            actor_id=f"00{uuid.uuid4().hex}",
        )
        second = Actor(config=config)
        assert second.create(
            url="https://x/",
            creator=creator,
            passphrase="p",
            actor_id=f"ff{uuid.uuid4().hex}",
        )
        real_get = Actor.get
        first_id = aid(first)

        def vanishing(self: Actor, actor_id: str | None = None) -> Any:
            if actor_id == first_id:
                self.id = None
                return None  # deleted between the ranking and the load
            return real_get(self, actor_id=actor_id)

        lookup = Actor(config=config)
        with mock.patch.object(Actor, "get", vanishing):
            assert lookup.get_from_creator(creator) is True
        assert lookup.id == aid(second)


class TestBundledKeyNotLogged:
    def test_a_generated_fallback_key_is_not_logged(self, caplog: Any) -> None:
        from actingweb.oauth2_server import state_manager

        config = make_config()
        with (
            mock.patch(
                "actingweb.oauth2_server.system_actor.ensure_oauth2_system_actor",
                side_effect=RuntimeError("not a DB fault"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            manager = state_manager.OAuth2StateManager(config)

        import base64

        key_text = base64.urlsafe_b64encode(manager.encryption_key).decode("utf-8")
        assert key_text not in caplog.text
        assert get_actor(config) is not None and get_attribute(config) is not None
