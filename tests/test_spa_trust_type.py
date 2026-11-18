"""The SPA authorize route applies the client list to ``trust_type``
(3.16, plan Phase 3): the field is the level for an MCP client."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest import mock

from actingweb.aw_web_request import AWWebObj


def _authorize(trust_type: str | None, **extra: str) -> dict:
    from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

    body = {"provider": "google", "redirect_uri": "https://app.example/cb", **extra}
    if trust_type is not None:
        body["trust_type"] = trust_type
    handler = OAuth2SPAHandler(AWWebObj(body=json.dumps(body)), mock.Mock(), hooks=None)
    with mock.patch(
        "actingweb.permission_integration.client_trust_type_acceptable",
        side_effect=lambda config, name: name == "mcp_client",
    ):
        return handler._handle_authorize()


def test_an_unlisted_trust_type_is_refused_at_authorize() -> None:
    result = _authorize("admin")
    assert result.get("status_code") == 400
    assert "not offered" in json.dumps(result)


def test_a_listed_type_and_a_plain_login_pass_the_check() -> None:
    """The check passes: the route goes on to the next one, an invalid
    ``prompt`` here, and answers that 400 instead (verification
    2026-11-10: the test swallowed every exception past the check)."""
    for trust_type in ("mcp_client", None):
        result = _authorize(trust_type, prompt="not-a-prompt")
        text = json.dumps(result)
        assert "not offered" not in text, trust_type
        assert "Invalid prompt" in text, trust_type


def _decide(
    hook: Callable[..., Any] | None, trust_type: str = "mcp_client"
) -> str | None:
    """The sign-in callback's decision for a state that names
    ``trust_type``, with ``hook`` as the application's only
    ``oauth2_trust_requested`` hook."""
    from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler
    from actingweb.interface.hooks import HookRegistry, LifecycleEvent

    registry = HookRegistry()
    if hook is not None:
        registry.register_lifecycle_hook(
            LifecycleEvent.OAUTH2_TRUST_REQUESTED.value, hook
        )
    handler = OAuth2CallbackHandler.__new__(OAuth2CallbackHandler)
    handler.config = mock.Mock()
    handler.hooks = registry
    with mock.patch(
        "actingweb.permission_integration.client_trust_type_acceptable",
        side_effect=lambda config, name: name in ("mcp_client", "viewer"),
    ):
        return handler._decided_client_trust_type(
            mock.Mock(), trust_type, email="u@example.test", provider="google"
        )


def test_a_sign_in_naming_a_trust_type_asks_the_decision_hook() -> None:
    """Release validation 2026-11-18 (owner: ask the hook): a sign-in whose
    state names ``trust_type`` created the trust without the application's
    ``oauth2_trust_requested`` hooks."""
    seen: list[dict] = []

    def decline(actor: object, **info: object) -> bool:
        seen.append(info)
        return False

    assert _decide(decline) is None
    assert len(seen) == 1
    assert seen[0]["trust_type"] == "mcp_client"
    assert seen[0]["email"] == "u@example.test"
    assert seen[0]["confirmed"] is False


def test_another_type_declines_and_no_hook_keeps_the_request() -> None:
    """No page shows the user another level on this path, so a hook that
    names another type declines, as at the OAuth2 server's Approve (owner,
    2026-11-18)."""
    assert _decide(lambda actor, **info: "viewer") is None
    assert _decide(lambda actor, **info: "admin") is None  # not on the list
    assert _decide(lambda actor, **info: None) == "mcp_client"
    assert _decide(lambda actor, **info: "mcp_client") == "mcp_client"
    assert _decide(None) == "mcp_client"
    assert _decide(None, "admin") is None
