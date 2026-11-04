"""Deleting a connection to an OAuth2 client ends that connection only (3.16).

Audit 2026-11-04 (thoughts/research/2026-11-04-client-deletion-lifecycle-audit.md):
``Trust.delete`` on any actor's client row deleted the client itself, and
with it the global index row, disabling the client for every actor (D1).
Now a row's actor deletes the client only when the client is registered
under it; otherwise it revokes its own tokens and deletes its own rows.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, patch

import pytest

from actingweb.db.exceptions import DbError
from actingweb.trust import Trust

REGISTRY = "actingweb.oauth2_server.client_registry.get_mcp_client_registry"


@pytest.fixture(autouse=True)
def _row_side_stores() -> Any:
    """The permission and provider-token stores ``Trust.delete`` clears
    right after the row; these unit tests use a mock ``Config``."""
    with (
        patch("actingweb.trust_permissions.TrustPermissionStore") as permissions,
        patch("actingweb.attribute.InternalStore") as store,
    ):
        permissions.return_value.get_permissions.return_value = None
        store.return_value.set_confirmed.return_value = True
        yield


def _trust(data: dict[str, Any], *, deleted: bool = True) -> tuple[Trust, Mock]:
    config = Mock()
    db_trust = Mock()
    db_trust.get.return_value = data
    db_trust.delete.return_value = deleted
    config.DbTrust.DbTrust.return_value = db_trust
    return Trust(actor_id="actor-y", peerid=data["peerid"], config=config), db_trust


def _registry(*, owner: bool) -> Mock:
    registry = Mock()
    registry.client_owned_by.return_value = owner
    registry.delete_client.return_value = True
    return registry


TAGGED = {
    "peerid": "oauth2_client:y_at_x_dot_com:mcp_ab12",
    "oauth_client_id": "mcp_ab12",
    "established_via": "oauth2_client",
}


def test_a_connection_of_another_actors_client_never_deletes_the_client() -> None:
    trust, db_trust = _trust(TAGGED)
    registry = _registry(owner=False)
    calls: list[str] = []
    registry.revoke_connection_tokens.side_effect = lambda *a: calls.append("revoke")
    db_trust.delete.side_effect = lambda: calls.append("row") or True
    with patch(REGISTRY, return_value=registry):
        assert trust.delete() is True
    registry.client_owned_by.assert_called_once_with("actor-y", "mcp_ab12")
    registry.delete_client.assert_not_called()
    assert calls == ["revoke", "row"], "tokens go before the row"
    registry._delete_client_trust_relationship.assert_called_once_with(
        "actor-y", "mcp_ab12"
    )


def test_the_owner_deletes_its_client() -> None:
    trust, _ = _trust(TAGGED)
    registry = _registry(owner=True)
    with patch(REGISTRY, return_value=registry):
        assert trust.delete() is True
    registry.delete_client.assert_called_once_with("mcp_ab12", actor_id="actor-y")
    registry.revoke_connection_tokens.assert_not_called()


def test_a_revocation_fault_keeps_the_row_as_the_retry_handle() -> None:
    trust, db_trust = _trust(TAGGED)
    registry = _registry(owner=False)
    registry.revoke_connection_tokens.side_effect = DbError("token revoke")
    with patch(REGISTRY, return_value=registry), pytest.raises(DbError):
        trust.delete()
    db_trust.delete.assert_not_called()


def test_a_failed_client_deletion_is_raised_not_folded() -> None:
    """The trust UI answered 204 while the client stayed live (D4)."""
    trust, _ = _trust(TAGGED)
    registry = _registry(owner=True)
    registry.delete_client.return_value = False
    with patch(REGISTRY, return_value=registry), pytest.raises(DbError):
        trust.delete()


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"peerid": "oauth2:y_at_x_dot_com:mcp_ab12"}, "mcp_ab12"),  # legacy, D5
        ({"peerid": "oauth2_client:mcp_ab12:mcp_ab12"}, "mcp_ab12"),
        ({"peerid": "oauth2_interactive:y_at_x_dot_com"}, None),
        ({"peerid": "0123abcd", "relationship": "friend"}, None),
        ({"peerid": "oauth2:y:z", "oauth_client_id": "mcp_tag"}, "mcp_tag"),
        # A peer-created row (POST /trust) is recorded as established via
        # "trust": its peer id never names a client.
        (
            {"peerid": "oauth2_client:x:mcp_ab12", "established_via": "trust"},
            None,
        ),
        (
            {
                "peerid": "0123abcd",
                "established_via": "trust",
                "oauth_client_id": "mcp_ab12",
            },
            None,
        ),
    ],
)
def test_the_client_id_is_read_from_the_tag_then_any_oauth2_peer_id(
    data: dict[str, Any], expected: str | None
) -> None:
    trust, _ = _trust(data)
    trust.get()
    assert trust._oauth2_client_id() == expected


def test_a_legacy_oauth2_row_ends_its_connection() -> None:
    """D5: an ``oauth2:`` row authorises (arm 2) but cascaded nothing."""
    trust, _ = _trust({"peerid": "oauth2:y_at_x_dot_com:mcp_ab12"})
    registry = _registry(owner=False)
    with patch(REGISTRY, return_value=registry):
        assert trust.delete() is True
    registry.revoke_connection_tokens.assert_called_once_with("actor-y", "mcp_ab12")


def test_delete_client_refuses_a_caller_that_does_not_own_the_client() -> None:
    from actingweb.config import Config
    from actingweb.oauth2_server.client_registry import MCPClientRegistry

    registry = MCPClientRegistry.__new__(MCPClientRegistry)
    registry.config = Config(mcp=True, unique_creator=False)
    with (
        patch.object(registry, "_load_client", return_value={"actor_id": "actor-x"}),
        patch("actingweb.single_use.delete_confirmed") as delete_confirmed,
    ):
        assert registry.delete_client("mcp_ab12", actor_id="actor-y") is False
    delete_confirmed.assert_not_called()


class TestTheTokenSweepMarksEveryChainFirst:
    """D8: a refresh whose consume preceded the sweep must find a marker."""

    def _manager(self, rows: dict[str, dict[str, Any]]) -> Any:
        from actingweb.oauth2_server.token_manager import ActingWebTokenManager

        manager = ActingWebTokenManager.__new__(ActingWebTokenManager)
        manager.config = Mock()
        manager.tokens_bucket = "mcp_tokens"
        manager.refresh_tokens_bucket = "mcp_refresh_tokens"
        manager.revoked_chains_bucket = "mcp_revoked_chains"
        manager._snapshot_bucket = Mock(  # type: ignore[method-assign]
            side_effect=lambda _a, bucket: rows.get(bucket, {})
        )
        return manager

    def test_chains_are_marked_before_any_token_is_removed(self) -> None:
        events: list[str] = []
        rows = {
            "mcp_tokens": {"at": {"data": {"client_id": "c", "chain_id": "k1"}}},
            "mcp_refresh_tokens": {
                "rt": {"data": {"client_id": "c", "chain_id": "k2"}},
                "other": {"data": {"client_id": "d", "chain_id": "k3"}},
            },
        }
        manager = self._manager(rows)
        manager._remove_access_token = lambda name, **_k: events.append(name) or True
        manager._remove_refresh_token_row = lambda _a, name: events.append(name) or True
        with patch(
            "actingweb.oauth2_server.token_manager.mark_chain_revoked",
            side_effect=lambda _c, _a, _b, chain: events.append(f"mark:{chain}"),
        ):
            assert manager.revoke_client_tokens("actor-y", "c") == 2
        assert events == ["mark:k1", "mark:k2", "at", "rt"]

    def test_an_unmarkable_chain_keeps_its_tokens_and_raises(self) -> None:
        from actingweb.oauth2_server.token_manager import TokenStoreUnavailable
        from actingweb.single_use import StoreFault

        rows = {
            "mcp_refresh_tokens": {"rt": {"data": {"client_id": "c", "chain_id": "k"}}}
        }
        manager = self._manager(rows)
        manager._remove_refresh_token_row = Mock(return_value=True)
        manager._remove_access_token = Mock(return_value=True)
        with (
            patch(
                "actingweb.oauth2_server.token_manager.mark_chain_revoked",
                side_effect=StoreFault("marker write"),
            ),
            pytest.raises(TokenStoreUnavailable),
        ):
            manager.revoke_client_tokens("actor-y", "c")
        manager._remove_refresh_token_row.assert_not_called()


@pytest.mark.parametrize(
    "peer_id",
    [
        "oauth2_client:y_at_x_dot_com:mcp_ab12",
        "oauth2:a:b",
        "oauth2_interactive:a",
        "oauth2",
    ],
)
def test_a_peer_cannot_take_an_oauth2_peer_id(peer_id: str) -> None:
    """A trust create overwrites a row with the same peer id, and the
    library's OAuth2 peer ids are deterministic: a peer naming one through
    POST /trust would replace a user's client connection."""
    from actingweb.trust import is_valid_peer_id

    assert not is_valid_peer_id(peer_id)
    assert is_valid_peer_id("9f2c1a7e0b4d4c3e8a1f")
    assert is_valid_peer_id("oauth3:not-ours")


