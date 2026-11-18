"""A client registration that cannot create its trust row fails (3.16).

Registration writes the client's trust row first, then the client row and
the index row. A missing actor, a refused trust or an unexpected error fails
the registration with nothing stored (500 ``server_error`` on
``POST /oauth/register``, ``ClientRegistrationError`` from the registry); a
storage fault after the trust row was written removes that row and raises.

The trust row is created without listing the actor's relationships: the peer
id is already known.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.config import Config
from actingweb.constants import CLIENT_INDEX_BUCKET, OAUTH2_SYSTEM_ACTOR
from actingweb.db.exceptions import DbError
from actingweb.oauth2_server.client_registry import (
    ClientRegistrationError,
    MCPClientRegistry,
)
from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server
from tests.mcp_oauth_server_helpers import make_handler, make_server
from tests.mcp_token_double import MemoryStore, make_config

BODY = {"client_name": "Test", "redirect_uris": ["https://client/cb"]}


class _Actor:
    """``actingweb.actor.Actor`` for an actor that exists."""

    def __init__(self, actor_id: str | None = None, config: Any = None, **_k: Any):
        self.id = actor_id
        self.config = config
        self.actor = {"id": actor_id}
        self.store: dict[str, Any] = {}


class _NoActor(_Actor):
    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self.actor = None  # type: ignore[assignment]


class _TrustRows:
    """The trust table: what the fake trust creation writes and what the
    registry's removal deletes through ``actingweb.db.get_trust``."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.delete_fault: Exception | None = None
        self.delete_answer = True

    def get_trust(self, _config: Any) -> Any:
        rows = self

        class _Db:
            key: tuple[str, str] | None = None

            def get(self, actor_id: str, peerid: str) -> Any:
                self.key = (actor_id, peerid)
                return rows.rows.get(self.key)

            def delete(self) -> bool:
                if rows.delete_fault is not None:
                    raise rows.delete_fault
                if not rows.delete_answer:
                    return False
                assert self.key is not None
                return rows.rows.pop(self.key, None) is not None

        return _Db()


def _creation(rows: _TrustRows, *, answer: bool = True, fault: Any = None) -> Any:
    """``TrustManager.create_or_update_oauth_trust``: writes the row, then
    answers ``answer`` or raises ``fault`` (a fault on the token entry, which
    follows the row)."""
    from actingweb.interface.trust_manager import oauth_trust_peer_id

    def create(tm: Any, email: str, trust_type: str, **kwargs: Any) -> bool:
        peer_id = oauth_trust_peer_id(
            email,
            source=kwargs.get("established_via"),
            client_id=kwargs.get("client_id"),
        )
        if answer or fault is not None:
            rows.rows[(tm._core_actor.id, peer_id)] = {"peerid": peer_id}
        if fault is not None:
            raise fault
        return answer

    return create


@pytest.fixture
def env() -> Iterator[tuple[ActingWebOAuth2Server, MemoryStore, _TrustRows]]:
    config, store = make_config()
    rows = _TrustRows()
    with (
        mock.patch("actingweb.db.get_trust", rows.get_trust),
        mock.patch(
            "actingweb.oauth2_server.system_actor.ensure_oauth2_system_actor",
            return_value=OAUTH2_SYSTEM_ACTOR,
        ),
        mock.patch("actingweb.mcp.invalidation.evict_caches_for_actor"),
        mock.patch(
            "actingweb.permission_integration.default_client_trust_type",
            return_value="mcp_client",
        ),
    ):
        yield make_server(config), store, rows


def _nothing_stored(store: MemoryStore, rows: _TrustRows, actor_id: str) -> None:
    assert store.names(OAUTH2_SYSTEM_ACTOR, CLIENT_INDEX_BUCKET) == set()
    assert store.names(actor_id, "mcp_clients") == set()
    assert rows.rows == {}


def _failing_case(case: str, rows: _TrustRows) -> Any:
    if case == "missing actor":
        return mock.patch("actingweb.actor.Actor", _NoActor)
    if case == "trust refused":
        create = _creation(rows, answer=False)
    else:
        create = _creation(rows, fault=RuntimeError("boom mcp_x actor-owner"))
    return mock.patch(
        "actingweb.interface.trust_manager.TrustManager.create_or_update_oauth_trust",
        create,
    )


CASES = ["missing actor", "trust refused", "unexpected error"]


def _register_through_the_endpoint(server: ActingWebOAuth2Server) -> tuple[Any, int]:
    handler = make_handler(server, body=BODY, json_body=True)
    out = handler._handle_client_registration()  # pyright: ignore[reportPrivateUsage]
    return out, handler.response.status_code


@pytest.mark.parametrize("case", CASES)
def test_a_registration_without_its_trust_row_is_a_server_error(
    env: Any, case: str
) -> None:
    server, store, rows = env
    with mock.patch("actingweb.actor.Actor", _Actor), _failing_case(case, rows):
        out, status = _register_through_the_endpoint(server)
    assert status == 500
    assert out["error"] == "server_error"
    _nothing_stored(store, rows, OAUTH2_SYSTEM_ACTOR)


