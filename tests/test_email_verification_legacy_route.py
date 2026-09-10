"""
Regression tests for the removal of the legacy email-verification handler,
and for what the surviving mechanism renders.

``/{actor_id}/www/verify_email`` (GET and POST) was an unauthenticated route
that let anyone holding an actor id rotate its verification token and fire
``email_verification_required`` — see the 3.14.5 plan and changelog REMOVED
entry. This pins that neither integration registers the route any more, that
the module is gone, and that the surviving mechanism
(``GET /oauth/email?verify=<token>``) renders a verification *result* rather
than the email-entry form. The handler-level behaviour of that path is
covered in ``tests/test_oauth_email_verify_link.py``.
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


@pytest.fixture
def flask_app(aw_app: ActingWebApp) -> Flask:
    """A Flask app with ActingWeb's routes actually registered.

    Constructing ``FlaskIntegration`` registers nothing — ``setup_routes()``
    does, and ``ActingWebApp.integrate_flask()`` is what normally calls it.
    Without that call the app has one rule (static) and *every* path answers
    404, so a "the route is gone" assertion would pass whether or not the
    route was gone.
    """
    app = Flask(__name__)
    FlaskIntegration(aw_app, app).setup_routes()
    return app


@pytest.fixture
def fastapi_client(aw_app: ActingWebApp) -> TestClient:
    """Same for FastAPI: ``__init__`` registers nothing, ``setup_routes()`` does."""
    app = FastAPI()
    FastAPIIntegration(aw_app, app).setup_routes()
    return TestClient(app)


class TestLegacyRouteNoLongerRegistered:
    """The route table is the precise assertion. A status code alone is not:
    Flask's generic ``/<actor_id>/www/<path:path>`` catches the legacy path
    and answers 401, which is indistinguishable from a route that still
    exists behind auth."""

    def test_flask_has_no_verify_email_rule(self, flask_app: Flask) -> None:
        rules = [str(r) for r in flask_app.url_map.iter_rules()]
        assert rules, "setup_routes() registered nothing — the test is vacuous"
        assert not [r for r in rules if "verify_email" in r]

    def test_fastapi_has_no_verify_email_route(
        self, fastapi_client: TestClient
    ) -> None:
        paths = [getattr(r, "path", "") for r in fastapi_client.app.routes]  # type: ignore[attr-defined]
        assert paths, "setup_routes() registered nothing — the test is vacuous"
        assert not [p for p in paths if "verify_email" in p]

    def test_flask_legacy_path_falls_through_to_the_authed_www_route(
        self, flask_app: Flask
    ) -> None:
        """401, not 404: Flask's catch-all www route claims the path. Nothing
        rotates a token, which is what the removal was for."""
        client = flask_app.test_client()
        assert (
            client.get("/some-actor-id/www/verify_email?token=abc").status_code == 401
        )
        assert client.post("/some-actor-id/www/verify_email").status_code == 401

    def test_fastapi_legacy_path_is_404(self, fastapi_client: TestClient) -> None:
        assert (
            fastapi_client.get("/some-actor-id/www/verify_email?token=abc").status_code
            == 404
        )
        assert fastapi_client.post("/some-actor-id/www/verify_email").status_code == 404


class TestSurvivingRouteRendersAResultNotTheForm:
    """Both integrations used to route every ``template_values`` from
    ``/oauth/email`` to ``aw-oauth-email.html``, which renders an input form
    unconditionally — so a bad verification link showed a form and a good one
    asked the user for the address they had just verified. They now branch on
    the ``status`` key that only the verification path sets.

    The status code is 200 in both cases because neither integration
    propagates the handler's status to a templated response; that is
    pre-existing and applies equally to the form's own error branches. The
    body is the assertion that matters.
    """

    def test_flask_verify_link_renders_the_result_template(
        self, flask_app: Flask
    ) -> None:
        body = (
            flask_app.test_client()
            .get("/oauth/email?verify=no-such-token")
            .get_data(as_text=True)
        )

        assert "Email verification" in body
        assert "<form" not in body
        assert 'name="email"' not in body

    def test_fastapi_verify_link_renders_the_result_template(
        self, fastapi_client: TestClient
    ) -> None:
        body = fastapi_client.get("/oauth/email?verify=no-such-token").text

        assert "Email verification" in body
        assert "<form" not in body
        assert 'name="email"' not in body

    def test_flask_form_path_still_renders_the_form(self, flask_app: Flask) -> None:
        """The other side of the branch: no verify token means the form."""
        body = (
            flask_app.test_client()
            .get("/oauth/email?session=no-such-session")
            .get_data(as_text=True)
        )

        assert "Enter your email" in body
        assert "<form" in body

    def test_fastapi_form_path_still_renders_the_form(
        self, fastapi_client: TestClient
    ) -> None:
        body = fastapi_client.get("/oauth/email?session=no-such-session").text

        assert "Enter your email" in body
        assert "<form" in body
