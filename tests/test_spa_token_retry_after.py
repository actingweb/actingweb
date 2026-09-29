"""A cross-origin SPA can read ``Retry-After`` and the allowlist is honoured.

The refresh grant (3.15.0), ``/oauth/revoke`` and ``/oauth/logout`` (3.15.1)
answer a token store fault with 503 and ``Retry-After``. A browser hides that
header from a cross-origin caller unless it is listed in
``Access-Control-Expose-Headers``. The integrations also used to echo any
``Origin`` with credentials, discarding ``spa_cors_origins``.
"""

from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.interface import ActingWebApp
from actingweb.oauth_session import (
    _ACCESS_TOKEN_BUCKET,
    _REFRESH_TOKEN_BUCKET,
    OAuth2SessionManager,
)
from tests.mcp_token_double import MemoryStore, make_config

ORIGIN = "https://spa.example.com"


def _app(*origins: str) -> ActingWebApp:
    aw_app = ActingWebApp(
        aw_type="urn:actingweb:test:retry-after",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    )
    if origins:
        aw_app.with_spa_cors_origins(*origins)
    return aw_app


def _fastapi(*origins: str) -> TestClient:
    app = FastAPI()
    _app(*origins).integrate_fastapi(app)
    return TestClient(app)


class _FlaskClient:
    """Adapts Flask's test client to the FastAPI client's ``.post`` shape."""

    def __init__(self, *origins: str) -> None:
        app = Flask(__name__)
        _app(*origins).integrate_flask(app)
        self._client = app.test_client()

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._client.post(path, **kwargs)


@pytest.fixture
def store_faults() -> Iterator[MemoryStore]:
    config, store = make_config()
    mgr = OAuth2SessionManager(config)
    with mock.patch(
        "actingweb.oauth_session.get_oauth2_session_manager", return_value=mgr
    ):
        yield store


def _exposed(resp: Any) -> str:
    return resp.headers.get("Access-Control-Expose-Headers", "")


CLIENTS = [pytest.param(_fastapi, id="fastapi"), pytest.param(_FlaskClient, id="flask")]


@pytest.mark.parametrize("make_client", CLIENTS)
def test_the_refresh_grant_503_exposes_retry_after(
    make_client: Any, store_faults: MemoryStore
) -> None:
    store_faults.faulty_buckets.add(_REFRESH_TOKEN_BUCKET)
    resp = make_client().post(
        "/oauth/spa/token",
        json={"grant_type": "refresh_token", "refresh_token": "rt"},
        headers={"Origin": ORIGIN},
    )
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    assert "Retry-After" in _exposed(resp)


@pytest.mark.parametrize("make_client", CLIENTS)
def test_the_revoke_503_exposes_retry_after(
    make_client: Any, store_faults: MemoryStore
) -> None:
    store_faults.faulty_buckets.add(_ACCESS_TOKEN_BUCKET)
    resp = make_client().post(
        "/oauth/revoke", json={"token": "t"}, headers={"Origin": ORIGIN}
    )
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    assert "Retry-After" in _exposed(resp)


@pytest.mark.parametrize("make_client", CLIENTS)
def test_the_logout_503_exposes_retry_after(
    make_client: Any, store_faults: MemoryStore
) -> None:
    store_faults.faulty_buckets.add(_ACCESS_TOKEN_BUCKET)
    resp = make_client().post(
        "/oauth/logout",
        headers={"Origin": ORIGIN, "Authorization": "Bearer some-session-token"},
    )
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    assert "Retry-After" in _exposed(resp)


@pytest.mark.parametrize("make_client", CLIENTS)
@pytest.mark.parametrize("path", ["/oauth/logout", "/oauth/revoke", "/oauth/spa/token"])
def test_an_origin_outside_the_allowlist_gets_the_allowlists_origin(
    make_client: Any, path: str, store_faults: MemoryStore
) -> None:
    resp = make_client("https://a.example.com").post(
        path,
        json={"grant_type": "refresh_token", "refresh_token": "x", "token": "x"},
        headers={"Origin": "https://b.example.com"},
    )
    assert resp.headers["Access-Control-Allow-Origin"] == "https://a.example.com"
    assert resp.headers["Access-Control-Allow-Credentials"] == "true"


@pytest.mark.parametrize("make_client", CLIENTS)
def test_an_allowed_origin_is_echoed(
    make_client: Any, store_faults: MemoryStore
) -> None:
    resp = make_client("https://a.example.com", "https://b.example.com").post(
        "/oauth/logout", headers={"Origin": "https://b.example.com"}
    )
    assert resp.headers["Access-Control-Allow-Origin"] == "https://b.example.com"


@pytest.mark.parametrize("make_client", CLIENTS)
@pytest.mark.parametrize("path", ["/oauth/logout", "/oauth/revoke"])
def test_the_default_config_still_echoes_any_origin(
    make_client: Any, path: str, store_faults: MemoryStore
) -> None:
    resp = make_client().post(
        path, json={"token": "x"}, headers={"Origin": "https://anything.example.com"}
    )
    assert resp.headers["Access-Control-Allow-Origin"] == "https://anything.example.com"


def test_the_fastapi_logout_preflight_honours_the_allowlist() -> None:
    resp = _fastapi("https://a.example.com").options(
        "/oauth/logout", headers={"Origin": "https://b.example.com"}
    )
    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == "https://a.example.com"
    assert "Retry-After" in _exposed(resp)


def test_the_fastapi_spa_logout_alias_preflight_is_credentialed_not_wildcard() -> None:
    resp = _fastapi("https://a.example.com").options(
        "/oauth/spa/logout", headers={"Origin": "https://b.example.com"}
    )
    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == "https://a.example.com"
    assert "Accept" in resp.headers["Access-Control-Allow-Headers"]
    default = _fastapi().options(
        "/oauth/spa/logout", headers={"Origin": "https://spa.example.com"}
    )
    assert default.headers["Access-Control-Allow-Origin"] == "https://spa.example.com"
