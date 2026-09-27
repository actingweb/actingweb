"""Build the MCP OAuth2 server and its endpoint handler on the in-memory store.

``ActingWebOAuth2Server.__init__`` probes the configured login providers; the
grant, registration and PKCE tests do not need that, so the server is built
around the real registry, token manager and state manager directly.
"""

import contextlib
import json
from collections.abc import Iterator
from typing import Any
from unittest import mock
from urllib.parse import urlencode

from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.handlers.oauth2_endpoints import OAuth2EndpointsHandler
from actingweb.oauth2_server.client_registry import MCPClientRegistry
from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server
from actingweb.oauth2_server.state_manager import get_oauth2_state_manager
from actingweb.oauth2_server.token_manager import ActingWebTokenManager


class _NoActor:
    """Stands in for ``actingweb.actor.Actor`` so registration skips the
    client trust row (it needs a real actor store)."""

    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.actor = None


def make_server(config: Config) -> ActingWebOAuth2Server:
    server = ActingWebOAuth2Server.__new__(ActingWebOAuth2Server)
    server.config = config
    server.client_registry = MCPClientRegistry(config)
    server.token_manager = ActingWebTokenManager(config)
    server.state_manager = get_oauth2_state_manager(config)
    server._authenticator_cache = {}
    return server


@contextlib.contextmanager
def no_actor_store() -> Iterator[None]:
    with mock.patch("actingweb.actor.Actor", _NoActor):
        yield


def register(server: ActingWebOAuth2Server, **metadata: Any) -> dict[str, Any]:
    body = {"client_name": "Test", "redirect_uris": ["https://client/cb"]}
    body.update(metadata)
    with no_actor_store():
        return server.client_registry.register_client("actor-owner", body)


def make_handler(
    server: ActingWebOAuth2Server,
    *,
    body: dict[str, Any] | str | None = None,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    json_body: bool = False,
) -> OAuth2EndpointsHandler:
    if isinstance(body, dict):
        raw = json.dumps(body) if json_body else urlencode(body)
    else:
        raw = body or ""
    webobj = AWWebObj(
        url="https://test.example.com/oauth/token",
        params=params or {},
        body=raw,
        headers=headers if headers is not None else {"Accept": "application/json"},
        cookies={},
    )
    with mock.patch(
        "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
        return_value=server,
    ):
        return OAuth2EndpointsHandler(webobj, server.config, hooks=None)
