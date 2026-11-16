"""The web UI's trust pages (3.16): the list says what both sides have done,
the new-trust form is linked from the dashboard and the list, and a submit
that fails returns to the form with a fixed message.

In process, on both integrations, with the library's own templates and the
real store. Each test has its own actor and trust rows.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any
from unittest import mock

import pytest
from markupsafe import escape as _escape

from actingweb.handlers.www import TRUST_FORM_MESSAGES, TRUST_LIST_NOTICES
from actingweb.interface import ActingWebApp
from actingweb.interface.trust_manager import TrustManager
from actingweb.trust import Trust

ORIGIN = "https://test.example.com"


def _shown(message: str) -> str:
    """A message as the page carries it (the templates escape)."""
    return str(_escape(message))


class _Site:
    """One application on one integration, and an actor signed in to it."""

    def __init__(self, framework: str) -> None:
        self.aw = (
            ActingWebApp(
                aw_type="urn:actingweb:test:www",
                database="dynamodb",
                fqdn="test.example.com",
                proto="https://",
            )
            .with_web_ui(enable=True)
            .with_devtest(enable=True)
            .with_unique_creator(False)
        )
        self.framework = framework
        if framework == "flask":
            from flask import Flask

            app = Flask(__name__)
            self.aw.integrate_flask(app)
            self._client: Any = app.test_client()
        else:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            fastapi_app = FastAPI()
            self.aw.integrate_fastapi(fastapi_app)
            self._client = TestClient(
                fastapi_app, base_url=ORIGIN, follow_redirects=False
            )
        self.config = self.aw.get_config()
        creator = f"{uuid.uuid4().hex[:12]}@example.com"
        created = self._send("post", "/", json={"creator": creator})
        assert created[0] == 201, created
        body = created[3]
        self.id, passphrase = body["id"], body["passphrase"]
        token = base64.b64encode(f"{creator}:{passphrase}".encode()).decode()
        self.auth = {"Authorization": f"Basic {token}", "Origin": ORIGIN}
        self.www = f"/{self.id}/www"

    def _send(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any, str, Any]:
        if self.framework == "flask":
            kwargs.setdefault("base_url", ORIGIN)
        response = getattr(self._client, method)(path, **kwargs)
        if self.framework == "flask":
            text = response.get_data(as_text=True)
            data = response.get_json(silent=True)
        else:
            text = response.text
            try:
                data = response.json()
            except ValueError:
                data = None
        return response.status_code, response.headers, text, data

    def get(self, path: str) -> tuple[int, Any, str]:
        status, headers, text, _ = self._send("get", path, headers=self.auth)
        return status, headers, text

    def submit(self, **form: str) -> tuple[int, str]:
        """POST the new-trust form; the status and the ``Location`` path."""
        status, headers, _, _ = self._send(
            "post", f"{self.www}/trust/new", data=form, headers=self.auth
        )
        location = headers.get("Location") or headers.get("location") or ""
        return status, location.replace(ORIGIN, "")

    def trust(
        self, peer: str, *, approved: bool, peer_approved: bool, verified: bool
    ) -> str:
        baseuri = f"https://{peer}.example.test/{peer}"
        assert Trust(actor_id=self.id, peerid=peer, config=self.config).create(
            baseuri=baseuri,
            peer_type="urn:test",
            relationship="friend",
            secret=uuid.uuid4().hex,
            desc="",
            approved=approved,
            peer_approved=peer_approved,
            verified=verified,
        )
        return baseuri


@pytest.fixture(params=["flask", "fastapi"])
def site(request: pytest.FixtureRequest) -> _Site:
    return _Site(request.param)


VALID = {"peer_url": "https://peer.example.test/p1", "trust_type": "friend"}


def test_the_trust_list_shows_both_sides(site: _Site) -> None:
    rows = {
        "Active": {"approved": True, "peer_approved": True, "verified": True},
        "Waiting for peer": {
            "approved": True,
            "peer_approved": False,
            "verified": True,
        },
        "Awaiting your approval": {
            "approved": False,
            "peer_approved": True,
            "verified": True,
        },
        "Awaiting both": {
            "approved": False,
            "peer_approved": False,
            "verified": True,
        },
        "Unverified": {
            "approved": False,
            "peer_approved": True,
            "verified": False,
        },
    }
    for index, flags in enumerate(rows.values()):
        site.trust(f"peer{index}", **flags)
    status, _, page = site.get(f"{site.www}/trust")
    assert status == 200
    for index, label in enumerate(rows):
        row = page[page.index(f"<code>peer{index}</code>") :]
        row = row[: row.index("</tr>")]
        assert f">{label}<" in row, (label, row)


def test_the_new_trust_form_is_linked(site: _Site) -> None:
    link = f'href="{ORIGIN}{site.www}/trust/new"'
    for path in (site.www, f"{site.www}/trust"):
        status, _, page = site.get(path)
        assert status == 200
        assert link in page or f'href="{site.www}/trust/new"' in page, path


@pytest.mark.parametrize(
    "code", ["peer_url_required", "relationship_too_long", "trust_type_required"]
)
def test_a_failed_new_trust_returns_to_the_form(site: _Site, code: str) -> None:
    form = dict(VALID)
    if code == "peer_url_required":
        form["peer_url"] = ""
    elif code == "relationship_too_long":
        form["relationship"] = "x" * 101
    else:
        form["trust_type"] = ""
    status, location = site.submit(**form)
    assert status == 302
    assert location == f"{site.www}/trust/new?error={code}"
    status, _, page = site.get(location)
    assert status == 200
    assert _shown(TRUST_FORM_MESSAGES[code]) in page


def test_a_peer_side_failure_has_one_message(site: _Site) -> None:
    """Unreachable, not an actor, refused: one answer, so the form cannot be
    used to tell hosts apart."""
    with mock.patch.object(TrustManager, "create_relationship", return_value=None):
        status, location = site.submit(**VALID)
    assert status == 302
    assert location == f"{site.www}/trust/new?error=create_failed"
    assert _shown(TRUST_FORM_MESSAGES["create_failed"]) in site.get(location)[2]


def test_an_unexpected_error_shows_nothing_of_itself(site: _Site) -> None:
    with mock.patch.object(
        TrustManager, "create_relationship", side_effect=RuntimeError("db-host-17")
    ):
        status, location = site.submit(**VALID)
    assert status == 302
    assert location == f"{site.www}/trust/new?error=server_error"
    page = site.get(location)[2]
    assert _shown(TRUST_FORM_MESSAGES["server_error"]) in page
    assert "db-host-17" not in page


def test_an_existing_trust_returns_a_notice(site: _Site) -> None:
    baseuri = site.trust("peer1", approved=True, peer_approved=True, verified=True)
    with mock.patch.object(TrustManager, "create_relationship") as create:
        status, location = site.submit(peer_url=baseuri + "/", trust_type="friend")
    create.assert_not_called()
    assert status == 302
    assert location == f"{site.www}/trust?notice=trust_exists"
    assert _shown(TRUST_LIST_NOTICES["trust_exists"]) in site.get(location)[2]


def test_nothing_from_the_query_string_is_rendered(site: _Site) -> None:
    """A link from another site cannot prefill the form or put text on the
    page: a known code shows the library's text, anything else nothing."""
    markup = "%3Cscript%3Ealert(1)%3C/script%3E"
    status, _, form = site.get(
        f"{site.www}/trust/new?error=nope&peer_url=https://evil.example/x"
        f"&trust_type=friend&description={markup}&relationship=evilrel"
    )
    assert status == 200
    for text in ("evil.example", "evilrel", "alert(1)", '<div class="aw-error"'):
        assert text not in form
    status, _, form = site.get(f"{site.www}/trust/new?error={markup}")
    assert "alert(1)" not in form and '<div class="aw-error"' not in form
    status, _, listing = site.get(f"{site.www}/trust?notice={markup}&error=x")
    assert status == 200
    assert "alert(1)" not in listing and 'class="aw-notice"' not in listing


def test_a_submitted_value_never_reaches_the_redirect(site: _Site) -> None:
    status, location = site.submit(
        peer_url="//evil.example/x\r\nX-Injected: 1", trust_type=""
    )
    assert status == 302
    assert location == f"{site.www}/trust/new?error=trust_type_required"
