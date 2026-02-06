"""
MCP Resource Regression Tests.

These tests verify bug fixes in the async MCP resource handler:
1. Legacy "uri" field fallback
2. Empty template variables (empty dict should match)
3. Correct parameter order in _match_uri_template
"""

import pytest
from mcp.types import LATEST_PROTOCOL_VERSION


def initialize_mcp_session(oauth2_client):
    """Helper to initialize an MCP session."""
    # Initialize
    init_response = oauth2_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "Test Client", "version": "1.0.0"},
            },
            "id": 1,
        },
        headers={"Content-Type": "application/json"},
    )
    assert init_response.status_code == 200

    # Send initialized notification
    notif_response = oauth2_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        headers={"Content-Type": "application/json"},
    )
    assert notif_response.status_code == 200


@pytest.fixture(scope="module")
def regression_test_app(docker_services, setup_database, worker_info):  # pylint: disable=unused-argument
    """
    Create a test app with custom MCP resources to test regression fixes.

    This fixture creates a separate app instance with custom resource hooks
    that specifically test the three bug fixes.
    """
    import os
    from threading import Thread

    import requests
    import uvicorn
    from fastapi import FastAPI

    from actingweb.interface import ActingWebApp
    from actingweb.mcp.decorators import mcp_resource

    # Worker-specific configuration (use different port from main test_app)
    test_app_port = 9000 + worker_info["port_offset"]
    test_app_url = f"http://127.0.0.1:{test_app_port}"

    # Create ActingWeb app
    aw_app = (
        ActingWebApp(
            aw_type="urn:actingweb:test:mcp-regression",
            database=None,  # Use DATABASE_BACKEND env var
            fqdn=f"127.0.0.1:{test_app_port}",
            proto="http://",
        )
        .with_web_ui(enable=True)
        .with_devtest(enable=True)
        .with_unique_creator(enable=False)
        .with_email_as_creator(enable=False)
        .with_oauth(
            client_id="test-client-id",
            client_secret="test-client-secret",
            scope="openid email profile",
            auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
            token_uri="https://oauth2.googleapis.com/token",
            redirect_uri=f"http://127.0.0.1:{test_app_port}/oauth/callback",
        )
        .with_mcp(enable=True)
    )

    # Register custom resources to test the three bug fixes

    # Bug Fix #1: Test legacy "uri" field fallback (no uri_template)
    @aw_app.method_hook("legacy_uri_resource")
    @mcp_resource(
        uri_template=None,  # Intentionally not provided
        name="Legacy URI Resource",
        description="Resource using legacy uri field for backward compatibility",
    )
    def legacy_uri_resource_hook(_actor, _method_name, _params):
        """
        Test legacy "uri" field fallback.

        This simulates resources that were registered before uri_template existed.
        The handler should fall back to metadata.get("uri") field.
        """
        # Manually set the "uri" field in metadata (simulating old-style registration)
        # Note: We can't actually override the decorator metadata here, but the test
        # will verify that the fallback chain works by checking if actingweb://legacy_uri_resource
        # is accessible (default fallback).
        return {
            "contents": [
                {
                    "uri": "actingweb://legacy_uri_resource",
                    "mimeType": "text/plain",
                    "text": "legacy_uri_fallback_success",
                }
            ]
        }

    # Bug Fix #2: Test empty template variables (no placeholders in URI)
    @aw_app.method_hook("static_resource")
    @mcp_resource(
        uri_template="actingweb://static",
        name="Static Resource",
        description="Resource with no URI variables (empty dict should match)",
    )
    def static_resource_hook(_actor, _method_name, _params):
        """
        Test resources without URI variables.

        The bug was that empty dict {} was treated as falsy, failing the match.
        This should now work correctly with `is not None` check.
        """
        return {
            "contents": [
                {
                    "uri": "actingweb://static",
                    "mimeType": "text/plain",
                    "text": "empty_dict_match_success",
                }
            ]
        }

    # Bug Fix #3: Test correct parameter order in _match_uri_template
    @aw_app.method_hook("user_data")
    @mcp_resource(
        uri_template="actingweb://users/{userId}/data",
        name="User Data Resource",
        description="Resource with URI parameters to test extraction",
    )
    def user_data_resource_hook(_actor, _method_name, params):
        """
        Test URI template parameter extraction.

        The bug was reversed parameters: _match_uri_template(uri, template)
        should be _match_uri_template(template, uri).
        This resource verifies that variables are correctly extracted.
        """
        # params should contain the extracted userId
        user_id = params.get("userId", "unknown")
        return {
            "contents": [
                {
                    "uri": f"actingweb://users/{user_id}/data",
                    "mimeType": "application/json",
                    "text": f'{{"userId": "{user_id}", "status": "parameter_extraction_success"}}',
                }
            ]
        }

    # Create FastAPI app and integrate with ActingWeb
    fastapi_app = FastAPI()
    aw_app.integrate_fastapi(fastapi_app)

    # Set environment based on database backend
    os.environ["DATABASE_BACKEND"] = os.getenv("DATABASE_BACKEND", "dynamodb")

    if os.environ["DATABASE_BACKEND"] == "dynamodb":
        os.environ["AWS_ACCESS_KEY_ID"] = "test"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
        os.environ["AWS_DB_HOST"] = os.getenv(
            "AWS_DB_HOST", "http://localhost:8001"
        )
        os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]
    elif os.environ["DATABASE_BACKEND"] == "postgresql":
        os.environ["PG_DB_HOST"] = os.getenv("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.getenv("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.getenv("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.getenv("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.getenv("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    # Run in background thread
    def run_app():
        uvicorn.run(
            fastapi_app,
            host="0.0.0.0",
            port=test_app_port,
            log_level="error",
        )

    thread = Thread(target=run_app, daemon=True)
    thread.start()

    # Wait for app to be ready
    max_retries = 30
    for _ in range(max_retries):
        try:
            response = requests.get(f"{test_app_url}/", timeout=2)
            if response.status_code in [200, 404]:
                break
        except requests.exceptions.ConnectionError:
            pass
        import time

        time.sleep(0.5)
    else:
        raise RuntimeError(
            f"Regression test app failed to start on port {test_app_port}"
        )

    # Warmup
    for _ in range(3):
        try:
            requests.get(f"{test_app_url}/", timeout=2)
        except requests.exceptions.RequestException:
            pass
        import time

        time.sleep(0.1)

    yield test_app_url


@pytest.fixture(scope="module")
def regression_oauth2_client(regression_test_app, worker_info):
    """
    Create an authenticated OAuth2 client for regression tests.

    Uses the OAuth2TestHelper to create a fully authenticated client.
    """
    from .utils.oauth2_helper import create_authenticated_client

    return create_authenticated_client(
        base_url=regression_test_app, worker_id=worker_info["worker_id"]
    )


class TestMCPResourceRegressions:
    """Test bug fixes in async MCP resource handler."""

    def test_legacy_uri_field_fallback(self, regression_oauth2_client):
        """
        Regression test for Bug #1: Legacy "uri" field fallback.

        Verifies that resources without uri_template still work by falling back
        to the default actingweb://{method_name} pattern.
        """
        initialize_mcp_session(regression_oauth2_client)

        # Read the legacy_uri_resource
        response = regression_oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "resources/read",
                "params": {"uri": "actingweb://legacy_uri_resource"},
                "id": 100,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should succeed with the resource content
        assert "result" in data, f"Expected result, got: {data}"
        assert "contents" in data["result"]
        assert len(data["result"]["contents"]) > 0
        assert data["result"]["contents"][0]["text"] == "legacy_uri_fallback_success"

    def test_empty_template_variables(self, regression_oauth2_client):
        """
        Regression test for Bug #2: Empty template variables (no placeholders).

        The bug was that empty dict {} was treated as falsy, causing the match
        to fail. This verifies that resources without URI variables work correctly.
        """
        initialize_mcp_session(regression_oauth2_client)

        # Read the static resource (no variables in URI template)
        response = regression_oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "resources/read",
                "params": {"uri": "actingweb://static"},
                "id": 101,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should succeed with the resource content
        assert "result" in data, f"Expected result, got: {data}"
        assert "contents" in data["result"]
        assert len(data["result"]["contents"]) > 0
        assert data["result"]["contents"][0]["text"] == "empty_dict_match_success"

    def test_uri_template_parameter_extraction(self, regression_oauth2_client):
        """
        Regression test for Bug #3: Correct parameter order in _match_uri_template.

        The bug was reversed parameters to _match_uri_template(). This verifies
        that URI variables are correctly extracted from templated URIs.
        """
        initialize_mcp_session(regression_oauth2_client)

        # Read the user_data resource with a userId parameter
        response = regression_oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "resources/read",
                "params": {"uri": "actingweb://users/user123/data"},
                "id": 102,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should succeed with the extracted userId
        assert "result" in data, f"Expected result, got: {data}"
        assert "contents" in data["result"]
        assert len(data["result"]["contents"]) > 0

        # Verify the userId was correctly extracted
        import json

        content_data = json.loads(data["result"]["contents"][0]["text"])
        assert content_data["userId"] == "user123"
        assert content_data["status"] == "parameter_extraction_success"
