"""Tests for FastAPI TemplateResponse rendering (Starlette 1.0 signature)."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from actingweb.interface import ActingWebApp

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "integration", "templates")


@pytest.fixture
def aw_app() -> ActingWebApp:
    """Create an ActingWeb app with web UI enabled."""
    return (
        ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
            proto="https://",
        )
        .with_web_ui(enable=True)
        .with_devtest(enable=True)
    )


@pytest.fixture
def fastapi_app_with_templates(aw_app: ActingWebApp) -> FastAPI:
    """Create a FastAPI app with ActingWeb routes and templates configured."""
    app = FastAPI()
    aw_app.integrate_fastapi(app, templates_dir=TEMPLATES_DIR)
    return app


@pytest.fixture
def client(fastapi_app_with_templates: FastAPI) -> TestClient:
    return TestClient(fastapi_app_with_templates)


class TestTemplateResponseRendering:
    """Verify TemplateResponse works with the Starlette 1.0 signature."""

    def test_factory_get_renders_template(self, client: TestClient) -> None:
        """GET / should render aw-root-factory.html as HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Create ActingWeb Actor" in response.text

    def test_factory_get_no_context_renders(self, client: TestClient) -> None:
        """GET / without OAuth still renders (no context arg passed)."""
        response = client.get("/")
        assert response.status_code == 200
        assert "<form" in response.text

    def test_factory_post_missing_email_renders_error_template(
        self, client: TestClient
    ) -> None:
        """POST / with empty form should render factory template with error."""
        response = client.post(
            "/",
            data={"creator": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        # Should return HTML (template rendered), not crash
        assert "text/html" in response.headers.get("content-type", "")


class TestTemplateResponseWithContext:
    """Verify template context variables are correctly passed."""

    def test_factory_get_includes_oauth_context(
        self, client: TestClient
    ) -> None:
        """GET / with web UI should pass oauth_enabled in template context."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestTemplateResponseWithoutTemplates:
    """Verify fallback when no templates directory is configured."""

    def test_factory_get_returns_inline_html(self) -> None:
        """GET / without templates_dir should return inline HTML fallback."""
        aw_app = (
            ActingWebApp(
                aw_type="urn:actingweb:test",
                database="dynamodb",
                fqdn="test.example.com",
                proto="https://",
            )
            .with_web_ui(enable=True)
            .with_devtest(enable=True)
        )
        app = FastAPI()
        aw_app.integrate_fastapi(app)  # No templates_dir
        client = TestClient(app)

        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Welcome to ActingWeb" in response.text
