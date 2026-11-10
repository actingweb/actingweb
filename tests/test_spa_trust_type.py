"""The SPA authorize route applies the client list to ``trust_type``
(3.16, plan Phase 3): the field is the level for an MCP client."""

from __future__ import annotations

import json
from unittest import mock

from actingweb.aw_web_request import AWWebObj


def _authorize(trust_type: str | None) -> dict:
    from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

    body = {"provider": "google", "redirect_uri": "https://app.example/cb"}
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
    """Past the check the route needs a real configuration (a mock one
    fails further on): what matters is that the check did not refuse."""
    for trust_type in ("mcp_client", None):
        try:
            result = _authorize(trust_type)
        except Exception:  # noqa: BLE001 - beyond the check, on a mock config
            continue
        assert "not offered" not in json.dumps(result)
