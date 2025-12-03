"""
OAuth2 endpoints handler for ActingWeb (MCP OAuth2 Server Role).

IMPORTANT: ActingWeb has TWO OAuth2 roles:

1. OAuth2 SERVER (this handler) - MCP clients authenticate TO ActingWeb
   - /oauth/register - Dynamic client registration (RFC 7591) for MCP clients
   - /oauth/authorize - Authorization endpoint (MCP client → user consent → ActingWeb)
   - /oauth/token - Token endpoint (issues ActingWeb tokens to MCP clients)
   - /oauth/logout - Logout endpoint

2. OAuth2 CLIENT (see oauth2_spa.py) - Users authenticate VIA Google/GitHub
   - /oauth/spa/authorize - Initiate login with external provider
   - /oauth/spa/token - Refresh external provider tokens
   - /oauth/callback - Receive callback from Google/GitHub

This handler implements role #1: ActingWeb as OAuth2 authorization server for
MCP clients (ChatGPT, Claude, Cursor). User authentication is proxied to
Google/GitHub, but the final tokens issued are ActingWeb tokens.
"""

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from .base_handler import BaseHandler

# Import MCP protocol version constants
try:
    from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
    from mcp.types import LATEST_PROTOCOL_VERSION
except ImportError:
    # Fallback if MCP SDK not available
    LATEST_PROTOCOL_VERSION = "2024-11-05"  # pyright: ignore[reportConstantRedefinition]
    SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05"]  # pyright: ignore[reportConstantRedefinition]

if TYPE_CHECKING:
    from .. import aw_web_request
    from .. import config as config_class
    from ..interface.hooks import HookRegistry

# TrustTypeRegistry imported locally where needed

logger = logging.getLogger(__name__)


