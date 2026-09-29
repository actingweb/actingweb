"""``GET /oauth/spa/session/{id}``: what the endpoint answers.

3.14.5 changed the endpoint to read through ``retrieve_spa_session`` (a
pending email-entry session is a 404, not an echo of the provider's token).
``tests/test_oauth_session.py`` covers the manager; these drive the route.
"""

import time
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from actingweb.constants import (
    OAUTH2_SYSTEM_ACTOR,
    OAUTH_SESSION_BUCKET,
    OAUTH_SESSION_RETRIEVE_GRACE,
)
from actingweb.interface import ActingWebApp
from actingweb.interface.integrations.fastapi_integration import FastAPIIntegration
from actingweb.oauth_session import OAuth2SessionManager
from tests.mcp_token_double import MemoryStore, make_config

URL = "/oauth/spa/session/{}"
SUCCESS_TOKEN_DATA = {
    "access_token": "aw-access",
    "actor_id": "actor-1",
    "email": "u@example.com",
    "expires_at": 1_900_000_000,
    "redirect_url": "/actor-1/app",
}


@pytest.fixture
def env() -> Iterator[
    tuple[TestClient, OAuth2SessionManager, MemoryStore, ActingWebApp]
]:
    aw_app = ActingWebApp(
        aw_type="urn:actingweb:test:session-retrieve",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    )
    app = FastAPI()
    FastAPIIntegration(aw_app, app).setup_routes()
    config, store = make_config()
    mgr = OAuth2SessionManager(config)
    with mock.patch(
        "actingweb.oauth_session.get_oauth2_session_manager", return_value=mgr
    ):
        yield TestClient(app), mgr, store, aw_app


def _store(mgr: OAuth2SessionManager, token_data: dict[str, Any]) -> str:
    return mgr.store_session(token_data=token_data, user_info={})


def test_a_pending_email_session_is_a_404(env: Any) -> None:
    client, mgr, _store_, _app = env
    session_id = _store(mgr, {"access_token": "raw-provider-token"})  # no actor_id
    resp = client.get(URL.format(session_id))
    assert resp.status_code == 404
    assert "raw-provider-token" not in resp.text


def test_a_missing_session_is_a_404(env: Any) -> None:
    client, *_ = env
    assert client.get(URL.format("no-such-session")).status_code == 404


def test_a_success_session_answers_200_with_the_token(env: Any) -> None:
    client, mgr, _store_, _app = env
    session_id = _store(mgr, SUCCESS_TOKEN_DATA)

    resp = client.get(URL.format(session_id))

    assert resp.status_code == 200
    assert resp.json() == {
        "success": True,
        "access_token": "aw-access",
        "actor_id": "actor-1",
        "email": "u@example.com",
        "expires_at": 1_900_000_000,
        "redirect_url": "/actor-1/app",
    }


def test_a_second_get_inside_the_grace_window_is_200(env: Any) -> None:
    client, mgr, _store_, _app = env
    session_id = _store(mgr, SUCCESS_TOKEN_DATA)
    assert client.get(URL.format(session_id)).status_code == 200
    assert client.get(URL.format(session_id)).status_code == 200


def test_a_session_stamped_outside_the_window_is_404_and_deleted(env: Any) -> None:
    client, mgr, store, _config = env
    session_id = _store(mgr, SUCCESS_TOKEN_DATA)
    row = store.bucket(OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET)[session_id]["data"]
    row["retrieved_at"] = int(time.time()) - OAUTH_SESSION_RETRIEVE_GRACE - 5

    assert client.get(URL.format(session_id)).status_code == 404
    assert store.data(OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET, session_id) is None


def test_an_origin_outside_the_allowlist_gets_the_allowlists_origin(env: Any) -> None:
    client, mgr, _store_, aw_app = env
    aw_app.with_spa_cors_origins("https://app.example.com")
    session_id = _store(mgr, SUCCESS_TOKEN_DATA)

    resp = client.get(URL.format(session_id), headers={"Origin": "https://evil.test"})

    assert resp.headers["access-control-allow-origin"] == "https://app.example.com"


def test_an_allowed_origin_is_echoed(env: Any) -> None:
    client, mgr, _store_, aw_app = env
    aw_app.with_spa_cors_origins("https://app.example.com", "https://b.example.com")
    session_id = _store(mgr, SUCCESS_TOKEN_DATA)

    resp = client.get(
        URL.format(session_id), headers={"Origin": "https://b.example.com"}
    )

    assert resp.headers["access-control-allow-origin"] == "https://b.example.com"
