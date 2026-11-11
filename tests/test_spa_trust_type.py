"""The SPA authorize route applies the client list to ``trust_type``
(3.16, plan Phase 3): the field is the level for an MCP client."""

from __future__ import annotations

import json
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
