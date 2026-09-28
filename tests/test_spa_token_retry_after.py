"""The SPA token endpoint's 503 reaches the client with ``Retry-After``.

The refresh grant answers a token-store fault with 503 and ``Retry-After``
(``OAuth2SPAHandler._store_unavailable``); both integrations used to copy only
the status code, dropping the header a client needs to retry instead of
signing the user out.
"""

from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.handlers.oauth2_spa import OAuth2SPAHandler
from actingweb.interface import ActingWebApp
from actingweb.interface.integrations.fastapi_integration import FastAPIIntegration
from actingweb.interface.integrations.flask_integration import FlaskIntegration


@pytest.fixture
def aw_app() -> ActingWebApp:
    return ActingWebApp(
        aw_type="urn:actingweb:test:spa-retry-after",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    )


def _store_unavailable_post(self: OAuth2SPAHandler, endpoint: str = "") -> Any:
    return self._store_unavailable()


def test_fastapi_passes_retry_after_through(aw_app: ActingWebApp) -> None:
    app = FastAPI()
    FastAPIIntegration(aw_app, app).setup_routes()
    with patch.object(OAuth2SPAHandler, "post", _store_unavailable_post):
        response = TestClient(app).post(
            "/oauth/spa/token",
            json={"grant_type": "refresh_token", "refresh_token": "x"},
        )
    assert response.status_code == 503
    assert response.headers.get("Retry-After") == "5"


def test_flask_passes_retry_after_through(aw_app: ActingWebApp) -> None:
    app = Flask(__name__)
    FlaskIntegration(aw_app, app).setup_routes()
    with patch.object(OAuth2SPAHandler, "post", _store_unavailable_post):
        response = app.test_client().post(
            "/oauth/spa/token",
            json={"grant_type": "refresh_token", "refresh_token": "x"},
        )
    assert response.status_code == 503
    assert response.headers.get("Retry-After") == "5"
