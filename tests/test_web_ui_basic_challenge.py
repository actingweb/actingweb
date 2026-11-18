"""The web UI without an OAuth provider asks the browser for credentials (3.16).

With no provider configured, ``/<actor_id>/www`` without credentials is
answered 401 with a ``Basic`` challenge in the application's realm, so a
browser shows its credential prompt and the creator and passphrase sign in.
FastAPI already let such a request reach the handler, which sends that
challenge; Flask answered ``Bearer realm="ActingWeb"``, which no browser
prompts for. Only the web UI routes: the actor root and ``/properties*`` keep
their answer. With a provider configured the request is redirected to
sign-in, and a provider whose redirect cannot be built never falls back to
``Basic``.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.interface import ActingWebApp
from tests._adoption_helpers import uuid_email


def _aw_app(*, oauth: bool) -> ActingWebApp:
    app = (
        ActingWebApp(
            aw_type="urn:actingweb:test:web-ui-basic",
            database="dynamodb",
            fqdn="test.example.com",
            proto="https://",
        )
        .with_web_ui(enable=True)
        .with_open_factory(enable=True)
    )
    if oauth:
        app = app.with_oauth(client_id="cid", client_secret="csecret")
    return app


_CREATED: dict[str, tuple[str, str]] = {}


def _created(answer: dict[str, Any]) -> str:
    _CREATED[answer["id"]] = (answer["creator"], answer["passphrase"])
    return answer["id"]


def _flask(*, oauth: bool) -> tuple[Any, str, str]:
    aw_app = _aw_app(oauth=oauth)
    app = Flask(__name__)
    aw_app.integrate_flask(app)
    client = app.test_client()
    created = client.post(
        "/", json={"creator": uuid_email()}, headers={"Accept": "application/json"}
    )
    assert created.status_code == 201, created.data
    return client, _created(created.get_json()), aw_app.get_config().auth_realm


def _fastapi(*, oauth: bool) -> tuple[Any, str, str]:
    aw_app = _aw_app(oauth=oauth)
    app = FastAPI()
    aw_app.integrate_fastapi(app)
    client = TestClient(app, follow_redirects=False)
    created = client.post(
        "/", json={"creator": uuid_email()}, headers={"Accept": "application/json"}
    )
    assert created.status_code == 201, created.text
    return client, _created(created.json()), aw_app.get_config().auth_realm


def _assert_basic(response: Any, realm: str) -> None:
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == f'Basic realm="{realm}"'


def test_flask_www_challenges_with_basic_when_no_provider_is_configured() -> None:
    client, actor_id, realm = _flask(oauth=False)
    _assert_basic(client.get(f"/{actor_id}/www"), realm)


def test_fastapi_www_challenges_with_basic_when_no_provider_is_configured() -> None:
    client, actor_id, realm = _fastapi(oauth=False)
    _assert_basic(client.get(f"/{actor_id}/www"), realm)


@pytest.mark.parametrize("integration", ["flask", "fastapi"])
def test_a_configured_provider_redirects(integration: str) -> None:
    build = _flask if integration == "flask" else _fastapi
    client, actor_id, _realm = build(oauth=True)
    response = client.get(f"/{actor_id}/www")
    assert response.status_code == 302
    assert "Basic" not in response.headers.get("WWW-Authenticate", "")


def test_flask_properties_keeps_its_bearer_401() -> None:
    client, actor_id, _realm = _flask(oauth=False)
    response = client.get(f"/{actor_id}/properties")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="ActingWeb"'


def test_a_provider_whose_redirect_fails_sends_no_basic_challenge() -> None:
    client, actor_id, _realm = _flask(oauth=True)
    with mock.patch(
        "actingweb.oauth2.OAuth2Authenticator.create_authorization_url",
        side_effect=RuntimeError("provider unreachable"),
    ):
        response = client.get(f"/{actor_id}/www")
    assert response.status_code == 401
    assert "Basic" not in response.headers.get("WWW-Authenticate", "")


@pytest.mark.parametrize("integration", ["flask", "fastapi"])
def test_the_creator_signs_in_and_a_wrong_passphrase_is_refused(
    integration: str,
) -> None:
    import base64

    build = _flask if integration == "flask" else _fastapi
    client, actor_id, _realm = build(oauth=False)

    def basic(user: str, password: str) -> dict[str, str]:
        raw = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {raw}"}

    email, passphrase = _CREATED[actor_id]
    refused = client.get(f"/{actor_id}/www", headers=basic(email, "wrong"))
    assert refused.status_code == 403
    # The browser keeps the wrong credentials and will not ask again, so
    # the 403 says how to retry (3.16; it had no body).
    assert "close the browser" in refused.text
    signed_in = client.get(f"/{actor_id}/www", headers=basic(email, passphrase))
    assert signed_in.status_code == 200


@pytest.mark.parametrize("integration", ["flask", "fastapi"])
def test_a_403_that_is_not_a_wrong_passphrase_gets_no_retry_text(
    integration: str,
) -> None:
    """An actor with no passphrase (made through OAuth, say) refuses every
    Basic sign-in; closing the browser cannot help, so the 403 does not say
    it would (3.16)."""
    import base64

    from actingweb.actor import Actor

    build = _flask if integration == "flask" else _fastapi
    client, actor_id, _realm = build(oauth=False)
    email, passphrase = _CREATED[actor_id]
    raw = base64.b64encode(f"{email}:{passphrase}".encode()).decode()
    loaded = Actor.get

    def without_passphrase(self: Actor, actor_id: str | None = None) -> Any:
        row = loaded(self, actor_id)
        self.passphrase = ""
        return row

    with mock.patch.object(Actor, "get", without_passphrase):
        refused = client.get(
            f"/{actor_id}/www", headers={"Authorization": f"Basic {raw}"}
        )
    assert refused.status_code == 403
    assert "close the browser" not in refused.text
