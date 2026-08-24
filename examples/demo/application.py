#!/usr/bin/env python3
"""
ActingWeb Demo Application using the modern interface.

This demonstrates the new ActingWeb interface with clean, fluent configuration
and decorator-based hooks instead of the old OnAWBase system.

Includes MCP (Model Context Protocol) support for AI language model integration.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from actingweb.interface import ActingWebApp
from actingweb.permission_integration import AccessControlConfig

# Load environment variables from .env file before any config is read
load_dotenv()

# A WSGI loader (Serverless/gunicorn importing a dotted module path such as
# examples.demo.application) puts the deployment root on sys.path, not this
# file's own directory -- unlike running this file directly, where Python
# does that automatically. Without this, `from shared_hooks import ...`
# resolves only by accident, depending on how this module was loaded.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared_hooks import register_all_shared_hooks  # noqa: E402

# Configure logging
logging.basicConfig(stream=sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"))
LOG = logging.getLogger()
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Suppress noisy urllib3 connection pool debug logs
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

# Create ActingWeb app with fluent configuration
aw_app = (
    ActingWebApp(
        aw_type="urn:actingweb:actingweb.io:actingwebdemo",
        database="dynamodb",
        fqdn=os.getenv("APP_HOST_FQDN", "localhost:5000"),
        proto=os.getenv("APP_HOST_PROTOCOL", "https://"),
    )
    # OAuth2 configuration - supports Google and GitHub providers via the new authentication system
    .with_oauth(
        client_id=os.getenv(
            "OAUTH_CLIENT_ID",
            os.getenv("APP_OAUTH_ID", ""),
        ),
        client_secret=os.getenv("OAUTH_CLIENT_SECRET", os.getenv("APP_OAUTH_KEY", "")),
        scope=os.getenv(
            "OAUTH_SCOPE", "openid email profile"
        ),  # Default to Google scopes
        auth_uri=os.getenv(
            "OAUTH_AUTH_URI", "https://accounts.google.com/o/oauth2/v2/auth"
        ),
        token_uri=os.getenv("OAUTH_TOKEN_URI", "https://oauth2.googleapis.com/token"),
        redirect_uri=f"{os.getenv('APP_HOST_PROTOCOL', 'https://')}{os.getenv('APP_HOST_FQDN', 'localhost:5000')}/oauth/callback",
    )
    .with_web_ui(enable=True)
    # Defaults to disabled -- this is the code behind demo.actingweb.io, and
    # devtest exposes mutation/read endpoints plus a passphrase OAuth grant
    # that must not be reachable in a live deployment. Set ENABLE_DEVTEST=true
    # for local development only.
    .with_devtest(enable=os.getenv("ENABLE_DEVTEST", "false").lower() == "true")
    .with_bot(
        token=os.getenv("APP_BOT_TOKEN", ""),
        email=os.getenv("APP_BOT_EMAIL", ""),
        secret=os.getenv("APP_BOT_SECRET", ""),
        admin_room=os.getenv("APP_BOT_ADMIN_ROOM", ""),
    )
    .with_unique_creator(enable=True)  # Each user gets one actor
    .with_email_as_creator(enable=True)  # Use email from OAuth as creator
    .with_mcp(enable=True)  # Enable MCP server support for AI assistants
    .add_actor_type(
        name="myself",
        factory=f"{os.getenv('APP_HOST_PROTOCOL', 'https://')}{os.getenv('APP_HOST_FQDN', 'localhost:5000')}/",
        relationship="friend",
    )
    # Property lookup table configuration for large property values
    # This enables reverse lookups (find actor by property value) without the 2048-byte GSI limit
    .with_indexed_properties(["oauthId", "email", "externalUserId"])
    .with_legacy_property_index(
        enable=False
    )  # Use new lookup table instead of legacy GSI
)

# Configure OAuth2 provider and trust relationship settings
oauth_provider = os.getenv("OAUTH_PROVIDER", "google")  # "google" or "github"
try:
    config_obj = aw_app.get_config()
    config_obj.oauth2_provider = oauth_provider
    LOG.info(f"OAuth2 provider configured: {oauth_provider}")

    # Configure trust relationship settings
    config_obj.default_relationship = "friend"
    config_obj.auto_accept_default_relationship = True
    LOG.info(
        f"Trust auto-approval enabled for relationship: {config_obj.default_relationship}"
    )
    LOG.info("Trust requests with other relationships will require manual approval")
except Exception as e:
    LOG.error(f"Failed to configure OAuth2/trust settings: {e}")

# Initialize OAuth2 state manager at startup (for MCP OAuth flows)
# This ensures the encryption key is created before any OAuth flows begin
try:
    from actingweb.oauth2_server.state_manager import get_oauth2_state_manager

    state_manager = get_oauth2_state_manager(aw_app.get_config())
    LOG.info("OAuth2 state manager initialized successfully")
except Exception as e:
    LOG.warning(f"OAuth2 state manager initialization skipped: {e}")
    # Continue anyway - non-MCP OAuth flows will still work

# Configure unified access control with MCP trust types
# This controls what AI assistants can access via the MCP protocol
try:
    access_control = AccessControlConfig(aw_app.get_config())

    # MCP client trust type: read-only access excluding sensitive properties
    access_control.add_trust_type(
        name="mcp_client",
        display_name="AI Assistant",
        description="AI assistant with read-only access to search actor properties. Sensitive data like tokens and email are excluded.",
        permissions={
            "properties": {
                "patterns": ["*"],  # Allow access to all properties
                "operations": ["read"],  # Read-only access
                "excluded_patterns": [
                    "email",
                    "auth_token",
                    "oauth_token",
                    "access_token",
                    "refresh_token",
                    "_*",  # Internal properties
                ],
            },
            "methods": ["get_*", "list_*", "search_*"],  # Read operations only
            "tools": ["search"],  # Only the search MCP tool
            "resources": [],  # No resource access
            "prompts": ["*"],  # All prompts available
        },
        oauth_scope="mcp",
    )

    # Configure OAuth2 trust type selection for MCP clients
    access_control.configure_oauth2_trust_types(
        allowed_trust_types=["mcp_client"],
        default_trust_type="mcp_client",
    )

    LOG.info("MCP access control configured with mcp_client trust type")
except Exception as e:
    LOG.warning(f"MCP access control configuration skipped: {e}")

# Register all shared hooks
register_all_shared_hooks(aw_app)

# Create Flask app
app = Flask(__name__, static_url_path="/static")

# Trust proxy headers (X-Forwarded-Proto, X-Forwarded-Host, etc.) from ngrok/reverse proxies
# This ensures request.url uses https:// when behind a proxy that terminates SSL
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)  # type: ignore[assignment]


# Health check endpoint for monitoring
@app.route("/health")
def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "integration": "flask",
        "mcp_enabled": True,
        "mcp_tools": ["search"],
        "version": "1.0.0-mcp",
    }


# Custom error handlers
@app.errorhandler(404)
def not_found(_error):
    return {"error": "Not found"}, 404


@app.errorhandler(500)
def internal_error(_error):
    return {"error": "Internal server error"}, 500


# Nuke endpoint for test environment cleanup
@app.route("/nuke", methods=["GET"])
def nuke_all_actors():
    """
    Delete all actors and their data from DynamoDB.

    This is a destructive operation intended for test environments only.
    Requires a secret parameter matching the NUKE_SECRET environment variable.

    Usage: GET /nuke?secret=<NUKE_SECRET>
    """
    import hmac

    import boto3
    from flask import request

    from actingweb import actor

    # Verify secret
    nuke_secret = os.getenv("NUKE_SECRET", "")
    if not nuke_secret:
        return {"error": "NUKE_SECRET not configured"}, 503

    provided_secret = request.args.get("secret", "")
    if not provided_secret or not hmac.compare_digest(provided_secret, nuke_secret):
        return {"error": "Invalid or missing secret"}, 403

    # Get config
    config = aw_app.get_config()

    # Scan all actors using boto3
    deleted = []
    skipped = []
    errors = []

    try:
        # Configure boto3 to use local DynamoDB if AWS_DB_HOST is set
        dynamodb_config = {}
        db_host = os.getenv("AWS_DB_HOST")
        if db_host:
            dynamodb_config["endpoint_url"] = db_host

        dynamodb = boto3.resource("dynamodb", **dynamodb_config)

        # Get table name from environment (same as ActingWeb uses)
        table_prefix = os.getenv("AWS_DB_PREFIX", "demo_actingweb")
        table_name = f"{table_prefix}_actors"
        table = dynamodb.Table(table_name)  # type: ignore[attr-defined]

        # Scan all actors
        response = table.scan(ProjectionExpression="id, creator")
        all_actors = response.get("Items", [])

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = table.scan(
                ProjectionExpression="id, creator",
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            all_actors.extend(response.get("Items", []))

        if not all_actors:
            return {
                "status": "complete",
                "message": "No actors found",
                "deleted": 0,
                "skipped": 0,
            }

        for actor_data in all_actors:
            actor_id = actor_data.get("id", "")
            creator = actor_data.get("creator", "")

            # Skip system actors
            if actor_id.startswith("_actingweb_"):
                skipped.append(
                    {"id": actor_id, "creator": creator, "reason": "system actor"}
                )
                continue

            try:
                # Load and delete the actor (this also cleans up properties, attributes, etc.)
                a = actor.Actor(actor_id=actor_id, config=config)
                if a.id:
                    a.delete()
                    deleted.append({"id": actor_id, "creator": creator})
                    LOG.info(f"Nuked actor: {actor_id} ({creator})")
                else:
                    skipped.append(
                        {"id": actor_id, "creator": creator, "reason": "not found"}
                    )
            except Exception as e:
                errors.append({"id": actor_id, "creator": creator, "error": str(e)})
                LOG.error(f"Error deleting actor {actor_id}: {e}")

        return {
            "status": "complete",
            "deleted": len(deleted),
            "skipped": len(skipped),
            "errors": len(errors),
            "details": {
                "deleted": deleted,
                "skipped": skipped,
                "errors": errors,
            },
        }

    except Exception as e:
        LOG.error(f"Nuke operation failed: {e}")
        return {"error": f"Nuke operation failed: {str(e)}"}, 500


# Integrate with Flask
integration = aw_app.integrate_flask(app)

if __name__ == "__main__":
    LOG.info("Starting ActingWeb Demo...")

    # Run in development mode
    app.run(host="0.0.0.0", port=5000, debug=True)
