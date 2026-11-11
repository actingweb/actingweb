"""An MCP client's access level is the user's choice (3.16, plan Phase 3).

On the ``wire_oauth`` app (OAuth2 and MCP on, the stand-in provider), not
recordings: the browser binding, the confirmation and its refusals, the
re-typed row, a trust that cannot be written, the decision hook as the
server applies it, and the page headers.
"""

from __future__ import annotations

import base64
import hashlib
import re
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from . import _oauth_stub

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

REDIRECT = "https://client.example.test/cb"
VERIFIER = "binding-verifier-" + "v" * 40


def _challenge() -> str:
    digest = hashlib.sha256(VERIFIER.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


class Flow:
    """One client, one user (the email the stand-in provider signs in)."""

    def __init__(self, host: Any):
        self.host = host
        self.email = f"bind-{uuid.uuid4().hex[:8]}@example.test"
        _oauth_stub.STUB["email"] = self.email
        r = requests.post(
            f"{host.url}/oauth/register",
            json={"client_name": "Binding Client", "redirect_uris": [REDIRECT]},
        )
        assert r.status_code == 201, r.text
        self.client_id = r.json()["client_id"]
        self.client_secret = r.json()["client_secret"]

    def params(self) -> dict[str, str]:
        return {
            "client_id": self.client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "state": "st-1",
            "code_challenge": _challenge(),
            "code_challenge_method": "S256",
        }

    def form(self, browser: Any) -> str:
        """GET the form in ``browser``; its nonce."""
        r = browser.get(
            f"{self.host.url}/oauth/authorize",
            params=self.params(),
            headers={"Accept": "application/json"},
        )
        assert r.status_code == 200, r.text
        return str(r.json()["form_data"]["form_nonce"])

    def post(self, http: Any, trust_type: str, nonce: str = "") -> requests.Response:
        return http.post(
            f"{self.host.url}/oauth/authorize",
            data={
                **self.params(),
                "provider": "google",
                "trust_type": trust_type,
                "form_nonce": nonce,
            },
            allow_redirects=False,
        )

    def callback(self, browser: Any, state: str) -> requests.Response:
        return browser.get(
            f"{self.host.url}/oauth/callback",
            params={"code": _oauth_stub.PROVIDER_CODE, "state": state},
            allow_redirects=False,
        )

    def confirm(
        self, browser: Any, token: str, decision: str, *, origin: str | None = None
    ) -> requests.Response:
        return browser.post(
            f"{self.host.url}/oauth/authorize/confirm",
            data={"token": token, "decision": decision},
            headers={"Origin": origin or self.host.url},
            allow_redirects=False,
        )

    def code_of(self, r: requests.Response) -> str | None:
        location = r.headers.get("location", "")
        if not location.startswith(REDIRECT):
            return None
        return (parse_qs(urlparse(location).query).get("code") or [None])[0]

    def error_of(self, r: requests.Response) -> str | None:
        location = r.headers.get("location", "")
        return (parse_qs(urlparse(location).query).get("error") or [None])[0]

    def honest(self, trust_type: str = "mcp_client") -> requests.Response:
        """The whole flow in one browser: no confirmation."""
        browser = requests.Session()
        nonce = self.form(browser)
        r = self.post(browser, trust_type, nonce)
        assert r.status_code == 302, r.text
        return self.callback(browser, _state(r))

    def paused(self, trust_type: str = "mcp_client") -> tuple[Any, str]:
        """The client posts the form itself; the user's browser signs in and
        gets the confirmation page. The browser and the page's token."""
        r = self.post(requests, trust_type)
        assert r.status_code == 302, r.text
        browser = requests.Session()
        page = self.callback(browser, _state(r))
        assert page.status_code == 200, page.text
        token = re.search(r'name="token" value="([^"]+)"', page.text)
        assert token, page.text[:500]
        return browser, token.group(1)

    def user_rows(self) -> list[dict[str, Any]]:
        from actingweb.actor import Actor

        core = Actor(config=self.host.config)
        if not core.get_from_creator(self.email):
            return []
        return [
            r
            for r in core.get_trust_relationships() or []
            if str(r.get("peerid", "")).endswith(":" + self.client_id)
        ]

    def token(self, code: str) -> requests.Response:
        return requests.post(
            f"{self.host.url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code_verifier": VERIFIER,
            },
        )


