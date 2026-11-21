"""Permission-change notifications to OAuth2/MCP peers (4.0.0rc2).

``thoughts/plans/2026-11-21-trust-request-answer-secret.md``, phase 2: a
peer whose id has an OAuth2 prefix has no base URI by construction, so a
permission change does not try to notify it and logs nothing above DEBUG;
any other peer whose trust has no base URI still logs a WARNING. Both the
sync (``_notify_peer``) and the async (``_notify_peer_async``) path.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from actingweb.trust_permissions import TrustPermissions, TrustPermissionStore

LOGGER = "actingweb.trust_permissions"
OAUTH2_PEERS = [
    "oauth2:google:someone",
    "oauth2_client:mcp_0123456789abcdef",
    "oauth2_interactive:web:someone",
]


def _store() -> TrustPermissionStore:
    config = Mock()
    config.notify_peer_on_change = True
    config.database = "dynamodb"
    return TrustPermissionStore(config)


def _permissions(peer_id: str) -> TrustPermissions:
    return TrustPermissions(actor_id="a", peer_id=peer_id, trust_type="mcp_client")


async def _notify(
    store: TrustPermissionStore, peer_id: str, path: str
) -> tuple[Mock, Mock, AsyncMock]:
    """Run one path's notification for ``peer_id``, whose trust row exists
    with no base URI. Returns the patched proxy class, Trust class and HTTP
    client."""
    client = AsyncMock()
    client.__aenter__.return_value = client
    with (
        patch("actingweb.aw_proxy.AwProxy") as proxy_class,
        patch("actingweb.trust.Trust") as trust_class,
        patch("httpx.AsyncClient", return_value=client),
        patch.object(store, "_build_callback_data", return_value={}),
    ):
        proxy = proxy_class.return_value
        proxy.trust = {"peerid": peer_id, "baseuri": "", "secret": "s"}
        # AwProxy answers None and leaves the code at 0 without a base URI.
        proxy.create_resource.return_value = None
        proxy.last_response_code = 0
        trust_class.return_value.get.return_value = {
            "peerid": peer_id,
            "baseuri": "",
            "secret": "s",
        }
        if path == "sync":
            store._notify_peer(_permissions(peer_id))  # noqa: SLF001
        else:
            await store._notify_peer_async(_permissions(peer_id))  # noqa: SLF001
    return proxy_class, trust_class, client


@pytest.mark.parametrize("path", ["sync", "async"])
@pytest.mark.parametrize("peer_id", OAUTH2_PEERS)
async def test_an_oauth2_peer_is_not_notified(
    peer_id: str, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-14."""
    store = _store()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        proxy_class, trust_class, client = await _notify(store, peer_id, path)
    proxy_class.assert_not_called()
    trust_class.assert_not_called()
    client.post.assert_not_called()
    above_debug = [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER and r.levelno > logging.DEBUG
    ]
    assert above_debug == []


@pytest.mark.parametrize("path", ["sync", "async"])
@pytest.mark.parametrize("peer_id", ["peer-without-baseuri", "my-oauth2:peer"])
async def test_a_peer_without_baseuri_still_warns(
    peer_id: str, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-15 (regression): only an OAuth2 prefix is skipped; an id that
    merely contains ``oauth2`` is not."""
    store = _store()
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await _notify(store, peer_id, path)
    warnings: list[Any] = [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER and r.levelno == logging.WARNING
    ]
    assert any(peer_id in message for message in warnings), warnings