@pytest.mark.parametrize("case", CASES)
def test_the_server_error_names_no_client_and_no_actor(env: Any, case: str) -> None:
    server, _store, rows = env
    with mock.patch("actingweb.actor.Actor", _Actor), _failing_case(case, rows):
        out, _status = _register_through_the_endpoint(server)
    text = json.dumps(out)
    assert "mcp_" not in text
    assert "client_secret" not in text
    assert OAUTH2_SYSTEM_ACTOR not in text
    assert "actor-owner" not in text


def test_a_registration_on_a_missing_system_actor_is_a_server_error(
    env: Any,
) -> None:
    # ensure_oauth2_system_actor answers the id also when the actor could
    # not be created; the registration on it now fails.
    server, store, rows = env
    with mock.patch("actingweb.actor.Actor", _NoActor):
        out, status = _register_through_the_endpoint(server)
    assert status == 500
    assert out["error"] == "server_error"
    _nothing_stored(store, rows, OAUTH2_SYSTEM_ACTOR)


@pytest.mark.parametrize("case", CASES)
def test_the_registry_raises_client_registration_error(env: Any, case: str) -> None:
    server, store, rows = env
    with (
        mock.patch("actingweb.actor.Actor", _Actor),
        _failing_case(case, rows),
        pytest.raises(ClientRegistrationError),
    ):
        server.client_registry.register_client("actor-owner", dict(BODY))
    _nothing_stored(store, rows, "actor-owner")


def _created(rows: _TrustRows) -> Any:
    return mock.patch(
        "actingweb.interface.trust_manager.TrustManager.create_or_update_oauth_trust",
        _creation(rows),
    )


@pytest.mark.parametrize("write", ["_store_client", "_update_global_index"])
def test_a_fault_on_the_client_writes_raises_and_removes_the_trust_row(
    env: Any, write: str
) -> None:
    server, store, rows = env
    registry = server.client_registry
    with (
        mock.patch("actingweb.actor.Actor", _Actor),
        _created(rows),
        mock.patch.object(registry, write, side_effect=DbError("write", "actor-owner")),
        pytest.raises(DbError),
    ):
        registry.register_client("actor-owner", dict(BODY))
    assert rows.rows == {}
    assert store.names(OAUTH2_SYSTEM_ACTOR, CLIENT_INDEX_BUCKET) == set()


def test_a_fault_inside_trust_creation_after_its_row_removes_the_row(
    env: Any,
) -> None:
    server, store, rows = env
    create = _creation(rows, fault=DbError("token entry", "actor-owner"))
    with (
        mock.patch("actingweb.actor.Actor", _Actor),
        mock.patch(
            "actingweb.interface.trust_manager.TrustManager.create_or_update_oauth_trust",
            create,
        ),
        pytest.raises(DbError),
    ):
        server.client_registry.register_client("actor-owner", dict(BODY))
    _nothing_stored(store, rows, "actor-owner")


@pytest.mark.parametrize("removal", ["faults", "is not confirmed"])
def test_a_failed_trust_row_removal_is_logged_and_the_first_fault_raised(
    env: Any, removal: str, caplog: pytest.LogCaptureFixture
) -> None:
    server, _store, rows = env
    registry = server.client_registry
    first = DbError("client write", "actor-owner")
    if removal == "faults":
        rows.delete_fault = DbError("trust delete", "actor-owner")
    else:
        rows.delete_answer = False
    with (
        caplog.at_level(logging.ERROR),
        mock.patch("actingweb.actor.Actor", _Actor),
        _created(rows),
        mock.patch.object(registry, "_store_client", side_effect=first),
        pytest.raises(DbError) as raised,
    ):
        registry.register_client("actor-owner", dict(BODY))
    assert raised.value is first
    ((_actor, peer_id),) = rows.rows
    assert any(
        peer_id in r.getMessage() and r.levelno >= logging.ERROR for r in caplog.records
    )


def test_the_trust_row_is_created_without_listing_relationships() -> None:
    config = Config(unique_creator=False)
    registry = MCPClientRegistry.__new__(MCPClientRegistry)
    registry.config = config  # type: ignore[attr-defined]

    core_actor = mock.Mock()
    core_actor.actor = mock.Mock()
    trust_manager = mock.Mock()
    trust_manager.create_or_update_oauth_trust.return_value = True
    relationships = mock.PropertyMock(side_effect=AssertionError("listed trusts"))

    with (
        mock.patch("actingweb.actor.Actor", return_value=core_actor),
        mock.patch(
            "actingweb.interface.trust_manager.TrustManager",
            return_value=trust_manager,
        ),
        mock.patch(
            "actingweb.interface.actor_interface.ActorInterface.trust",
            new_callable=lambda: relationships,
            create=True,
        ),
    ):
        registry._create_client_trust_relationship(  # pyright: ignore[reportPrivateUsage]
            "actor-1",
            "client-1",
            {"client_name": "c", "client_secret": "s", "created_at": 1},
        )

    trust_manager.create_or_update_oauth_trust.assert_called_once()
    relationships.assert_not_called()
