"""
Minimal ActingWeb test harness.

This is a standalone Flask application using the ActingWeb library,
designed for integration testing. It's completely independent of
actingwebdemo and actingweb_mcp.
"""

import os
import logging
import json
import re
from flask import Flask
from actingweb.interface import ActingWebApp

# Suppress Flask debug output
logging.getLogger('werkzeug').setLevel(logging.ERROR)


def create_test_app(
    fqdn: str = "localhost:5555",
    proto: str = "http://",
    enable_oauth: bool = False,
    enable_mcp: bool = False,
    enable_devtest: bool = True,
) -> tuple[Flask, ActingWebApp]:
    """
    Create a minimal ActingWeb test harness.

    Args:
        fqdn: Fully qualified domain name for the test app
        proto: Protocol (http:// or https://)
        enable_oauth: Enable OAuth2 configuration
        enable_mcp: Enable MCP endpoints
        enable_devtest: Enable devtest endpoints (for proxy tests)

    Returns:
        Tuple of (flask_app, actingweb_app)
    """
    # Create ActingWeb app with minimal configuration
    aw_app = (
        ActingWebApp(
            aw_type="urn:actingweb:test:integration",
            database="dynamodb",
            fqdn=fqdn,
            proto=proto,
        )
        .with_web_ui(enable=True)
        .with_devtest(enable=enable_devtest)
        .with_unique_creator(enable=False)
        .with_email_as_creator(enable=False)
    )

    # Optional: Add OAuth2 configuration for OAuth tests
    if enable_oauth:
        aw_app = aw_app.with_oauth(
            client_id="test-client-id",
            client_secret="test-client-secret",
            scope="openid email profile",
            auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
            token_uri="https://oauth2.googleapis.com/token",
            redirect_uri=f"{proto}{fqdn}/oauth/callback",
        )

    # Optional: Enable MCP for MCP tests
    if enable_mcp:
        aw_app = aw_app.with_mcp(enable=True)

    # Create Flask app
    flask_app = Flask(__name__)
    flask_app.config['TESTING'] = True

    # Integrate with Flask
    aw_app.integrate_flask(flask_app)

    return flask_app, aw_app
