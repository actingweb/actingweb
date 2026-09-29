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

# MCP protocol version constants (single source of truth)
from ..log_summary import summarize_payload
from ..mcp.protocol import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from .base_handler import BaseHandler

if TYPE_CHECKING:
    from .. import aw_web_request
    from .. import config as config_class
    from ..interface.hooks import HookRegistry

# TrustTypeRegistry imported locally where needed

logger = logging.getLogger(__name__)

# The cookies a logout clears, as ``(name, path)``. ``access_token`` and
# ``oauth_token`` are the SPA cookie-mode pair, ``refresh_token`` is set at
# ``/`` by cookie mode and at ``/oauth/spa/token`` by the hybrid callback, and
# ``session_id`` is the www session. (``oauth_refresh_token`` was named here
# before 3.15.1 but nothing ever set it.)
_LOGOUT_COOKIES: tuple[tuple[str, str], ...] = (
    ("access_token", "/"),
    ("oauth_token", "/"),
    ("refresh_token", "/"),
    ("refresh_token", "/oauth/spa/token"),
    ("session_id", "/"),
)


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
                # RFC 7591 §3.2.2
                return self._token_error(400, "invalid_client_metadata", str(e))
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
                    # PKCE (RFC 7636). AWWebObj.get returns "" for an absent
                    # parameter; absent is None so the server can tell.
                    "code_challenge": self.request.get("code_challenge") or None,
                    "code_challenge_method": (
                        self.request.get("code_challenge_method") or None
                    ),
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
                    # PKCE, carried back by the form's hidden inputs
                    "code_challenge": form_data.get("code_challenge", [""])[0] or None,
                    "code_challenge_method": form_data.get(
                        "code_challenge_method", [""]
                    )[0]
                    or None,
                }

            # Debug logging for MCP OAuth2 flow
            logger.debug(
                f"OAuth2 authorization {method} request with params: "
                f"{summarize_payload(params)}"
            )

            # Handle using OAuth2 server
            server_response = self.oauth2_server.handle_authorization_request(
                params, method
            )

            logger.debug(
                f"OAuth2 server response: action={server_response.get('action')} "
                f"{summarize_payload(server_response)}"
            )

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

            # Debug: log received form data keys only (never log body content which contains secrets)
            logger.debug(f"Token request form data keys: {list(form_data.keys())}")

            # Extract parameters (parse_qs returns lists). An absent or empty
            # secret is None, never "": the grants treat None as "no secret".
            params: dict[str, Any] = {
                "grant_type": form_data.get("grant_type", [""])[0],
                "code": form_data.get("code", [""])[0],
                "refresh_token": form_data.get("refresh_token", [""])[0],
                "redirect_uri": form_data.get("redirect_uri", [""])[0],
                "client_id": form_data.get("client_id", [""])[0],
                "client_secret": form_data.get("client_secret", [None])[0] or None,
                "code_verifier": form_data.get("code_verifier", [""])[0],
            }

            # client_secret_basic: parse the Authorization header whenever it
            # is present, not only when the body lacks client_id. A body
            # client_id or client_secret that disagrees with the header's is
            # refused (RFC 6749 §2.3.1: one method per request); identical
            # duplicates are tolerated.
            headers = self.request.headers or {}
            auth_header = headers.get("Authorization", "") or headers.get(
                "authorization", ""
            )
            if auth_header.startswith("Basic "):
                header_client_id: str | None = None
                header_secret: str | None = None
                try:
                    import base64
                    from urllib.parse import unquote_plus

                    decoded_creds = base64.b64decode(auth_header[6:]).decode("utf-8")
                    if ":" in decoded_creds:
                        raw_id, raw_secret = decoded_creds.split(":", 1)
                        # RFC 6749 §2.3.1: form-urlencoded before base64
                        header_client_id = unquote_plus(raw_id)
                        header_secret = unquote_plus(raw_secret) or None
                except Exception as e:
                    logger.warning(f"Failed to parse Authorization header: {e}")
                if header_client_id:
                    if params["client_id"] and params["client_id"] != header_client_id:
                        return self._token_error(
                            400,
                            "invalid_request",
                            "client_id in the body does not match the "
                            "Authorization header",
                        )
                    if (
                        params["client_secret"]
                        and header_secret
                        and params["client_secret"] != header_secret
                    ):
                        return self._token_error(
                            400,
                            "invalid_request",
                            "client_secret in the body does not match the "
                            "Authorization header",
                        )
                    params["client_id"] = header_client_id
                    if not params["client_secret"]:
                        params["client_secret"] = header_secret
                    logger.debug(
                        f"Read client credentials from Authorization header: "
                        f"{header_client_id}"
                    )

            # Expired MCP token rows are purged at most once per interval per
            # process (PostgreSQL; DynamoDB relies on native TTL). Before the
            # grant, not after: a slow first purge (a backlog, a cold start)
            # must never hold back a response whose refresh token was already
            # consumed, or the client's retry would read as theft. Never let
            # housekeeping fail the grant.
            try:
                self.oauth2_server.token_manager.maybe_purge_expired_tokens()
            except Exception as e:
                logger.debug(f"MCP token purge skipped: {e}")

            # Handle using OAuth2 server
            token_response = self.oauth2_server.handle_token_request(params)

            if "error" in token_response:
                error = str(token_response.get("error", "server_error"))
                description = str(
                    token_response.get("error_description", "Unknown error")
                )

                # Map to appropriate HTTP status codes; the body keeps the
                # server's own error code (RFC 6749 §5.2).
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
                    "unauthorized_client",
                    "invalid_scope",
                ]:
                    status = 400
                else:
                    status = 500
                    error = "server_error"

                return self._token_error(status, error, description)

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

            # Check if OAuth is configured and generate provider URLs
            try:
                from ..oauth2 import (
                    create_oauth2_authenticator,
                    get_provider_display_name,
                )
                from ..oauth2_server.oauth2_server import (
                    get_actingweb_oauth2_server,
                )

                providers_cfg = getattr(self.config, "oauth_providers", {})
                # Determine list of provider names to iterate
                provider_names: list[str] = []
                if providers_cfg:
                    provider_names = list(providers_cfg.keys())
                elif self.config.oauth and self.config.oauth.get("client_id"):
                    # Single-provider backward-compat
                    provider_names = [getattr(self.config, "oauth2_provider", "google")]

                if provider_names:
                    oauth2_server = get_actingweb_oauth2_server(self.config)

                    for prov_name in provider_names:
                        # Native-only variants (mobile / native id_token flows)
                        # are not offered in the LLM-triggered web form.
                        if prov_name.endswith("-mobile") or prov_name.endswith(
                            "-native"
                        ):
                            continue

                        # Each provider gets its own encrypted state with provider embedded
                        mcp_context = {
                            "client_id": form_data.get("client_id", ""),
                            "redirect_uri": form_data.get("redirect_uri", ""),
                            "original_state": form_data.get("state", ""),
                            "trust_type": default_trust_type,
                            "flow_type": "mcp_oauth2",
                            "provider": prov_name,
                            # PKCE binds the code the callback issues
                            "code_challenge": form_data.get("code_challenge"),
                            "code_challenge_method": form_data.get(
                                "code_challenge_method"
                            ),
                        }
                        encrypted_state = oauth2_server.state_manager.create_state(
                            mcp_context
                        )

                        auth = create_oauth2_authenticator(self.config, prov_name)
                        if not auth.is_enabled():
                            continue

                        # Apple form_posts its callback; wrap the encrypted MCP
                        # state in a server-side nonce so /oauth/callback/apple can
                        # consume it and dispatch back to the MCP completion path.
                        is_apple = prov_name == "apple" or prov_name.startswith(
                            "apple-"
                        )
                        if is_apple:
                            from ..oauth_state_store import StateNonceStore

                            state_param = StateNonceStore(self.config).create(
                                {"provider": prov_name, "mcp_state": encrypted_state}
                            )
                        else:
                            state_param = encrypted_state

                        auth_url = auth.create_authorization_url(
                            state=state_param,
                            trust_type=default_trust_type or "",
                        )
                        oauth_providers.append(
                            {
                                "name": prov_name,
                                "display_name": get_provider_display_name(prov_name),
                                "url": auth_url,
                            }
                        )
                        oauth_enabled = True
                        logger.debug(
                            f"Generated {prov_name} OAuth authorization URL for MCP client"
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
                "code_challenge": form_data.get("code_challenge") or "",  # PKCE
                "code_challenge_method": form_data.get("code_challenge_method")
                or "",  # PKCE
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
                "code_challenge": form_data.get("code_challenge") or "",
                "code_challenge_method": form_data.get("code_challenge_method") or "",
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
            "scopes_supported": ["mcp", "offline_access"],
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
            "scopes_supported": ["mcp", "offline_access"],
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

        This endpoint revokes the presented session and clears its cookies.
        Works for both GET and POST requests. A session token ends its whole
        refresh-token chain (access token, refresh token and rotated
        successors); an MCP token ends its MCP chain.

        The chain can also be named by a refresh token, which matters because
        an access token expires after an hour and its expired row cannot be
        read: POST a JSON body ``{"refresh_token": "..."}`` (a form field of
        the same name is accepted), or send the ``refresh_token`` cookie on any
        method. With no access token, the refresh token alone drives the
        revoke; with both, each is revoked, so two different chains both end.

        A token store fault answers 503 with ``Retry-After`` and clears no
        cookie: the presented token stays valid and is the retry handle.

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

            refresh_tokens = self._logout_refresh_tokens(method)

            # Handle OAuth2 token logout (web UI authentication)
            try:
                if token or refresh_tokens:
                    response = self._handle_provider_token_logout(
                        token,
                        refresh_tokens,
                        # A GET can be forced cross-site (SameSite=Lax cookies),
                        # so only a POST also clears the actor-wide provider
                        # token; a GET still ends the session's chain.
                        clear_provider_token=method == "POST",
                    )
                else:
                    # No token provided - just clear cookies
                    response = {
                        "action": "success",
                        "message": "Successfully logged out",
                        "clear_cookies": list(_LOGOUT_COOKIES),
                        "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
                    }

                # Clear MCP token cache if the token was cached there. On a
                # retry too: the store fault may have hit before revoke_token
                # could evict, and a cached token must not outlive a logout.
                if token and response.get("action") in ("success", "retry"):
                    try:
                        from .mcp import MCPHandler

                        MCPHandler.clear_token_from_cache(token)
                    except Exception as cache_error:
                        logger.warning(
                            f"Failed to clear MCP token cache: {cache_error}"
                        )
                        # Non-critical - token will expire from cache naturally
            except Exception as logout_error:
                logger.error(f"Token logout error: {logout_error}")
                import traceback

                logger.error(f"Full logout error: {traceback.format_exc()}")
                # Fail closed: an unexpected error means the revoke is not
                # confirmed, so a 200 with the cookies cleared would report a
                # logout that did not happen and strand the client without its
                # retry handle (RFC 7009 §2.2.1: on 5xx assume the token
                # still exists). Answer 500 and leave the cookies alone.
                return self.error_response(500, "Internal server error during logout")

            if response["action"] == "retry":
                # An MCP token whose revocation hit a store fault: it is kept
                # so presenting it again retries. A 200 would tell the client
                # it is done, so answer 503 with Retry-After and clear no
                # cookies (the client needs its token for the retry).
                self.response.headers["Retry-After"] = "5"
                self.response.set_status(503, "Service Unavailable")
                return {
                    "success": False,
                    "error": "temporarily_unavailable",
                    "message": response["message"],
                    "method": method,
                }

            if response["action"] == "success":
                # Clear cookies
                self.response.set_status(200)

                # Clear OAuth cookies by setting them to expire immediately.
                # An entry is ``(name, path)``; a bare name means path ``/``.
                to_clear = [
                    (entry, "/") if isinstance(entry, str) else entry
                    for entry in response.get("clear_cookies", [])
                ]
                for cookie_name, cookie_path in to_clear:
                    try:
                        # Clear both secure and non-secure versions of cookies
                        self.response.set_cookie(
                            cookie_name, "", max_age=-1, path=cookie_path, secure=False
                        )
                        self.response.set_cookie(
                            cookie_name, "", max_age=-1, path=cookie_path, secure=True
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
                    "cleared_cookies": list(
                        dict.fromkeys(name for name, _path in to_clear)
                    ),
                }
            else:
                logger.error(f"Logout failed with response: {response}")
                return self.error_response(500, "Logout failed")

        except Exception as e:
            logger.error(f"Logout request error: {e}")
            import traceback

            logger.error(f"Full logout handler traceback: {traceback.format_exc()}")
            return self.error_response(500, "Internal server error during logout")

    def _logout_refresh_tokens(self, method: str) -> list[str]:
        """The refresh tokens a logout request names, without duplicates.

        POST: the JSON body's ``refresh_token`` (only when the content type is
        JSON) or a ``refresh_token`` field of a form-encoded body (never the
        query string). Any method: the
        ``refresh_token`` cookie. An absent, empty, non-JSON or otherwise
        unreadable body is ignored, never a 400: old clients post no body, and
        logout must still proceed.
        """
        from urllib.parse import parse_qs

        found: list[str] = []

        def add(value: object) -> None:
            if isinstance(value, str) and value and value not in found:
                found.append(value)

        if method == "POST":
            headers = self.request.headers or {}
            content_type = str(
                headers.get("Content-Type") or headers.get("content-type") or ""
            )
            body = self.request.body
            lowered = content_type.lower()
            if isinstance(body, bytes):
                text = body.decode("utf-8", "ignore")
            else:
                text = str(body) if body else ""
            if "json" in lowered and text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        add(parsed.get("refresh_token"))
                except ValueError:
                    logger.debug("Logout body is not valid JSON; ignoring it")
            elif "x-www-form-urlencoded" in lowered and text:
                # The form *body* only, never the query string: a credential
                # in a URL lands in access logs and referrers.
                for value in parse_qs(text).get("refresh_token", []):
                    add(value)
        if self.request.cookies:
            add(self.request.cookies.get("refresh_token"))
        return found

    def _handle_provider_token_logout(
        self,
        token: str | None,
        refresh_tokens: list[str] | None = None,
        *,
        clear_provider_token: bool = True,
    ) -> dict[str, Any]:
        """
        Route a logout to the store that holds the presented token.

        An MCP access token (the token manager's prefix; SPA session tokens
        never carry it) is revoked in the MCP token store with every token of
        its chain. Anything else is an ActingWeb session token, or a refresh
        token with no access token, and goes to
        :meth:`_handle_session_token_logout`.

        Args:
            token: ActingWeb session or MCP access token, if presented
            refresh_tokens: Refresh tokens presented in the body or cookie
            clear_provider_token: Whether a session logout also clears the
                actor's stored provider token (False for a GET)

        Returns:
            Response dict: ``action`` is ``success`` or ``retry``
        """
        if token and token.startswith(self.oauth2_server.token_manager.token_prefix):
            return self._handle_mcp_token_logout(token)
        return self._handle_session_token_logout(
            token, refresh_tokens or [], clear_provider_token=clear_provider_token
        )

    def _handle_session_token_logout(
        self,
        token: str | None,
        refresh_tokens: list[str],
        *,
        clear_provider_token: bool = True,
    ) -> dict[str, Any]:
        """
        End the session an ActingWeb session token or refresh token belongs to.

        Each presented token goes through
        ``OAuth2SessionManager.revoke_session``: a token with a chain ends the
        whole chain, a chain-less one (the www cookie login) only itself. The
        access token is revoked first; a refresh token from the same chain then
        finds nothing left to read, one GetItem. The stored provider token is
        cleared for the actor after a confirmed revoke, which affects every
        device of the actor, not only this chain. A GET (which a cross-site
        navigation can force) ends the chain but leaves the provider token
        alone (``clear_provider_token=False``). We do NOT call the
        provider's revocation endpoint: logout is not an account disconnect
        (see ``_clear_provider_token_for_actor``).

        A token store fault is caught here and answered ``retry`` (503), never
        swallowed into "logged out", because the session is still valid and the
        client must present its token again. It is converted before the
        caller's catch-all, which answers any other unexpected error with a
        fail-closed 500 (no cookie cleared).

        Args:
            token: ActingWeb session token, if presented
            refresh_tokens: Refresh tokens presented in the body or cookie

        Returns:
            ``{"action": "retry", ...}`` on a store fault, else ``success``
            with the cookies to clear.
        """
        from ..oauth2_server.token_manager import TokenStoreUnavailable
        from ..oauth_session import get_oauth2_session_manager

        session_manager = get_oauth2_session_manager(self.config)
        presented: list[tuple[str, str]] = []
        if token:
            presented.append((token, "access_token"))
        presented.extend((rt, "refresh_token") for rt in refresh_tokens)

        actor_ids: list[str] = []
        try:
            for value, hint in presented:
                row = session_manager.revoke_session(value, token_type_hint=hint)
                actor_id = row.get("actor_id") if row else None
                if actor_id and actor_id not in actor_ids:
                    actor_ids.append(actor_id)
        except TokenStoreUnavailable as e:
            logger.error(f"Session token revocation on logout failed: {e}")
            return {
                "action": "retry",
                "message": "Token store temporarily unavailable; retry the logout",
            }

        # After the confirmed revoke, never before: a fault leaves the provider
        # token in place for the retry.
        if clear_provider_token:
            for actor_id in actor_ids:
                self._clear_provider_token_for_actor(actor_id)

        return {
            "action": "success",
            "message": "Successfully logged out",
            "clear_cookies": list(_LOGOUT_COOKIES),
            "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
        }

    def _handle_mcp_token_logout(self, token: str) -> dict[str, Any]:
        """Revoke an MCP access token and its refresh-token chain on logout.

        On success the endpoint answers as it always has (success, cookies
        cleared). On a token store fault the action is ``retry``, which
        :meth:`_handle_logout_request` answers with 503 and ``Retry-After``,
        so the client presents the token again. What the retry finds depends
        on where the fault hit (see ``ActingWebTokenManager.revoke_token``):
        a chain that could not be revoked is revoked then; a token whose row
        delete was unconfirmed is already dead and the retry confirms it.
        """
        from ..oauth2_server.token_manager import TokenStoreUnavailable

        try:
            if not self.oauth2_server.token_manager.revoke_token(token):
                logger.debug("Logout with an unknown or expired MCP token")
        except TokenStoreUnavailable as e:
            logger.error(f"MCP token revocation on logout failed: {e}")
            return {
                "action": "retry",
                "message": "Token store temporarily unavailable; retry the logout",
            }
        return {
            "action": "success",
            "message": "Successfully logged out",
            "clear_cookies": list(_LOGOUT_COOKIES),
            "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
        }

    def _clear_provider_token_for_actor(self, actor_id: str) -> None:
        """
        Clear the stored OAuth provider token from the actor store on logout.

        Logout ends the local ActingWeb session only; it must NOT call the
        identity provider's token-revocation endpoint. For Apple in particular,
        hitting ``/auth/revoke`` emails the user ("… has revoked access to sign
        in with your Apple account") and severs the Sign in with Apple grant —
        the next login re-prompts for name/email consent and the stored refresh
        token is invalidated. Provider-side revocation belongs to an explicit
        account-disconnect / delete flow, not to logout.

        Nulling the stored token locally is sufficient to stop the backend from
        making further API calls on the user's behalf. Best-effort: failures are
        logged but never block logout.
        """
        try:
            from .. import actor as actor_module

            actor = actor_module.Actor(actor_id=actor_id, config=self.config)
            if not actor.id or not actor.store:
                return

            if actor.store.oauth_token:
                # Clear all credential fields written on login (oauth_session.py).
                # oauth_provider is left intact: it is identity metadata, not a
                # credential, and a subsequent login may branch on it.
                actor.store.oauth_token = None
                actor.store.oauth_token_expiry = None
                actor.store.oauth_token_timestamp = None
                logger.info(
                    f"Cleared stored provider token for actor {actor_id} on logout"
                )
            else:
                logger.debug(f"No provider token to clear for actor {actor_id}")
        except Exception as e:
            logger.debug(f"Clearing provider token for actor {actor_id}: {e}")

    def _token_error(
        self, status_code: int, error: str, description: str
    ) -> dict[str, Any]:
        """OAuth2 error body with an explicit error code (RFC 6749 §5.2,
        RFC 7591 §3.2.2), unlike :meth:`error_response`, which derives the code
        from the status."""
        self.response.set_status(status_code)
        return {"error": error, "error_description": description}

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
