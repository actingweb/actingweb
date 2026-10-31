"""Fifth verification, Y1-Y5, Y7, Y10, Y12: peer-supplied trust fields
never reach a script or a link that acts; ambient credentials only; the
integrations refuse the session cookie for a cross-site state change."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest import mock

import jinja2
import pytest

from actingweb import cross_site
from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.handlers import callbacks, properties, root, trust
from actingweb.trust import is_valid_peer_baseuri, is_valid_peer_id

ROOT = "https://demo.actingweb.io/"
EVIL_ID = "x');fetch('/v1?_method=DELETE');('"
REPO = Path(__file__).resolve().parent.parent


def _config() -> Config:
    config = Config(database="dynamodb")
    config.root = ROOT
    return config


# --- Y1: no template value inside an inline script --------------------------


@pytest.mark.parametrize(
    "directory,template,values",
    [
        (
            "actingweb/templates",
            "aw-actor-www-trust.html",
            {
                "trusts": [
                    {"peerid": EVIL_ID, "approveuri": "/t", "relationship": "friend"}
                ]
            },
        ),
        (
            "examples/demo/templates",
            "aw-actor-www-trust.html",
            {
                "trusts": [
                    {"peerid": EVIL_ID, "approveuri": "/t", "baseuri": "javascript:x"}
                ]
            },
        ),
        (
            "actingweb/templates",
            "aw-actor-www-properties.html",
            {"properties": {EVIL_ID: "v"}, "actor_www": "/a1/www"},
        ),
        (
            "actingweb/templates",
            "aw-actor-www-property.html",
            {"property": EVIL_ID, "qual": "a", "value": "v", "actor_www": "/a1/www"},
        ),
    ],
)
def test_inline_handlers_carry_no_template_values(
    directory: str, template: str, values: dict[str, Any]
) -> None:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(REPO / directory), autoescape=True
    )
    html = env.get_template(template).render(id="a1", url="/a1/www", **values)
    for line in html.splitlines():
        if "onsubmit=" in line or "onclick=" in line:
            assert "fetch(" not in line, line
    assert 'onsubmit="return confirm(this.dataset.confirm);"' in html
    # The value sits in a data attribute, escaped once.
    assert "x&#39;);fetch(" in html
    # A peer base URI that is not a plain http(s) URL is never a link.
    assert 'href="javascript:' not in html


# --- Y2, Y3: peer ids and base URIs are checked where a peer supplies them --


def test_incoming_trust_request_refuses_a_bad_id_or_baseuri() -> None:
    for body in (
        {"id": "../../../victim", "baseuri": "https://peer.example/p1"},
        {"id": EVIL_ID, "baseuri": "https://peer.example/p1"},
        {"id": "p1", "baseuri": "https://demo.actingweb.io/v1?_method=DELETE"},
        {"id": "p1", "baseuri": "javascript:alert(1)"},
    ):
        webobj = AWWebObj(body=json.dumps(body))
        handler = trust.TrustRelationshipHandler(webobj, _config())
        auth = mock.Mock(actor=mock.Mock(id="a1"))
        with (
            mock.patch.object(handler, "authenticate_actor", return_value=auth),
            mock.patch("actingweb.actor.Actor.create_verified_trust") as created,
        ):
            handler.post("a1", "friend")
        assert webobj.response.status_code == 400, body
        created.assert_not_called()


def test_create_verified_trust_refuses_a_bad_id() -> None:
    from actingweb.actor import Actor

    actor = Actor.__new__(Actor)
    actor.id = "a1"
    actor.config = _config()
    assert (
        actor.create_verified_trust(
            baseuri="https://peer.example/p1",
            peerid="../x",
            approved=False,
            secret="s",
            verification_token=None,
            trust_type="",
            peer_approved=None,
            relationship="friend",
            desc="",
        )
        is False
    )


def test_peer_input_validators() -> None:
    assert is_valid_peer_id("0f3a9c")
    assert is_valid_peer_id("oauth2:user_at_x_dot_com:client_1")
    for bad in ("", "../x", "a/b", "a?b", "a#b", "a%2fb", "a b", "a'b", "é", "x" * 256):
        assert not is_valid_peer_id(bad), bad
    assert is_valid_peer_baseuri("https://peer.example/p1")
    assert is_valid_peer_baseuri("http://localhost:5055/p1")
    for bad in (
        "javascript:alert(1)",
        "https://h/a?_method=DELETE",
        "https://h/a#f",
        "https://u:p@h/a",
        "//h/a",
        "https://h/a b",
        'https://h/a"b',
    ):
        assert not is_valid_peer_baseuri(bad), bad


def test_trust_links_quote_a_stored_peer_id() -> None:
    from actingweb.handlers.www import WwwHandler

    handler = WwwHandler(AWWebObj(), _config())
    assert handler._trust_uri("a1", "friend", "../../x") == (
        "https://demo.actingweb.io/a1/trust/friend/..%2F..%2Fx"
    )
    assert handler._trust_uri("a1", "friend", "..") == ""
    assert handler._trust_uri("a1", "friend", "a?_method=DELETE#").endswith(
        "/friend/a%3F_method%3DDELETE%23"
    )


# --- Y4, Y5: ambient credentials only ---------------------------------------


def _override(headers: dict[str, str], cookies: dict[str, str] | None = None) -> Any:
    webobj = AWWebObj(
        params={"_method": "DELETE"}, headers=headers, cookies=cookies or {}
    )
    handler = properties.PropertiesHandler(webobj, _config())
    with mock.patch.object(handler, "delete") as dispatched:
        handler.get("a1", "notes")
    return dispatched


def test_a_cross_origin_spa_with_its_own_bearer_token_is_dispatched() -> None:
    dispatched = _override(
        {"Sec-Fetch-Site": "cross-site", "Authorization": "Bearer spa-token"}
    )
    dispatched.assert_called_once()


def test_cached_basic_auth_cross_site_is_refused() -> None:
    dispatched = _override(
        {"Sec-Fetch-Site": "cross-site", "Authorization": "Basic eDp5"}
    )
    dispatched.assert_not_called()


def test_the_cookie_counts_whatever_the_authorization_header() -> None:
    dispatched = _override(
        {"Authorization": "Basic eDp5"}, cookies={"oauth_token": "tok"}
    )
    dispatched.assert_not_called()


# --- Y12: the integrations and the session cookie ---------------------------


@pytest.mark.parametrize(
    "method,headers,expected",
    [
        ("GET", {"Sec-Fetch-Site": "cross-site"}, True),
        ("POST", {"Sec-Fetch-Site": "same-origin"}, True),
        ("POST", {}, True),
        ("POST", {"Sec-Fetch-Site": "same-site"}, False),
        ("PUT", {"Origin": "https://sibling.actingweb.io"}, False),
        ("DELETE", {"Origin": "null"}, False),
        ("POST", {"Origin": "https://demo.actingweb.io"}, True),
    ],
)
def test_may_use_session_cookie(
    method: str, headers: dict[str, str], expected: bool
) -> None:
    lowered = {k.lower(): v for k, v in headers.items()}
    assert (
        cross_site.may_use_session_cookie(
            method, lambda n: lowered.get(n.lower()), ROOT
        )
        is expected
    )


def _flask_integration() -> Any:
    from actingweb.interface.integrations.flask_integration import FlaskIntegration

    aw_app = mock.Mock()
    aw_app.hooks = {}
    aw_app.get_config.return_value = _config()
    with mock.patch.object(FlaskIntegration, "setup_routes"):
        return FlaskIntegration(aw_app, mock.Mock())


@pytest.mark.parametrize(
    "fetch_site,mapped", [("same-site", False), ("same-origin", True)]
)
def test_flask_maps_the_cookie_only_for_a_same_origin_state_change(
    fetch_site: str, mapped: bool
) -> None:
    from flask import Flask

    integration = _flask_integration()
    app = Flask("t")
    with app.test_request_context(
        "/a1/properties",
        method="POST",
        headers={"Cookie": "oauth_token=tok", "Sec-Fetch-Site": fetch_site},
    ):
        headers = integration._normalize_request()["headers"]
    assert ("Authorization" in headers) is mapped


@pytest.mark.parametrize(
    "fetch_site,mapped", [(b"same-site", False), (b"same-origin", True)]
)
def test_fastapi_maps_the_cookie_only_for_a_same_origin_state_change(
    fetch_site: bytes, mapped: bool
) -> None:
    from starlette.requests import Request

    from actingweb.interface.integrations.fastapi_integration import (
        FastAPIIntegration,
    )

    aw_app = mock.Mock()
    aw_app.hooks = {}
    aw_app.get_config.return_value = _config()
    with mock.patch.object(FastAPIIntegration, "setup_routes"):
        integration = FastAPIIntegration(aw_app, mock.Mock())

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/a1/properties",
            "query_string": b"",
            "headers": [
                (b"cookie", b"oauth_token=tok"),
                (b"sec-fetch-site", fetch_site),
            ],
        },
        receive,
    )
    headers = asyncio.run(integration._normalize_request(request))["headers"]
    assert ("Authorization" in headers) is mapped


# --- Y10: callbacks dispatch once -------------------------------------------


def test_callbacks_override_does_not_also_run_the_get() -> None:
    webobj = AWWebObj(
        params={"_method": "POST"}, headers={"Sec-Fetch-Site": "same-origin"}
    )
    handler = callbacks.CallbacksHandler(webobj, _config())
    with (
        mock.patch.object(handler, "post") as posted,
        mock.patch.object(handler, "_authenticate_dual_context") as authed,
    ):
        handler.get("a1", "cb")
    posted.assert_called_once()
    authed.assert_not_called()


def test_root_redirect_keeps_the_base_path() -> None:
    config = _config()
    config.root = "https://demo.actingweb.io/base/"
    assert config.actor_path("a1", "/www") == "/base/a1/www"
    assert _config().actor_path("a1") == "/a1"
    assert root.RootHandler  # imported for the handler map


# --- Sixth verification, Z1-Z12 ---------------------------------------------


def test_trust_put_refuses_a_bad_baseuri() -> None:
    """Z1: the peer may PUT its own row; the base URI must stay plain."""
    webobj = AWWebObj(body=json.dumps({"baseuri": "javascript:alert(1)"}))
    handler = trust.TrustPeerHandler(webobj, _config())
    auth = mock.Mock(actor=mock.Mock(id="a1"))
    auth.authorize.return_value = True
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=auth),
        mock.patch.object(handler, "_get_actor_interface") as interface,
    ):
        handler.put("a1", "friend", "p1")
    assert webobj.response.status_code == 400
    interface.return_value.trust.modify_and_notify.assert_not_called()


def test_root_browser_redirect_keeps_one_base_path() -> None:
    """Z2: the origin of config.root, then actor_path (which has the base)."""
    config = _config()
    config.root = "https://demo.actingweb.io/base/"
    config.ui = True
    webobj = AWWebObj(headers={"Accept": "text/html"})
    handler = root.RootHandler(webobj, config)
    auth = mock.Mock(success=True, actor=mock.Mock(id="a1"))
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=auth),
        mock.patch.object(handler, "_wants_html", return_value=True),
    ):
        handler.get("a1")
    assert webobj.response.status_code == 302
    assert webobj.response.redirect == "https://demo.actingweb.io/base/a1/www"


@pytest.mark.parametrize(
    "fetch_site,kept",
    [("cross-site", False), ("same-site", False), ("same-origin", True)],
)
def test_flask_drops_a_cached_basic_header_on_a_cross_site_post(
    fetch_site: str, kept: bool
) -> None:
    """Z3: a form on another site carries the browser's cached Basic header."""
    from flask import Flask

    integration = _flask_integration()
    app = Flask("t")
    with app.test_request_context(
        "/a1/properties",
        method="POST",
        headers={"Authorization": "Basic eDp5", "Sec-Fetch-Site": fetch_site},
    ):
        headers = integration._normalize_request()["headers"]
    assert ("Authorization" in headers) is kept