class OAuth2EndpointsHandler(BaseHandler):
    """
    Handler for OAuth2 authorization server endpoints.

    This handler implements ActingWeb as a full OAuth2 authorization server:
    1. Dynamic client registration (RFC 7591) for MCP clients
    2. OAuth2 authorization flow with Google user authentication proxy
    3. ActingWeb token issuance and management
    4. OAuth2 callback handling from Google
    """

    def __init__(
        self,
        webobj: Optional["aw_web_request.AWWebObj"] = None,
        config: Optional["config_class.Config"] = None,
        hooks: Optional["HookRegistry"] = None,
    ) -> None:
        if config is None:
            raise RuntimeError("Config is required for OAuth2EndpointsHandler")
        if webobj is None:
            from .. import aw_web_request

            webobj = aw_web_request.AWWebObj()
        super().__init__(webobj, config, hooks)

        # Initialize OAuth2 server
        from ..oauth2_server.oauth2_server import get_actingweb_oauth2_server

        self.oauth2_server = get_actingweb_oauth2_server(config)

    def post(self, path: str = "") -> dict[str, Any]:
        """
        Handle POST requests to OAuth2 endpoints.

        Routes:
        - /oauth/register - Dynamic client registration for MCP clients
        - /oauth/token - Token exchange (authorization_code or refresh_token)
        - /oauth/authorize - Authorization request processing (email form submission)

        Args:
            path: The sub-path after /oauth/

        Returns:
            Response dict
        """
        if path == "register":
            return self._handle_client_registration()
        elif path == "token":
            return self._handle_token_request()
        elif path == "authorize":
            return self._handle_authorization_request("POST")
        elif path == "logout":
            return self._handle_logout_request("POST")
        else:
            return self.error_response(404, f"Unknown OAuth2 endpoint: {path}")

    def options(self, _path: str = "") -> dict[str, Any]:
        """
        Handle OPTIONS requests (CORS preflight).

        Args:
            path: The sub-path after /oauth/

        Returns:
            CORS headers response
        """
        # Set CORS headers
        self.response.headers["Access-Control-Allow-Origin"] = "*"
        self.response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        self.response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, mcp-protocol-version"
        )
        self.response.headers["Access-Control-Max-Age"] = "86400"  # 24 hours

        return {"status": "ok"}

    def get(self, path: str = "") -> dict[str, Any]:
        """
        Handle GET requests to OAuth2 endpoints.

        Routes:
        - /oauth/authorize - Authorization endpoint (shows email form)
        - /oauth/callback - OAuth2 callback from Google (completes MCP flow)
        - /.well-known/oauth-authorization-server - Authorization server discovery (RFC 8414)

        Args:
            path: The sub-path after /oauth/ (or the full well-known path)

        Returns:
            Response dict or redirect
        """
        if path == "authorize":
            return self._handle_authorization_request("GET")
        elif path == "callback":
            return self._handle_oauth_callback()
        elif path == "logout":
            return self._handle_logout_request("GET")
        elif path == ".well-known/oauth-authorization-server":
            return self._handle_authorization_server_discovery()
        elif path == ".well-known/oauth-protected-resource":
            return self._handle_protected_resource_discovery()
        elif path == ".well-known/oauth-protected-resource/mcp":
            return self._handle_protected_resource_mcp_discovery()
        else:
            return self.error_response(404, f"Unknown OAuth2 endpoint: {path}")

    def _handle_client_registration(self) -> dict[str, Any]:
        """
        Handle dynamic client registration (RFC 7591) for MCP clients.

        Request body should contain:
        - client_name: Human-readable name
        - redirect_uris: List of allowed redirect URIs

        Returns:
            Client registration response per RFC 7591
        """
        try:
            # Parse request body
            body: str | bytes | None = self.request.body
            if body is None:
                body_str = "{}"
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = str(body)

            try:
                registration_data = json.loads(body_str)
            except json.JSONDecodeError:
                return self.error_response(400, "Invalid JSON in request body")

            # Register the client using OAuth2 server
            try:
                client_response = self.oauth2_server.handle_client_registration(
                    registration_data
                )
                logger.debug(f"Registered MCP client: {client_response['client_id']}")
                # Set status to 201 Created per RFC 7591
                self.response.set_status(201, "Created")
                return client_response

            except ValueError as e:
                return self.error_response(400, str(e))
            except Exception as e:
                logger.error(f"Client registration failed: {e}")
                return self.error_response(500, "Client registration failed")

        except Exception as e:
            logger.error(f"Error in client registration: {e}")
            return self.error_response(500, "Internal server error")

    def _handle_authorization_request(self, method: str = "GET") -> dict[str, Any]:
        """
        Handle OAuth2 authorization requests.

        For GET: Show email form (same UX as GET /)
        For POST: Process email and redirect to Google OAuth2

        Expected parameters:
        - client_id: Registered client ID
        - redirect_uri: Callback URI (must match registered URI)
        - response_type: Must be "code"
        - scope: Requested scopes
        - state: CSRF protection token

        Returns:
            Email form or redirect response
        """
        try:
            # Get request parameters
            if method == "GET":
                params = {
                    "client_id": self.request.get("client_id") or "",
                    "redirect_uri": self.request.get("redirect_uri") or "",
                    "response_type": self.request.get("response_type") or "",
                    "scope": self.request.get("scope") or "",
                    "state": self.request.get("state") or "",
                }
            else:  # POST
                # Parse form data for POST
                body: str | bytes | None = self.request.body
                if body is None:
                    body_str = ""
                elif isinstance(body, bytes):
                    body_str = body.decode("utf-8", "ignore")
                else:
                    body_str = str(body)

                from urllib.parse import parse_qs

                form_data = parse_qs(body_str)

                params = {
                    "client_id": form_data.get("client_id", [""])[0],
                    "redirect_uri": form_data.get("redirect_uri", [""])[0],
                    "response_type": form_data.get("response_type", [""])[0],
                    "scope": form_data.get("scope", [""])[0],
                    "state": form_data.get("state", [""])[0],
                    "email": form_data.get("email", [""])[0],
                    "trust_type": form_data.get("trust_type", ["mcp_client"])[
                        0
                    ],  # Default to mcp_client
                    "provider": form_data.get("provider", [""])[
                        0
                    ],  # OAuth provider (google/github)
                }

            # Debug logging for MCP OAuth2 flow
            logger.debug(
                f"OAuth2 authorization {method} request with params: {dict(params)}"
            )

            # Handle using OAuth2 server
            server_response = self.oauth2_server.handle_authorization_request(
                params, method
            )

            logger.debug(f"OAuth2 server response: {server_response}")

            if server_response.get("action") == "show_form":
                # Show email form (preserve existing UX)
                form_response = self._render_authorization_form(server_response)
                if form_response is None:
                    # Template values were set, let framework handle rendering
                    return {}  # Return empty dict instead of None
                else:
                    # Return JSON response
                    return form_response
            elif server_response.get("action") == "redirect":
                # Redirect to Google OAuth2
                redirect_url = server_response.get("url")
                if redirect_url:
                    self.response.set_status(302, "Found")
                    self.response.set_redirect(redirect_url)
                    return {"status": "redirect", "location": redirect_url}
                else:
                    return self.error_response(500, "Failed to create redirect URL")
            else:
                # Error response
                error = server_response.get("error", "server_error")
                description = server_response.get("error_description", "Unknown error")
                return self.error_response(400, f"{error}: {description}")

        except Exception as e:
            logger.error(f"Error in authorization request: {e}")
            return self.error_response(500, "Internal server error")

    def _handle_token_request(self) -> dict[str, Any]:
        """
        Handle OAuth2 token requests.

        This endpoint exchanges authorization codes for ActingWeb access tokens
        or refreshes existing tokens.

        Expected parameters:
        - grant_type: "authorization_code" or "refresh_token"
        - code: Authorization code (for authorization_code grant)
        - refresh_token: Refresh token (for refresh_token grant)
        - redirect_uri: Must match the URI used in authorization request
        - client_id: Client identifier
        - client_secret: Client secret (for confidential clients)

        Returns:
            Token response with ActingWeb access token
        """
        try:
            # Parse request body (form-encoded for OAuth2)
            body: str | bytes | None = self.request.body
            if body is None:
                body_str = ""
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = str(body)

            # Parse form data
            from urllib.parse import parse_qs

            form_data = parse_qs(body_str)

            # Debug: log received form data
            logger.debug(f"Token request form data keys: {list(form_data.keys())}")
            logger.debug(f"Token request body: {body_str[:200]}...")  # First 200 chars

            # Extract parameters (parse_qs returns lists)
            params = {
                "grant_type": form_data.get("grant_type", [""])[0],
                "code": form_data.get("code", [""])[0],
                "refresh_token": form_data.get("refresh_token", [""])[0],
                "redirect_uri": form_data.get("redirect_uri", [""])[0],
                "client_id": form_data.get("client_id", [""])[0],
                "client_secret": form_data.get("client_secret", [""])[0],
                "code_verifier": form_data.get("code_verifier", [""])[0],
            }

            # Check for client_id in Authorization header if not in form data
            if not params["client_id"]:
                if not self.request.headers:
                    return self.error_response(
                        400, "invalid_request: No Authorization headsers"
                    )
                auth_header = self.request.headers.get(
                    "Authorization", ""
                ) or self.request.headers.get("authorization", "")
                if auth_header.startswith("Basic "):
                    try:
                        import base64

                        encoded_creds = auth_header[6:]  # Remove "Basic "
                        decoded_creds = base64.b64decode(encoded_creds).decode("utf-8")
                        if ":" in decoded_creds:
                            client_id, client_secret = decoded_creds.split(":", 1)
                            params["client_id"] = client_id
                            if not params["client_secret"]:
                                params["client_secret"] = client_secret
                            logger.debug(
                                f"Extracted client_id from Authorization header: {client_id}"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to parse Authorization header: {e}")

            # Handle using OAuth2 server
            token_response = self.oauth2_server.handle_token_request(params)

            if "error" in token_response:
                error = token_response.get("error", "server_error")
                description = token_response.get("error_description", "Unknown error")

                # Map to appropriate HTTP status codes
                if error in ["invalid_client"]:
                    status = 401
                    # RFC 6749 Section 5.2: MUST include WWW-Authenticate for 401
                    base_url = f"{self.config.proto}{self.config.fqdn}"
                    self.response.headers["WWW-Authenticate"] = (
                        f'Basic realm="ActingWeb OAuth2", '
                        f'error="invalid_client", '
                        f'error_description="Invalid client credentials", '
                        f'authorization_uri="{base_url}/oauth/authorize"'
                    )
                elif error in [
                    "invalid_request",
                    "invalid_grant",
                    "unsupported_grant_type",
                ]:
                    status = 400
                else:
                    status = 500

                return self.error_response(status, f"{error}: {description}")

            logger.debug(
                f"Token request successful for client {params.get('client_id', 'unknown')}"
            )
            return token_response

        except Exception as e:
            logger.error(f"Error in token request: {e}")
            return self.error_response(500, "Internal server error")

    def _handle_authorization_server_discovery(self) -> dict[str, Any]:
        """
        Handle OAuth2 Authorization Server Discovery (RFC 8414).

        Returns:
            ActingWeb OAuth2 authorization server metadata
        """
        # Set CORS headers for discovery endpoint
        self.response.headers["Access-Control-Allow-Origin"] = "*"
        self.response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        self.response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, mcp-protocol-version"
        )

        return self.oauth2_server.handle_discovery_request()

    def _handle_oauth_callback(self) -> dict[str, Any]:
        """
        Handle OAuth2 callback from Google.

        This completes the MCP client authorization flow.

        Returns:
            Redirect response to MCP client
        """
        try:
            # Get callback parameters
            params = {
                "code": self.request.get("code") or "",
                "state": self.request.get("state") or "",
                "error": self.request.get("error") or "",
                "error_description": self.request.get("error_description") or "",
            }

            # Handle using OAuth2 server
            callback_response = self.oauth2_server.handle_oauth_callback(params)

            if callback_response.get("action") == "redirect":
                # Redirect back to MCP client
                redirect_url = callback_response.get("url")
                if redirect_url:
                    self.response.set_status(302, "Found")
                    self.response.set_redirect(redirect_url)
                    return {"status": "redirect", "location": redirect_url}
                else:
                    return self.error_response(
                        500, "Failed to create callback redirect URL"
                    )
            else:
                # Error response
                error = callback_response.get("error", "server_error")
                description = callback_response.get(
                    "error_description", "OAuth2 callback failed"
                )
                return self.error_response(400, f"{error}: {description}")

        except Exception as e:
            logger.error(f"Error in OAuth2 callback: {e}")
            return self.error_response(500, "Internal server error")

    def _render_authorization_form(
        self, form_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Render authorization form (same UX as GET /).

        Args:
            form_data: Form data from OAuth2 server

        Returns:
            Form response or None if template values were set
        """
        # For OAuth2 authorization forms, always try to render HTML template if UI or MCP is enabled
        # The form is meant for human interaction, so default to HTML unless explicitly requesting JSON
        # Note: MCP OAuth2 flow needs the form even when config.ui is False (web UI disabled)
        ui_or_mcp_enabled = self.config.ui or getattr(self.config, "mcp", False)
        is_browser_request = (
            ui_or_mcp_enabled
            and self.request
            and self.request.headers
            and self.request.headers.get("Accept", "").find("application/json") == -1
        )

        if is_browser_request:
            # Get available trust types for selection
            available_trust_types = []
            requested_scope = form_data.get("scope", "")
            client_id = form_data.get("client_id", "")

            # Get OAuth2 trust type configuration from app (if configured)
            # The application decides which trust types are available for MCP OAuth2
            oauth2_config = getattr(self.config, "_oauth2_trust_types", None)

            if oauth2_config is None:
                logger.debug(
                    "No OAuth2 trust type configuration - will use all registry types"
                )
                # No filtering - show all trust types from registry
                oauth2_config = {"allowed": None, "default": None}

            # Get trust types from the registry (configured by the application)
            trust_types = []
            try:
                from actingweb.trust_type_registry import get_registry

                registry = get_registry(self.config)
                trust_types = registry.list_types()
            except RuntimeError:
                logger.warning(
                    "Trust type registry not initialized - no trust types available. "
                    "Application must configure trust types for MCP OAuth2."
                )
                trust_types = []
            except Exception as e:
                logger.warning(f"Error accessing trust type registry: {e}")
                trust_types = []

            # Get developer-configured OAuth2 trust type restrictions (already initialized above)
            allowed_by_developer = (
                oauth2_config.get("allowed") if oauth2_config else None
            )

            logger.debug(
                f"Trust type filtering: oauth2_config={oauth2_config}, allowed_by_developer={allowed_by_developer}"
            )
            logger.debug(
                f"Available trust types from registry: {[tt.name for tt in trust_types]}"
            )

            # Filter trust types based on multiple criteria
            for trust_type in trust_types:
                should_include = True

                # Option 1: Filter by developer configuration (highest priority)
                if allowed_by_developer is not None:
                    if trust_type.name not in allowed_by_developer:
                        should_include = False

                # Option 2: Filter by OAuth2 scope if specified
                # Skip scope filtering if no scope is requested (show all allowed types)
                if requested_scope and trust_type.oauth_scope and should_include:
                    # Check if requested scope matches or includes this trust type's scope
                    requested_scopes = set(requested_scope.split())
                    trust_type_scopes = set(trust_type.oauth_scope.split())

                    # More flexible scope matching for compatibility
                    scope_matches = False
                    if trust_type_scopes & requested_scopes:  # Direct intersection
                        scope_matches = True
                    else:
                        # Check for partial matches (e.g., "mcp" matches "actingweb.mcp_client")
                        for req_scope in requested_scopes:
                            for tt_scope in trust_type_scopes:
                                if req_scope in tt_scope or tt_scope in req_scope:
                                    scope_matches = True
                                    break
                            if scope_matches:
                                break

                    if not scope_matches:
                        should_include = False

                # Option 3: Check client-specific trust type restrictions
                # Developers can register clients with allowed_trust_types
                if client_id and should_include:
                    try:
                        client_data = (
                            self.oauth2_server.client_registry.validate_client(
                                client_id
                            )
                        )
                        if client_data and "allowed_trust_types" in client_data:
                            allowed_types = client_data["allowed_trust_types"]
                            if (
                                isinstance(allowed_types, list)
                                and trust_type.name not in allowed_types
                            ):
                                should_include = False
                    except Exception:
                        pass  # Continue if client lookup fails

                if should_include:
                    available_trust_types.append(
                        {
                            "name": trust_type.name,
                            "display_name": trust_type.display_name,
                            "description": trust_type.description,
                            "oauth_scope": trust_type.oauth_scope or "",
                        }
                    )
                    logger.debug(f"Trust type {trust_type.name} included")
                else:
                    logger.debug(f"Trust type {trust_type.name} excluded")

            # Log available trust types (no hardcoded fallbacks - app must configure)
            logger.debug(
                f"Final available_trust_types count: {len(available_trust_types)}"
            )
            if not available_trust_types:
                logger.warning(
                    "No trust types available for MCP OAuth2. "
                    "Application must register trust types in the trust type registry."
                )
                # Don't provide hardcoded fallbacks - app must configure trust types

            # Determine default trust type from app configuration (no hardcoded default)
            default_trust_type = None
            if oauth2_config:
                configured_default = oauth2_config.get("default")
                if configured_default and any(
                    tt["name"] == configured_default for tt in available_trust_types
                ):
                    default_trust_type = configured_default

            # If no default configured but trust types available, use first one
            if default_trust_type is None and available_trust_types:
                default_trust_type = available_trust_types[0]["name"]

            # Generate OAuth provider URLs (like factory handler does)
            oauth_enabled = False
            oauth_providers = []

            # Check if OAuth is configured (same check as factory handler)
            if self.config.oauth and self.config.oauth.get("client_id"):
                try:
                    from ..oauth2 import (
                        create_github_authenticator,
                        create_google_authenticator,
                    )

                    # Determine which provider(s) to support based on configuration
                    oauth2_provider = getattr(self.config, "oauth2_provider", "google")

                    # Build MCP context to embed in state using OAuth2Server's state manager
                    from ..oauth2_server.oauth2_server import (
                        get_actingweb_oauth2_server,
                    )

                    oauth2_server = get_actingweb_oauth2_server(self.config)
                    mcp_context = {
                        "client_id": form_data.get("client_id", ""),
                        "redirect_uri": form_data.get("redirect_uri", ""),
                        "original_state": form_data.get(
                            "state", ""
                        ),  # Original MCP state from ChatGPT
                        "trust_type": default_trust_type,
                        "flow_type": "mcp_oauth2",  # Required to identify this as MCP OAuth2 flow
                    }

                    # Create encrypted state with MCP context embedded
                    encrypted_state = oauth2_server.state_manager.create_state(
                        mcp_context
                    )

                    if oauth2_provider == "google":
                        google_auth = create_google_authenticator(self.config)
                        if google_auth.is_enabled():
                            # Pass encrypted state and trust_type as separate parameters
                            auth_url = google_auth.create_authorization_url(
                                state=encrypted_state,
                                trust_type=default_trust_type or "",
                            )
                            oauth_providers.append(
                                {
                                    "name": "google",
                                    "display_name": "Google",
                                    "url": auth_url,
                                }
                            )
                            oauth_enabled = True
                            logger.debug(
                                "Generated Google OAuth authorization URL for MCP client with encrypted state"
                            )

                    elif oauth2_provider == "github":
                        github_auth = create_github_authenticator(self.config)
                        if github_auth.is_enabled():
                            auth_url = github_auth.create_authorization_url(
                                state=encrypted_state,
                                trust_type=default_trust_type or "",
                            )
                            oauth_providers.append(
                                {
                                    "name": "github",
                                    "display_name": "GitHub",
                                    "url": auth_url,
                                }
                            )
                            oauth_enabled = True
                            logger.debug(
                                "Generated GitHub OAuth authorization URL for MCP client with encrypted state"
                            )

                except Exception as e:
                    logger.warning(
                        f"Failed to generate OAuth URLs for authorization form: {e}"
                    )

            # Set template values for HTML rendering (like factory handler does)
            self.response.template_values = {
                "client_id": form_data.get("client_id", ""),
                "redirect_uri": form_data.get("redirect_uri", ""),
                "state": form_data.get("state", ""),
                "response_type": form_data.get("response_type", "code"),  # OAuth2 PKCE
                "scope": form_data.get("scope", ""),  # OAuth2 scope
                "code_challenge": form_data.get("code_challenge", ""),  # OAuth2 PKCE
                "code_challenge_method": form_data.get(
                    "code_challenge_method", ""
                ),  # OAuth2 PKCE
                "client_name": form_data.get("client_name", "MCP Client"),
                "form_action": "/oauth/authorize",
                "form_method": "POST",
                "message": f"Authorize {form_data.get('client_name', 'MCP Client')} to access your ActingWeb data",
                "trust_types": available_trust_types,
                "default_trust_type": default_trust_type,
                "oauth2_trust_control_enabled": True,  # Indicate that trust type control is available
                "oauth_enabled": oauth_enabled,  # Enable OAuth buttons
                "oauth_providers": oauth_providers,  # OAuth provider list
            }
            return None  # Template will be rendered by framework

        # For API requests, return JSON structure
        return {
            "action": "show_form",
            "form_data": {
                "client_id": form_data.get("client_id", ""),
                "redirect_uri": form_data.get("redirect_uri", ""),
                "state": form_data.get("state", ""),
                "client_name": form_data.get("client_name", "MCP Client"),
                "form_action": "/oauth/authorize",
                "form_method": "POST",
            },
            "template": "oauth_authorization_form",  # Template to render
            "message": f"Authorize {form_data.get('client_name', 'MCP Client')} to access your ActingWeb data",
        }

    def _handle_protected_resource_discovery(self) -> dict[str, Any]:
        """
        Handle OAuth2 Protected Resource Discovery (RFC 8705).

        Returns:
            Protected resource metadata
        """
        # Set CORS headers for discovery endpoint
        self.response.headers["Access-Control-Allow-Origin"] = "*"
        self.response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        self.response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, mcp-protocol-version"
        )

        base_url = f"{self.config.proto}{self.config.fqdn}"

        return {
            "resource": f"{base_url}/mcp",
            "authorization_servers": [base_url],
            "scopes_supported": ["mcp"],
            "bearer_methods_supported": ["header"],
            "resource_documentation": f"{base_url}/mcp/info",
            "resource_policy_uri": f"{base_url}",
        }

    def _handle_protected_resource_mcp_discovery(self) -> dict[str, Any]:
        """
        Handle OAuth2 Protected Resource Discovery for MCP-specific metadata.

        Returns:
            MCP-specific protected resource metadata
        """
        # Set CORS headers for discovery endpoint
        self.response.headers["Access-Control-Allow-Origin"] = "*"
        self.response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        self.response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, mcp-protocol-version"
        )

        base_url = f"{self.config.proto}{self.config.fqdn}"

        return {
            "resource": f"{base_url}/mcp",
            "authorization_servers": [base_url],
            "scopes_supported": ["mcp"],
            "bearer_methods_supported": ["header"],
            "resource_documentation": f"{base_url}/mcp/info",
            "resource_policy_uri": f"{base_url}",
            "mcp_version": LATEST_PROTOCOL_VERSION,
            "supported_protocol_versions": SUPPORTED_PROTOCOL_VERSIONS,
            "capabilities": {
                "tools": True,
                "prompts": True,
                "resources": False,
                "roots": False,
            },
        }

    def _handle_logout_request(self, method: str = "GET") -> dict[str, Any]:
        """
        Handle OAuth2 logout request.

        This endpoint revokes the current access token and clears session cookies.
        Works for both GET and POST requests.

        Args:
            method: HTTP method (GET or POST)

        Returns:
            Response dict with success and redirect information
        """
        try:
            logger.info(f"Logout request started: method={method}")

            # Extract token from Authorization header or cookie
            auth_header = None
            if self.request.headers:
                auth_header = self.request.headers.get(
                    "Authorization"
                ) or self.request.headers.get("authorization")
            token = None

            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]  # Remove "Bearer " prefix
                logger.debug("Found token in Authorization header")
            else:
                # Try to get token from cookies (for web sessions)
                token = (
                    self.request.cookies.get("oauth_token")
                    if self.request.cookies
                    else None
                )
                if token:
                    logger.debug("Found token in cookies")
                else:
                    logger.debug("No token found in cookies or Authorization header")

            # Handle Google OAuth2 token logout (web UI authentication)
            try:
                if token:
                    response = self._handle_google_token_logout(token)
                else:
                    # No token provided - just clear cookies
                    response = {
                        "action": "success",
                        "message": "Successfully logged out",
                        "clear_cookies": [
                            "oauth_token",
                            "oauth_refresh_token",
                            "session_id",
                        ],
                        "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
                    }

                # Clear MCP token cache if the token was cached there
                if token and response.get("action") == "success":
                    try:
                        from .mcp import MCPHandler

                        MCPHandler.clear_token_from_cache(token)
                    except Exception as cache_error:
                        logger.warning(
                            f"Failed to clear MCP token cache: {cache_error}"
                        )
                        # Non-critical - token will expire from cache naturally
            except Exception as logout_error:
                logger.error(f"Google token logout error: {logout_error}")
                import traceback

                logger.error(f"Full Google logout error: {traceback.format_exc()}")
                # Continue with basic logout even if Google revocation fails
                response = {
                    "action": "success",
                    "message": "Logged out (token revocation failed)",
                    "clear_cookies": [
                        "oauth_token",
                        "oauth_refresh_token",
                        "session_id",
                    ],
                    "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
                }

            if response["action"] == "success":
                # Clear cookies
                self.response.set_status(200)

                # Clear OAuth cookies by setting them to expire immediately
                for cookie_name in response.get("clear_cookies", []):
                    try:
                        # Clear both secure and non-secure versions of cookies
                        self.response.set_cookie(
                            cookie_name, "", max_age=-1, path="/", secure=False
                        )
                        self.response.set_cookie(
                            cookie_name, "", max_age=-1, path="/", secure=True
                        )
                    except Exception as cookie_error:
                        logger.warning(
                            f"Failed to clear cookie {cookie_name}: {cookie_error}"
                        )

                # Return JSON response
                return {
                    "success": True,
                    "message": response["message"],
                    "redirect_url": response["redirect_url"],
                    "method": method,
                    "cleared_cookies": response.get("clear_cookies", []),
                }
            else:
                logger.error(f"Logout failed with response: {response}")
                return self.error_response(500, "Logout failed")

        except Exception as e:
            logger.error(f"Logout request error: {e}")
            import traceback

            logger.error(f"Full logout handler traceback: {traceback.format_exc()}")
            return self.error_response(500, "Internal server error during logout")

    def _handle_google_token_logout(self, google_token: str) -> dict[str, Any]:
        """
        Handle logout for Google OAuth2 tokens.

        Google tokens need to be revoked directly with Google's revocation endpoint
        to ensure they are immediately invalidated.

        Args:
            google_token: Google OAuth2 access token

        Returns:
            Response dict indicating logout success/failure
        """
        try:
            # Revoke the token with Google
            revocation_successful = False
            try:
                from ..oauth2 import OAuth2Authenticator

                authenticator = OAuth2Authenticator(self.config)
                revocation_successful = authenticator.revoke_token(google_token)
            except Exception as revoke_error:
                logger.error(f"Error during Google token revocation: {revoke_error}")
                # Continue with logout even if Google revocation fails

            # Always return success and clear cookies, even if Google revocation failed
            # The user should be logged out from the local session regardless
            return {
                "action": "success",
                "message": "Successfully logged out"
                + (
                    "" if revocation_successful else " (Google token revocation failed)"
                ),
                "clear_cookies": ["oauth_token", "oauth_refresh_token", "session_id"],
                "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
            }

        except Exception as e:
            logger.error(f"Error handling Google token logout: {e}")
            import traceback

            logger.error(
                f"Google token logout error traceback: {traceback.format_exc()}"
            )

            # Still return success to clear cookies and log user out locally
            return {
                "action": "success",
                "message": "Logged out (with errors)",
                "clear_cookies": ["oauth_token", "oauth_refresh_token", "session_id"],
                "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
            }

    def error_response(self, status_code: int, message: str) -> dict[str, Any]:
        """Create OAuth2 error response."""
        self.response.set_status(status_code)

        # OAuth2 error format
        if status_code == 400:
            return {"error": "invalid_request", "error_description": message}
        elif status_code == 401:
            return {"error": "invalid_client", "error_description": message}
        else:
            return {"error": "server_error", "error_description": message}
