"""A confirmation the server cannot complete answers as the other refusals
do (3.16, verification re-run 1 of the grant-enforcement plan, Issue G): a
page for a person, JSON for a client, with its status. An expired or spent
pending record reached the browser as raw JSON."""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth2_endpoints import (
    CONFIRM_COOKIE,
    CONFIRM_TEMPLATE,
    OAuth2EndpointsHandler,
)
from tests._adoption_helpers import make_config


def _handler(accept: str, answer: dict[str, Any]) -> OAuth2EndpointsHandler:
    config = make_config()
    server = mock.Mock()
    server.handle_confirmation.return_value = answer
    with mock.patch(
        "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
        return_value=server,
    ):
        probe = OAuth2EndpointsHandler(AWWebObj(), config, hooks=None)
        cookie = probe._cookie_name(CONFIRM_COOKIE)
        webobj = AWWebObj(
            url="https://test.example.com/oauth/authorize/confirm",
            body="token=tok&decision=approve",
            headers={"Accept": accept} if accept else {},
            cookies={cookie: "tok"},
        )
        handler = OAuth2EndpointsHandler(webobj, config, hooks=None)
    return handler


@pytest.mark.parametrize(
    ("error", "status"),
    [
        ("invalid_request", 400),
        ("temporarily_unavailable", 503),
        # Re-run 2 (Issue 10): a server failure is not the client's 400.
        ("server_error", 500),
    ],
)
def test_an_error_completing_it_is_a_page_for_a_browser(
    error: str, status: int
) -> None:
    handler = _handler(
        "text/html", {"error": error, "error_description": "the request expired"}
    )
    with mock.patch("actingweb.cross_site.cross_site", return_value=False):
        body = handler._handle_confirmation()
    assert body == {}
    assert handler.response.status_code == status
    assert handler.response.template_name == CONFIRM_TEMPLATE
    assert "the request expired" in handler.response.template_values["error"]
    assert "confirm_token" not in handler.response.template_values


def test_an_error_completing_it_is_json_for_a_client() -> None:
    handler = _handler(
        "application/json",
        {"error": "invalid_request", "error_description": "the request expired"},
    )
    with mock.patch("actingweb.cross_site.cross_site", return_value=False):
        body = handler._handle_confirmation()
    assert handler.response.status_code == 400
    assert body["error"] == "invalid_request"


def test_a_redirect_still_redirects() -> None:
    handler = _handler(
        "text/html", {"action": "redirect", "url": "https://client.example/cb?code=c"}
    )
    with mock.patch("actingweb.cross_site.cross_site", return_value=False):
        body = handler._handle_confirmation()
    assert body["status"] == "redirect"
    assert handler.response.status_code == 302