def _state(r: requests.Response) -> str:
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0]


@pytest.fixture
def flow(wire_oauth) -> Flow:
    return Flow(wire_oauth)


@pytest.fixture
def listed(wire_oauth) -> Iterator[Any]:
    """Change wire_oauth's client list for one test, then restore it."""
    config = wire_oauth.config
    saved = dict(getattr(config, "_oauth2_trust_types", {}) or {})

    def set_list(allowed: list[str] | None, default: str | None = None) -> None:
        config._oauth2_trust_types = {"allowed": allowed, "default": default}

    yield set_list
    config._oauth2_trust_types = saved


def test_the_honest_flow_needs_no_confirmation(flow: Flow) -> None:
    r = flow.honest()
    code = flow.code_of(r)
    assert code, r.text
    rows = flow.user_rows()
    assert [row["relationship"] for row in rows] == ["mcp_client"]
    token = flow.token(code)
    assert token.status_code == 200
    assert token.json()["trust_type"] == "mcp_client"


def test_a_form_the_client_posted_waits_for_the_user(flow: Flow) -> None:
    browser, token = flow.paused()
    assert flow.user_rows() == []  # no trust before Approve
    r = flow.confirm(browser, token, "approve")
    code = flow.code_of(r)
    assert code, r.text
    assert [row["relationship"] for row in flow.user_rows()] == ["mcp_client"]
    # PKCE survives the pause: the code exchanges with the verifier.
    assert flow.token(code).status_code == 200


def test_decline_creates_nothing(flow: Flow) -> None:
    browser, token = flow.paused()
    r = flow.confirm(browser, token, "decline")
    assert flow.error_of(r) == "access_denied"
    assert "state=st-1" in r.headers["location"]
    assert flow.user_rows() == []


def test_another_browsers_nonce_asks_for_confirmation(flow: Flow) -> None:
    form_browser = requests.Session()
    nonce = flow.form(form_browser)
    r = flow.post(form_browser, "mcp_client", nonce)
    page = flow.callback(requests.Session(), _state(r))  # signs in elsewhere
    assert page.status_code == 200 and "Confirm access" in page.text


def test_a_replayed_state_asks_for_confirmation(flow: Flow) -> None:
    browser = requests.Session()
    nonce = flow.form(browser)
    r = flow.post(browser, "mcp_client", nonce)
    state = _state(r)
    assert flow.code_of(flow.callback(browser, state))
    again = flow.callback(browser, state)  # the nonce cookie was cleared
    assert again.status_code == 200 and "Confirm access" in again.text


def test_an_unlisted_type_is_declined_at_the_post_and_at_the_callback(
    flow: Flow, listed: Any
) -> None:
    listed(["mcp_client", "friend"])
    browser = requests.Session()
    nonce = flow.form(browser)
    r = flow.post(browser, "friend", nonce)
    state = _state(r)
    listed(["mcp_client"])
    refused = flow.post(browser, "friend", nonce)
    assert refused.status_code == 400 and "access_denied" in refused.text
    # A state minted while friend was listed is declined at the callback.
    assert flow.error_of(flow.callback(browser, state)) == "access_denied"
    assert flow.user_rows() == []


def test_admin_is_not_offered_without_a_list(flow: Flow, listed: Any) -> None:
    listed(None)
    r = flow.post(requests, "admin")
    assert r.status_code == 400 and "access_denied" in r.text