def test_ownership_is_the_actors_own_row_naming_it() -> None:
    from actingweb.config import Config
    from actingweb.oauth2_server.client_registry import MCPClientRegistry

    registry = MCPClientRegistry.__new__(MCPClientRegistry)
    registry.config = Config(mcp=True, unique_creator=False)
    registry.clients_bucket = "mcp_clients"
    for row, expected in [
        ({"data": {"actor_id": "actor-y"}}, True),
        ({"data": {"actor_id": "actor-x"}}, False),  # copied or restored
        ({"data": "garbage"}, False),
        (None, False),
    ]:
        with patch("actingweb.attribute.Attributes") as attributes:
            attributes.return_value.get_attr.return_value = row
            assert registry.client_owned_by("actor-y", "mcp_ab12") is expected


def test_delete_client_without_an_index_row_refuses_a_non_owner() -> None:
    from actingweb.config import Config
    from actingweb.oauth2_server.client_registry import MCPClientRegistry

    registry = MCPClientRegistry.__new__(MCPClientRegistry)
    registry.config = Config(mcp=True, unique_creator=False)
    with (
        patch.object(registry, "_load_client", return_value=None),
        patch.object(registry, "client_owned_by", return_value=False),
        patch("actingweb.single_use.delete_confirmed") as delete_confirmed,
    ):
        assert registry.delete_client("mcp_ab12", actor_id="actor-y") is False
    delete_confirmed.assert_not_called()


def test_actor_deletion_keeps_an_index_row_naming_another_actor() -> None:
    from actingweb.config import Config
    from actingweb.oauth2_server.client_registry import MCPClientRegistry

    registry = MCPClientRegistry.__new__(MCPClientRegistry)
    registry.config = Config(mcp=True, unique_creator=False)
    with (
        patch("actingweb.attribute.Attributes") as attributes,
        patch("actingweb.single_use.delete_confirmed") as delete_confirmed,
    ):
        attributes.return_value.get_attr.return_value = {"data": "actor-x"}
        assert registry.delete_client(
            "mcp_ab12", actor_id="actor-y", actor_deleted=True
        )
    delete_confirmed.assert_not_called()
