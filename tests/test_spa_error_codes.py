"""Every SPA token-endpoint error carries a stable code (3.16).

The ``X-ActingWeb-Error`` response header and the body's ``code`` key name the
reason, so a client can tell a 401 that is the library's and final (it carries
the header) from one a gateway produced. Both integrations forward the header,
CORS exposes it, and the fault handler's answers carry it too.
"""

from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.db.exceptions import DbError
from actingweb.interface import ActingWebApp
from actingweb.oauth_session import _REFRESH_TOKEN_BUCKET, OAuth2SessionManager
from tests.mcp_token_double import MemoryStore, make_config

ORIGIN = "https://spa.example.com"
HEADER = "X-ActingWeb-Error"


def _app() -> ActingWebApp:
    return ActingWebApp(
        aw_type="urn:actingweb:test:error-codes",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_unique_creator(False)


def _fastapi() -> TestClient:
    app = FastAPI()
    _app().integrate_fastapi(app)
    return TestClient(app)


class _FlaskClient:
    """Adapts Flask's test client to the FastAPI client's ``.post`` shape."""

    def __init__(self) -> None:
        app = Flask(__name__)
        _app().integrate_flask(app)
        self._client = app.test_client()

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._client.post(path, **kwargs)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._client.get(path, **kwargs)


CLIENTS = [pytest.param(_fastapi, id="fastapi"), pytest.param(_FlaskClient, id="flask")]


@pytest.fixture
def store_faults() -> Iterator[MemoryStore]:
    config, store = make_config()
    mgr = OAuth2SessionManager(config)
    with mock.patch(
        "actingweb.oauth_session.get_oauth2_session_manager", return_value=mgr
    ):
        yield store


def _body(resp: Any) -> dict[str, Any]:
    """FastAPI's ``json()`` is a method, Flask's test response has it too."""
    return resp.get_json() if hasattr(resp, "get_json") else resp.json()


def _exposed(resp: Any) -> str:
    return resp.headers.get("Access-Control-Expose-Headers", "")


def _assert_coded(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status
    assert resp.headers[HEADER] == code
    body = _body(resp)
    assert body["code"] == code
    assert body["error"] is True  # unchanged
    assert HEADER in _exposed(resp)
    assert "Retry-After" in _exposed(resp)


@pytest.mark.parametrize("make_client", CLIENTS)
def test_an_unknown_refresh_token_is_invalid_grant(
    make_client: Any, store_faults: MemoryStore
) -> None:
    resp = make_client().post(
        "/oauth/spa/token",
        json={"grant_type": "refresh_token", "refresh_token": "never-issued"},
        headers={"Origin": ORIGIN},
    )
    _assert_coded(resp, 401, "invalid_grant")


@pytest.mark.parametrize("make_client", CLIENTS)
def test_an_unknown_grant_type_is_unsupported_grant_type(
    make_client: Any, store_faults: MemoryStore
) -> None:
    resp = make_client().post(
        "/oauth/spa/token",
        json={"grant_type": "bogus"},
        headers={"Origin": ORIGIN},
    )
    _assert_coded(resp, 400, "unsupported_grant_type")


@pytest.mark.parametrize("make_client", CLIENTS)
def test_invalid_json_is_invalid_request(
    make_client: Any, store_faults: MemoryStore
) -> None:
    resp = make_client().post(
        "/oauth/spa/token",
        data="{not json",
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    _assert_coded(resp, 400, "invalid_request")


@pytest.mark.parametrize("make_client", CLIENTS)
def test_a_token_store_fault_is_temporarily_unavailable(
    make_client: Any, store_faults: MemoryStore
) -> None:
    store_faults.faulty_buckets.add(_REFRESH_TOKEN_BUCKET)
    resp = make_client().post(
        "/oauth/spa/token",
        json={"grant_type": "refresh_token", "refresh_token": "rt"},
        headers={"Origin": ORIGIN},
    )
    _assert_coded(resp, 503, "temporarily_unavailable")
    assert resp.headers["Retry-After"] == "5"


@pytest.mark.parametrize("make_client", CLIENTS)
@pytest.mark.parametrize("path", ["/oauth/spa/token", "/oauth/token"])
def test_a_db_error_through_the_fault_handler_carries_the_header(
    make_client: Any, path: str
) -> None:
    target = (
        "actingweb.handlers.oauth2_spa.OAuth2SPAHandler.post"
        if path == "/oauth/spa/token"
        else "actingweb.handlers.oauth2_endpoints.OAuth2EndpointsHandler.post"
    )
    with mock.patch(target, side_effect=DbError("simulated")):
        resp = make_client().post(path, json={}, headers={"Origin": ORIGIN})
    assert resp.status_code == 503
    assert resp.headers[HEADER] == "temporarily_unavailable"
    assert HEADER in _exposed(resp)
    assert "Retry-After" in _exposed(resp)


def test_the_fastapi_session_retrieve_404_carries_not_found() -> None:
    client = _fastapi()
    with mock.patch(
        "actingweb.oauth_session.OAuth2SessionManager.retrieve_spa_session",
        return_value=None,
    ):
        resp = client.get("/oauth/spa/session/missing", headers={"Origin": ORIGIN})
    assert resp.status_code == 404
    assert resp.headers[HEADER] == "not_found"
    assert resp.json()["code"] == "not_found"
    assert HEADER in _exposed(resp)


@pytest.mark.parametrize("make_client", CLIENTS)
def test_the_passphrase_grant_outside_devtest_is_access_denied(
    make_client: Any, store_faults: MemoryStore
) -> None:
    # The test app does not enable devtest, so the grant is refused.
    resp = make_client().post(
        "/oauth/spa/token",
        json={"grant_type": "passphrase", "actor_id": "nobody", "passphrase": "x"},
        headers={"Origin": ORIGIN},
    )
    _assert_coded(resp, 403, "access_denied")