@pytest.mark.parametrize(
    "case", ["cross_site", "no_page_cookie", "reused", "store_fault", "bad_decision"]
)
def test_the_confirmation_refuses(flow: Flow, case: str) -> None:
    browser, token = flow.paused()
    if case == "cross_site":
        r = flow.confirm(browser, token, "approve", origin="https://evil.example")
        assert r.status_code == 403
    elif case == "no_page_cookie":
        r = flow.confirm(requests.Session(), token, "approve")
        assert r.status_code == 400
    elif case == "reused":
        assert flow.code_of(flow.confirm(browser, token, "approve"))
        browser.cookies.set("aw_authz_confirm", token)
        r = flow.confirm(browser, token, "approve")
        assert r.status_code == 400
    elif case == "store_fault":
        from actingweb.oauth2_server.token_manager import (
            ActingWebTokenManager,
            TokenStoreUnavailable,
        )

        with mock.patch.object(
            ActingWebTokenManager,
            "consume_pending_authorization",
            side_effect=TokenStoreUnavailable("fault"),
        ):
            r = flow.confirm(browser, token, "approve")
        assert r.status_code == 503
    else:
        r = flow.confirm(browser, token, "maybe")
        assert r.status_code == 400
    assert flow.code_of(r) is None


def test_a_store_fault_leaves_the_retry(flow: Flow) -> None:
    """Verification 2026-11-10: the confirm cookie was cleared before the
    store was read, so the user's retry after a 503 got 400."""
    from actingweb.oauth2_server.token_manager import (
        ActingWebTokenManager,
        TokenStoreUnavailable,
    )

    browser, token = flow.paused()
    with mock.patch.object(
        ActingWebTokenManager,
        "consume_pending_authorization",
        side_effect=TokenStoreUnavailable("fault"),
    ):
        assert flow.confirm(browser, token, "approve").status_code == 503
    assert flow.code_of(flow.confirm(browser, token, "approve"))


def test_an_expired_confirmation_is_refused(flow: Flow) -> None:
    import time as time_module

    browser, token = flow.paused()
    later = time_module.time() + 601
    with mock.patch(
        "actingweb.oauth2_server.token_manager.time.time", return_value=later
    ):
        r = flow.confirm(browser, token, "approve")
    assert r.status_code == 400
    assert flow.user_rows() == []


def test_a_deleted_actor_gets_nothing_on_approve(flow: Flow) -> None:
    from actingweb.actor import Actor

    browser, token = flow.paused()
    core = Actor(config=flow.host.config)
    assert core.get_from_creator(flow.email)
    core.delete()
    r = flow.confirm(browser, token, "approve")
    assert flow.error_of(r) == "access_denied"


def test_no_code_without_a_trust(flow: Flow) -> None:
    with mock.patch(
        "actingweb.oauth2.create_oauth2_trust_relationship", return_value=False
    ):
        r = flow.honest()
    assert flow.code_of(r) is None
    assert r.status_code == 400 and "server_error" in r.text


def test_a_re_authorisation_follows_the_approval_both_ways(flow: Flow) -> None:
    assert flow.code_of(flow.honest("admin"))  # listed on wire_oauth
    assert [row["relationship"] for row in flow.user_rows()] == ["admin"]
    assert flow.code_of(flow.honest("mcp_client"))
    assert [row["relationship"] for row in flow.user_rows()] == ["mcp_client"]
    assert flow.code_of(flow.honest("viewer"))
    assert [row["relationship"] for row in flow.user_rows()] == ["viewer"]


def test_a_retyped_row_loses_its_override(flow: Flow) -> None:
    from actingweb.actor import Actor
    from actingweb.trust_permissions import (
        create_permission_override,
        get_trust_permission_store,
    )

    assert flow.code_of(flow.honest("mcp_client"))
    row = flow.user_rows()[0]
    core = Actor(config=flow.host.config)
    assert core.get_from_creator(flow.email)
    store = get_trust_permission_store(flow.host.config)
    store.store_permissions(
        create_permission_override(
            str(core.id),
            row["peerid"],
            "mcp_client",
            {"properties": {"patterns": ["*"], "operations": ["read"]}},
        )
    )
    assert store.get_permissions(str(core.id), row["peerid"])
    assert flow.code_of(flow.honest("viewer"))
    assert not store.get_permissions(str(core.id), row["peerid"])


