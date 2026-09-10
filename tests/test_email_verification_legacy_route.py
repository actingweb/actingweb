"""
Regression tests for the removal of the legacy email-verification handler.

``/{actor_id}/www/verify_email`` (GET and POST) was an unauthenticated route
that let anyone holding an actor id rotate its verification token and fire
``email_verification_required`` — see the 3.14.5 plan and changelog REMOVED
entry. This pins that both integrations no longer register the route and
that the module is gone. The surviving mechanism
(``GET /oauth/email?verify=<token>``) is covered in
``tests/test_oauth_email_verify_link.py``.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.interface import ActingWebApp
from actingweb.interface.integrations.fastapi_integration import FastAPIIntegration
from actingweb.interface.integrations.flask_integration import FlaskIntegration


def test_email_verification_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        import actingweb.handlers.email_verification  # type: ignore[import-not-found]  # noqa: F401


@pytest.fixture
def aw_app() -> ActingWebApp:
    return ActingWebApp(
        aw_type="urn:actingweb:test:legacy-verify",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_devtest(enable=True)


class TestFlaskLegacyRouteRemoved:
    def test_get_verify_email_is_404(self, aw_app: ActingWebApp) -> None:
        flask_app = Flask(__name__)
        FlaskIntegration(aw_app, flask_app)
        client = flask_app.test_client()

        resp = client.get("/some-actor-id/www/verify_email?token=abc")
        assert resp.status_code == 404

    def test_post_verify_email_is_404(self, aw_app: ActingWebApp) -> None:
        flask_app = Flask(__name__)
        FlaskIntegration(aw_app, flask_app)
        client = flask_app.test_client()

        resp = client.post("/some-actor-id/www/verify_email")
        assert resp.status_code == 404


class TestFastAPILegacyRouteRemoved:
    def test_get_verify_email_is_404(self, aw_app: ActingWebApp) -> None:
        fastapi_app = FastAPI()
        FastAPIIntegration(aw_app, fastapi_app)
        client = TestClient(fastapi_app)

        resp = client.get("/some-actor-id/www/verify_email?token=abc")
        assert resp.status_code == 404

    def test_post_verify_email_is_404(self, aw_app: ActingWebApp) -> None:
        fastapi_app = FastAPI()
        FastAPIIntegration(aw_app, fastapi_app)
        client = TestClient(fastapi_app)

        resp = client.post("/some-actor-id/www/verify_email")
        assert resp.status_code == 404
