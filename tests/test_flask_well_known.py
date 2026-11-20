"""AC-32: ``/.well-known/openid-configuration`` serves the authorisation
server document, on both integrations. Some clients look only there."""

from __future__ import annotations

from typing import Any

import pytest

from tests.test_oauth2_logout_mcp_tokens import _fastapi_client, _flask_client


def _json(resp: Any) -> Any:
    return resp.get_json() if hasattr(resp, "get_json") else resp.json()


@pytest.mark.parametrize("make", [_flask_client, _fastapi_client])
def test_openid_configuration(make: Any) -> None:
    client = make()
    server = client.get("/.well-known/oauth-authorization-server")
    openid = client.get("/.well-known/openid-configuration")
    assert openid.status_code == 200
    assert _json(openid) == _json(server)