def test_the_decision_hook_declines(flow: Flow) -> None:
    from actingweb.interface.hooks import HookRegistry

    with mock.patch.object(HookRegistry, "decide_oauth2_trust", return_value=None):
        r = flow.honest("mcp_client")
    assert flow.error_of(r) == "access_denied"
    assert flow.user_rows() == []


def test_a_level_the_hook_changed_is_shown_before_it_is_granted(flow: Flow) -> None:
    """The hook lowers mcp_client to viewer: the user sees viewer on the
    confirmation page, and Approve grants exactly that."""
    from actingweb.interface.hooks import HookRegistry

    with mock.patch.object(HookRegistry, "decide_oauth2_trust", return_value="viewer"):
        browser = requests.Session()
        nonce = flow.form(browser)
        page = flow.callback(browser, _state(flow.post(browser, "mcp_client", nonce)))
        assert page.status_code == 200 and "Viewer" in page.text
        assert flow.user_rows() == []
        token = re.search(r'name="token" value="([^"]+)"', page.text)
        assert token
        r = flow.confirm(browser, token.group(1), "approve")
    code = flow.code_of(r)
    assert code
    assert [row["relationship"] for row in flow.user_rows()] == ["viewer"]
    assert flow.token(code).json()["trust_type"] == "viewer"


def test_approve_grants_only_the_level_shown(flow: Flow) -> None:
    """A hook answering differently at Approve declines: no level the user
    did not see."""
    from actingweb.interface.hooks import HookRegistry

    browser, token = flow.paused("mcp_client")
    with mock.patch.object(HookRegistry, "decide_oauth2_trust", return_value="viewer"):
        r = flow.confirm(browser, token, "approve")
    assert flow.error_of(r) == "access_denied"
    assert flow.user_rows() == []


@pytest.mark.parametrize("change", ["disabled", "generation", "narrowed"])
def test_a_client_changed_before_approve_gets_nothing(flow: Flow, change: str) -> None:
    """Verification 2026-11-10: the confirm-time re-checks of the client."""
    from actingweb.oauth2_server.client_registry import MCPClientRegistry

    browser, token = flow.paused("mcp_client")
    real = MCPClientRegistry.validate_client

    def changed(self: Any, client_id: str, *a: Any, **kw: Any) -> Any:
        data = real(self, client_id, *a, **kw)
        if change == "disabled" or not data:
            return None
        data = dict(data)
        if change == "generation":
            data["session_generation"] = "something-else"
        else:
            data["allowed_trust_types"] = ["viewer"]
        return data

    with mock.patch.object(MCPClientRegistry, "validate_client", changed):
        r = flow.confirm(browser, token, "approve")
    assert flow.error_of(r) == "access_denied"
    assert flow.code_of(r) is None
    assert flow.user_rows() == []


def test_a_callers_own_decision_cannot_grant_an_unoffered_type(flow: Flow) -> None:
    """Verification 2026-11-10: a caller passing its own ``decide_trust`` to
    the public methods gets the acceptability re-check too."""
    from actingweb.oauth2_server.oauth2_server import get_actingweb_oauth2_server

    server = get_actingweb_oauth2_server(flow.host.config)
    record = {"trust_type": "mcp_client", "client_id": "c"}
    assert (
        server._decided_type(mock.Mock(), record, lambda *a, **k: "no_such", True)
        is None
    )
    assert (
        server._decided_type(mock.Mock(), record, lambda *a, **k: "viewer", True)
        == "viewer"
    )