def test_flask_keeps_an_explicit_bearer_on_a_cross_site_post() -> None:
    from flask import Flask

    integration = _flask_integration()
    app = Flask("t")
    with app.test_request_context(
        "/a1/properties",
        method="POST",
        headers={"Authorization": "Bearer t", "Sec-Fetch-Site": "cross-site"},
    ):
        headers = integration._normalize_request()["headers"]
    assert headers["Authorization"] == "Bearer t"


def test_library_templates_encode_property_names_in_urls() -> None:
    """Z4: a name with "?" must not become a ?_method= link."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(REPO / "actingweb/templates"), autoescape=True
    )
    name = "email?_method=DELETE"
    listing = env.get_template("aw-actor-www-properties.html").render(
        properties={name: "v"}, actor_www="/a1/www", id="a1"
    )
    page = env.get_template("aw-actor-www-property.html").render(
        property=name, qual="a", value="v", actor_www="/a1/www", id="a1"
    )
    for html in (listing, page):
        assert "/properties/email?_method" not in html
        assert "/properties/email%3F_method%3DDELETE" in html


def test_dot_only_trust_ids_get_no_link() -> None:
    """Z5: "%2E" is a dot to the browser, so such a row has no action URL."""
    from actingweb.handlers.www import WwwHandler

    handler = WwwHandler(AWWebObj(), _config())
    assert handler._trust_uri("a1", "friend", "..") == ""
    assert handler._trust_uri("a1", "..", "p1") == ""


def test_reciprocal_trust_refuses_an_invalid_url() -> None:
    """Z6."""
    from actingweb.actor import Actor

    actor = Actor.__new__(Actor)
    actor.id = "a1"
    actor.config = _config()
    with mock.patch.object(Actor, "get_peer_info") as fetched:
        assert (
            actor.create_reciprocal_trust(
                url="https://peer.example/p1?x=1", secret="s", relationship="friend"
            )
            is False
        )
    fetched.assert_not_called()


def test_peer_id_refuses_a_trailing_newline() -> None:
    """Z9."""
    assert not is_valid_peer_id("abc\n")


def test_verification_page_continue_link_keeps_the_base_path() -> None:
    """Z12."""
    config = _config()
    config.root = "https://demo.actingweb.io/base/"
    integration = _flask_integration()
    integration.aw_app.get_config.return_value = config
    values = integration._with_verification_redirect(
        {"actor_id": "a1", "status": "success"}
    )
    assert values["redirect_url"] == "/base/a1/www"


# --- Seventh verification: the Basic drop is for actor routes only ----------


@pytest.mark.parametrize(
    "path,kept",
    [
        ("/oauth/token", True),
        # Only the token endpoint reads client_secret_basic: every other
        # path, under /oauth and /mcp too, drops a cross-site Basic header.
        ("/oauth/revoke", False),
        ("/oauth/register", False),
        ("/oauth/tokenx", False),
        ("/mcp", False),
        ("/a1/properties", False),
        ("/a1/trust", False),
    ],
)
def test_flask_keeps_a_client_basic_header_on_client_auth_endpoints(
    path: str, kept: bool
) -> None:
    """client_secret_basic from a browser-hosted client is cross-origin by
    design; every other route drops a cross-site Basic header."""
    from flask import Flask

    integration = _flask_integration()
    app = Flask("t")
    with app.test_request_context(
        path,
        method="POST",
        headers={"Authorization": "Basic eDp5", "Sec-Fetch-Site": "cross-site"},
    ):
        headers = integration._normalize_request()["headers"]
    assert ("Authorization" in headers) is kept


@pytest.mark.parametrize(
    "path,kept", [("/oauth/token", True), ("/a1/properties", False)]
)
def test_fastapi_drops_a_cross_site_basic_header_except_on_the_token_endpoint(
    path: str, kept: bool
) -> None:
    from starlette.requests import Request

    from actingweb.interface.integrations.fastapi_integration import (
        FastAPIIntegration,
    )

    aw_app = mock.Mock()
    aw_app.hooks = {}
    aw_app.get_config.return_value = _config()
    with mock.patch.object(FastAPIIntegration, "setup_routes"):
        integration = FastAPIIntegration(aw_app, mock.Mock())

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": [
                (b"authorization", b"Basic eDp5"),
                (b"sec-fetch-site", b"cross-site"),
            ],
        },
        receive,
    )
    headers = asyncio.run(integration._normalize_request(request))["headers"]
    assert ("Authorization" in headers) is kept


def test_may_use_basic_strips_the_base_path() -> None:
    def cross(name: str) -> str | None:
        return "cross-site" if name.lower() == "sec-fetch-site" else None

    root = "https://h.example/base/"
    assert cross_site.may_use_basic("POST", cross, "/base/oauth/token", root)
    assert not cross_site.may_use_basic("POST", cross, "/base/a1/properties", root)
    assert cross_site.may_use_basic("GET", cross, "/base/a1/properties", root)