def test_a_retype_whose_override_cannot_be_removed_still_issues_a_code(
    flow: Flow,
) -> None:
    """Owner decision 2026-11-11 (re-run 3): an override for the old type is
    not applied once the row is re-typed, so its removal is cleanup; a
    removal that fails does not refuse the authorisation (it refused, and
    the rollback that went with it raced concurrent authorisations). A
    smoke test over HTTP; the unit tests in ``test_client_trust_update.py``
    hold the cleanup and the evaluator rule."""
    from actingweb.trust_permissions import TrustPermissions, TrustPermissionStore

    assert flow.code_of(flow.honest("mcp_client"))
    old_override = TrustPermissions(
        actor_id="a", peer_id="p", trust_type="mcp_client", properties={}
    )
    with (
        mock.patch.object(
            TrustPermissionStore, "get_permissions_uncached", return_value=old_override
        ),
        mock.patch.object(
            TrustPermissionStore, "delete_permissions", return_value=False
        ),
    ):
        r = flow.honest("viewer")
    assert flow.code_of(r)


def test_the_pages_are_not_framed_or_cached(flow: Flow) -> None:
    page = requests.get(f"{flow.host.url}/oauth/authorize", params=flow.params())
    for response in (
        page,
        flow.callback(requests.Session(), _state(flow.post(requests, "mcp_client"))),
    ):
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["Referrer-Policy"] == "same-origin"


def test_the_helper_for_an_own_sign_in_route(flow: Flow, listed: Any) -> None:
    """``complete_client_authorization``: the list, the hook, the trust and
    the code in one call, for a route that signs the user in itself."""
    from actingweb.actor import Actor
    from actingweb.oauth2_server.oauth2_server import get_actingweb_oauth2_server

    r = requests.post(f"{flow.host.url}/", json={"creator": flow.email})
    assert r.status_code == 201
    core = Actor(config=flow.host.config)
    core.get(actor_id=r.json()["id"])
    server = get_actingweb_oauth2_server(flow.host.config)
    listed(["mcp_client", "viewer"])
    denied = server.complete_client_authorization(
        core, flow.client_id, REDIRECT, "admin"
    )
    assert "error=access_denied" in denied["url"]
    hooked = server.complete_client_authorization(
        core, flow.client_id, REDIRECT, "viewer", decide_trust=lambda *a, **k: None
    )
    assert "error=access_denied" in hooked["url"]
    done = server.complete_client_authorization(
        core, flow.client_id, REDIRECT, "viewer", state="s9"
    )
    assert "code=" in done["url"] and "state=s9" in done["url"]


def test_a_form_posted_without_its_nonce_is_named_once(
    flow: Flow, caplog: pytest.LogCaptureFixture
) -> None:
    """Verification 2026-11-10 (plan: one warning per process): a browser
    that was shown the form posts it without ``form_nonce``, as a custom
    template without the hidden input would."""
    import logging

    from actingweb.handlers import oauth2_endpoints

    oauth2_endpoints._form_without_nonce_warned = False
    with caplog.at_level(logging.WARNING, logger="actingweb.handlers.oauth2_endpoints"):
        for _ in range(2):
            browser = requests.Session()
            flow.form(browser)  # sets the nonce cookie
            flow.post(browser, "mcp_client")  # no form_nonce
    named = [r for r in caplog.records if "without form_nonce" in r.getMessage()]
    assert len(named) == 1


def test_a_refusal_is_a_page_for_a_browser_and_json_for_a_client(flow: Flow) -> None:
    """Browser walk 2026-11-10 (F-003): a person who answered a used page saw
    raw JSON. A browser gets the confirmation template's refusal, with the
    status kept; an API caller keeps the JSON."""
    browser, token = flow.paused()
    assert flow.code_of(flow.confirm(browser, token, "approve"))
    page = browser.post(
        f"{flow.host.url}/oauth/authorize/confirm",
        data={"token": token, "decision": "approve"},
        headers={"Origin": flow.host.url, "Accept": "text/html"},
        allow_redirects=False,
    )
    assert page.status_code == 400
    assert "cannot be used" in page.text and "<form" not in page.text
    api = browser.post(
        f"{flow.host.url}/oauth/authorize/confirm",
        data={"token": token, "decision": "approve"},
        headers={"Origin": flow.host.url, "Accept": "application/json"},
        allow_redirects=False,
    )
    assert api.status_code == 400
    assert api.json()["error"] == "invalid_request"
