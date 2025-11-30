"""
SPA (Single Page Application) OAuth2 handler for ActingWeb.

This handler provides JSON-only OAuth2 endpoints optimized for SPAs.

Unified endpoints (exposed at /oauth/*):
- /oauth/config - Get OAuth configuration and available providers
- /oauth/callback - OAuth callback (auto-detects SPA mode via state param)
- /oauth/revoke - Token revocation
- /oauth/session - Session status check
- /oauth/logout - Logout and clear tokens

SPA-specific endpoints (different purpose than MCP OAuth2 server endpoints):
- /oauth/spa/authorize - Initiate external OAuth flow (ActingWeb as OAuth client)
- /oauth/spa/token - Token refresh with rotation for external provider tokens

Note: /oauth/authorize and /oauth/token are for MCP OAuth2 (ActingWeb as OAuth server).
The /oauth/spa/* versions are for external OAuth (ActingWeb as OAuth client to Google/GitHub).

These endpoints always return JSON, making them ideal for SPAs.
"""

import base64
import hashlib
import json
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, Optional

from .base_handler import BaseHandler

if TYPE_CHECKING:
    from .. import aw_web_request
    from .. import config as config_class
    from ..interface.hooks import HookRegistry

logger = logging.getLogger(__name__)

# PKCE constants
PKCE_VERIFIER_LENGTH = 64  # 43-128 characters recommended
PKCE_VERIFIER_CHARSET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def generate_pkce_pair() -> tuple[str, str]:
    """
    Generate PKCE code verifier and challenge pair.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    # Generate random code verifier
    code_verifier = "".join(
        secrets.choice(PKCE_VERIFIER_CHARSET) for _ in range(PKCE_VERIFIER_LENGTH)
    )

    # Generate code challenge using S256 method
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return code_verifier, code_challenge


def verify_pkce(code_verifier: str, stored_challenge: str) -> bool:
    """
    Verify PKCE code verifier against stored challenge.

    Args:
        code_verifier: The code verifier from the token request
        stored_challenge: The challenge stored during authorization

    Returns:
        True if verification passes
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(computed_challenge, stored_challenge)


class OAuth2SPAHandler(BaseHandler):
    """
    Handler for SPA-optimized OAuth2 endpoints.

    All responses are JSON - no HTML templates are used.
    """

    def __init__(
        self,
        webobj: Optional["aw_web_request.AWWebObj"] = None,
        config: Optional["config_class.Config"] = None,
        hooks: Optional["HookRegistry"] = None,
    ) -> None:
        if config is None:
            raise RuntimeError("Config is required for OAuth2SPAHandler")
        if webobj is None:
            from .. import aw_web_request

            webobj = aw_web_request.AWWebObj()
        super().__init__(webobj, config, hooks)

        # Set JSON content type for all responses
        if self.response:
            self.response.headers["Content-Type"] = "application/json"

    def _set_cors_headers(self) -> None:
        """Set CORS headers for SPA access."""
        if self.response:
            # Allow configurable origins, default to *
            allowed_origins = getattr(self.config, "spa_cors_origins", ["*"])
            origin = (
                self.request.headers.get("Origin", "*") if self.request.headers else "*"
            )

            if "*" in allowed_origins or origin in allowed_origins:
                self.response.headers["Access-Control-Allow-Origin"] = origin
            else:
                self.response.headers["Access-Control-Allow-Origin"] = allowed_origins[
                    0
                ]

            self.response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, OPTIONS"
            )
            self.response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, Accept"
            )
            self.response.headers["Access-Control-Allow-Credentials"] = "true"
            self.response.headers["Access-Control-Max-Age"] = "86400"

    def options(self, path: str = "") -> dict[str, Any]:
        """Handle CORS preflight requests."""
        self._set_cors_headers()
        self.response.set_status(204)
        return {}

    def get(self, path: str = "") -> dict[str, Any]:
        """
        Handle GET requests to SPA OAuth endpoints.

        Routes:
        - /oauth/spa/config - Get OAuth configuration
        - /oauth/spa/session - Check session status

        Args:
            path: The sub-path after /oauth/spa/

        Returns:
            JSON response dict
        """
        self._set_cors_headers()

        if path == "config":
            return self._handle_config()
        elif path == "session":
            return self._handle_session_check()
        elif path == "callback":
            # OAuth callbacks go to /oauth/callback which auto-detects SPA mode
            return self._json_error(
                400,
                "OAuth callbacks should go to /oauth/callback. "
                "The callback endpoint auto-detects SPA mode via the state parameter.",
            )
        else:
            return self._json_error(404, f"Unknown SPA endpoint: {path}")

    def post(self, path: str = "") -> dict[str, Any]:
        """
        Handle POST requests to SPA OAuth endpoints.

        Routes:
        - /oauth/spa/authorize - Initiate OAuth flow
        - /oauth/spa/token - Token exchange/refresh
        - /oauth/spa/revoke - Token revocation
        - /oauth/spa/logout - Logout and clear session

        Args:
            path: The sub-path after /oauth/spa/

        Returns:
            JSON response dict
        """
        self._set_cors_headers()

        if path == "authorize":
            return self._handle_authorize()
        elif path == "token":
            return self._handle_token()
        elif path == "revoke":
            return self._handle_revoke()
        elif path == "logout":
            return self._handle_logout()
        else:
            return self._json_error(404, f"Unknown SPA endpoint: {path}")

    def _handle_config(self) -> dict[str, Any]:
        """
        Return OAuth configuration for SPAs doing user login.

        GET /oauth/spa/config

        Returns JSON with:
        - oauth_providers: Available OAuth providers with URLs
        - pkce_supported: Whether PKCE is supported
        - spa_mode_supported: Always true for this handler
        - endpoints: OAuth endpoint URLs

        Note: Trust types are NOT included here because this endpoint is for
        user login configuration. Trust types are only relevant for MCP client
        authorization, which uses the /oauth/authorize endpoint (ActingWeb as
        OAuth server). See the MCP authorization flow for trust type selection.
        """
        base_url = f"{self.config.proto}{self.config.fqdn}"

        # Build provider list
        oauth_providers = []
        oauth_enabled = False

        if self.config.oauth and self.config.oauth.get("client_id"):
            try:
                from ..oauth2 import (
                    create_github_authenticator,
                    create_google_authenticator,
                )

                oauth2_provider = getattr(self.config, "oauth2_provider", "google")

                if oauth2_provider == "google":
                    google_auth = create_google_authenticator(self.config)
                    if google_auth.is_enabled():
                        oauth_providers.append(
                            {
                                "name": "google",
                                "display_name": "Google",
                                "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                                "token_endpoint": "https://oauth2.googleapis.com/token",
                                "userinfo_endpoint": "https://www.googleapis.com/oauth2/v3/userinfo",
                            }
                        )
                        oauth_enabled = True

                elif oauth2_provider == "github":
                    github_auth = create_github_authenticator(self.config)
                    if github_auth.is_enabled():
                        oauth_providers.append(
                            {
                                "name": "github",
                                "display_name": "GitHub",
                                "authorization_endpoint": "https://github.com/login/oauth/authorize",
                                "token_endpoint": "https://github.com/login/oauth/access_token",
                                "userinfo_endpoint": "https://api.github.com/user",
                            }
                        )
                        oauth_enabled = True

            except Exception as e:
                logger.warning(f"Failed to get OAuth providers: {e}")

        return {
            "oauth_enabled": oauth_enabled,
            "oauth_providers": oauth_providers,
            "pkce_supported": True,
            "pkce_methods": ["S256"],
            "spa_mode_supported": True,
            "token_delivery_modes": ["json", "cookie", "hybrid"],
            "refresh_token_rotation": True,
            "endpoints": {
                # Unified endpoints (no /spa/ prefix needed)
                "config": f"{base_url}/oauth/config",
                "callback": f"{base_url}/oauth/callback",
                "revoke": f"{base_url}/oauth/revoke",
                "session": f"{base_url}/oauth/session",
                "logout": f"{base_url}/oauth/logout",
                # SPA-specific (different purpose than MCP OAuth2)
                "authorize": f"{base_url}/oauth/spa/authorize",
                "token": f"{base_url}/oauth/spa/token",
                # MCP OAuth2 server endpoints (ActingWeb as OAuth server)
                "mcp_authorize": f"{base_url}/oauth/authorize",
                "mcp_token": f"{base_url}/oauth/token",
                "oauth_callback": f"{base_url}/oauth/callback",
            },
            "discovery": {
                "authorization_server": f"{base_url}/.well-known/oauth-authorization-server",
                "protected_resource": f"{base_url}/.well-known/oauth-protected-resource",
            },
        }

    def _handle_authorize(self) -> dict[str, Any]:
        """
        Initiate OAuth flow for SPA - supports both user login and MCP authorization.

        POST /oauth/spa/authorize

        This endpoint supports two distinct flows:

        1. USER LOGIN (no trust_type):
           - SPA wants to log a user in via Google/GitHub
           - After OAuth, actor is created/looked up for the user
           - No trust relationship is created (user owns their actor)

        2. MCP CLIENT AUTHORIZATION (with trust_type):
           - An MCP client (AI assistant) wants access to a user's actor
           - After OAuth, a trust relationship is created with the specified trust_type
           - The trust_type determines what permissions the MCP client gets

        Request body (JSON):
        - provider: OAuth provider name (google, github)
        - trust_type: Trust type for MCP authorization (optional, omit for user login)
          - If omitted/null: Simple user login, no trust relationship created
          - If specified (e.g., "mcp_client"): Creates trust relationship with that type
        - redirect_uri: Where to redirect after OAuth
        - pkce: "server" for server-managed PKCE, "client" for client-managed
        - code_challenge: Client-provided code challenge (if pkce=client)
        - code_challenge_method: Must be "S256" (if pkce=client)
        - token_delivery: "json", "cookie", or "hybrid" (default: json)

        Returns JSON with:
        - authorization_url: Full URL to redirect user to
        - state: State parameter for CSRF protection
        - code_challenge: Server-generated challenge (if pkce=server)
        - code_challenge_method: "S256" (if pkce=server)
        """
        # Parse request body
        try:
            body = self.request.body
            if body is None:
                body_str = "{}"
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = str(body)

            params = json.loads(body_str) if body_str else {}
        except json.JSONDecodeError:
            return self._json_error(400, "Invalid JSON in request body")

        provider = params.get("provider", "google")
        # trust_type: None = user login, "mcp_client" etc = MCP authorization
        trust_type = params.get("trust_type")  # Default None for user login
        redirect_uri = params.get("redirect_uri", "")
        pkce_mode = params.get("pkce", "server")
        token_delivery = params.get("token_delivery", "json")
        # return_path: Where to redirect after successful auth (e.g., "/app", "/dashboard")
        # The {actor_id} placeholder will be replaced with the actual actor ID
        return_path = params.get("return_path", "/app")

        # Validate token_delivery mode
        if token_delivery not in ["json", "cookie", "hybrid"]:
            return self._json_error(
                400, f"Invalid token_delivery mode: {token_delivery}"
            )

        # Get the appropriate authenticator
        try:
            from ..oauth2 import (
                create_github_authenticator,
                create_google_authenticator,
            )

            if provider == "google":
                authenticator = create_google_authenticator(self.config)
            elif provider == "github":
                authenticator = create_github_authenticator(self.config)
            else:
                return self._json_error(400, f"Unknown OAuth provider: {provider}")

            if not authenticator.is_enabled():
                return self._json_error(400, f"OAuth provider {provider} is not enabled")

        except Exception as e:
            logger.error(f"Failed to create authenticator: {e}")
            return self._json_error(500, "OAuth configuration error")

        # Handle PKCE
        code_challenge = None
        code_verifier = None

        if pkce_mode == "server":
            # Generate PKCE pair server-side
            code_verifier, code_challenge = generate_pkce_pair()
        elif pkce_mode == "client":
            # Client provides code_challenge
            code_challenge = params.get("code_challenge")
            code_challenge_method = params.get("code_challenge_method", "S256")

            if not code_challenge:
                return self._json_error(
                    400, "code_challenge required when pkce=client"
                )
            if code_challenge_method != "S256":
                return self._json_error(
                    400, "Only S256 code_challenge_method is supported"
                )

        # Build state with SPA-specific fields
        # Only include trust_type if provided (for MCP client auth, not user login)
        state_data: dict[str, Any] = {
            "spa_mode": True,
            "redirect_url": redirect_uri,
            "return_path": return_path,  # Final redirect path after auth
            "token_delivery": token_delivery,
            "pkce_mode": pkce_mode,
            "timestamp": int(time.time()),
        }
        if trust_type:
            state_data["trust_type"] = trust_type

        # Store PKCE verifier if server-managed
        if code_verifier:
            from ..oauth_session import get_oauth2_session_manager

            session_manager = get_oauth2_session_manager(self.config)
            pkce_session_id = session_manager.store_session(
                token_data={},
                user_info={},
                state=json.dumps(state_data),
                provider=provider,
                pkce_verifier=code_verifier,
            )
            state_data["pkce_session_id"] = pkce_session_id

        # Create authorization URL
        state_json = json.dumps(state_data)

        try:
            auth_url = authenticator.create_authorization_url(
                state=state_json,
                trust_type=trust_type or "",  # Convert None to "" for type safety
                code_challenge=code_challenge or "",
                code_challenge_method="S256" if code_challenge else "",
            )
        except Exception as e:
            logger.error(f"Failed to create authorization URL: {e}")
            return self._json_error(500, "Failed to create authorization URL")

        response_data: dict[str, Any] = {
            "authorization_url": auth_url,
            "state": state_json,
            "provider": provider,
            "token_delivery": token_delivery,
        }

        # Only include trust_type in response if it was specified (MCP authorization)
        if trust_type:
            response_data["trust_type"] = trust_type

        if pkce_mode == "server" and code_challenge:
            response_data["code_challenge"] = code_challenge
            response_data["code_challenge_method"] = "S256"
            response_data["pkce_managed_by"] = "server"

        return response_data

    def _handle_token(self) -> dict[str, Any]:
        """
        Handle token exchange and refresh with rotation.

        POST /oauth/spa/token

        Request body (JSON):
        - grant_type: "authorization_code" or "refresh_token"
        - code: Authorization code (for authorization_code grant)
        - code_verifier: PKCE verifier (for authorization_code with PKCE)
        - refresh_token: Refresh token (for refresh_token grant)
        - token_delivery: "json", "cookie", or "hybrid"

        For refresh_token grant, implements token rotation:
        - Issues new access token
        - Issues new refresh token
        - Old refresh token is invalidated

        Returns JSON with new tokens.
        """
        # Parse request body
        try:
            body = self.request.body
            if body is None:
                body_str = "{}"
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = str(body)

            params = json.loads(body_str) if body_str else {}
        except json.JSONDecodeError:
            return self._json_error(400, "Invalid JSON in request body")

        grant_type = params.get("grant_type")
        token_delivery = params.get("token_delivery", "json")

        if grant_type == "refresh_token":
            return self._handle_refresh_token(params, token_delivery)
        elif grant_type == "authorization_code":
            return self._handle_authorization_code(params, token_delivery)
        else:
            return self._json_error(400, f"Unsupported grant_type: {grant_type}")

    def _handle_refresh_token(
        self, params: dict[str, Any], token_delivery: str
    ) -> dict[str, Any]:
        """
        Handle refresh token grant with rotation.

        Implements refresh token rotation for security:
        - Each refresh token can only be used once
        - A new refresh token is issued with each refresh
        - If a refresh token is reused, it indicates potential theft
        """
        refresh_token = params.get("refresh_token")

        if not refresh_token:
            # Try to get from cookie
            if self.request.cookies:
                refresh_token = self.request.cookies.get("refresh_token")

        if not refresh_token:
            return self._json_error(400, "Missing refresh_token")

        # Validate refresh token and get associated actor
        from ..oauth_session import get_oauth2_session_manager

        session_manager = get_oauth2_session_manager(self.config)

        # Look up the refresh token
        token_data = session_manager.validate_refresh_token(refresh_token)
        if not token_data:
            return self._json_error(401, "Invalid or expired refresh_token")

        actor_id = token_data.get("actor_id")
        identifier = token_data.get("identifier")

        if not actor_id:
            return self._json_error(401, "Invalid refresh token data")

        # Check if token was already used (replay attack detection)
        # Allow a 2-second grace period for race conditions (e.g., multiple tabs refreshing)
        if token_data.get("used"):
            used_at = token_data.get("used_at", 0)
            grace_period = 2  # seconds
            if int(time.time()) - used_at > grace_period:
                logger.warning(
                    f"Refresh token reuse detected for actor {actor_id} - potential token theft"
                )
                # Revoke all tokens for this actor
                session_manager.revoke_all_tokens(actor_id)
                return self._json_error(
                    401, "Refresh token already used - all tokens revoked for security"
                )
            else:
                # Within grace period - issue new tokens (don't treat as theft)
                # This handles rapid page refreshes where access token is lost from memory
                logger.debug(
                    f"Refresh token reuse within grace period for actor {actor_id} - issuing new tokens"
                )
                # Continue to issue new tokens below (don't mark as used again, already marked)

        else:
            # Mark current refresh token as used (only if not already used)
            session_manager.mark_refresh_token_used(refresh_token)

        # Generate new tokens (rotation)
        new_access_token = self._generate_actingweb_token(actor_id, identifier or "")
        new_refresh_token = session_manager.create_refresh_token(actor_id, identifier)

        expires_in = 3600  # 1 hour for access token
        refresh_expires_in = 86400 * 14  # 2 weeks for refresh token

        response_data: dict[str, Any] = {
            "success": True,
            "actor_id": actor_id,
            "email": identifier,  # Include email/identifier for frontend
            "expires_in": expires_in,
            "expires_at": int(time.time()) + expires_in,
        }

        if token_delivery == "json":
            response_data["access_token"] = new_access_token
            response_data["refresh_token"] = new_refresh_token
            response_data["token_type"] = "Bearer"
            response_data["refresh_token_expires_in"] = refresh_expires_in

        elif token_delivery == "cookie":
            self._set_token_cookies(
                new_access_token, new_refresh_token, expires_in, httponly=True
            )
            response_data["token_delivery"] = "cookie"

        elif token_delivery == "hybrid":
            response_data["access_token"] = new_access_token
            response_data["token_type"] = "Bearer"
            self._set_refresh_token_cookie(new_refresh_token, httponly=True)
            response_data["token_delivery"] = "hybrid"

        logger.debug(f"Refreshed tokens for actor {actor_id} with rotation")
        return response_data

    def _handle_authorization_code(
        self, params: dict[str, Any], token_delivery: str
    ) -> dict[str, Any]:
        """Handle authorization code grant."""
        code = params.get("code")
        code_verifier = params.get("code_verifier")
        state = params.get("state")

        if not code:
            return self._json_error(400, "Missing authorization code")

        # If code_verifier provided, verify PKCE
        if code_verifier and state:
            try:
                state_data = json.loads(state)
                pkce_session_id = state_data.get("pkce_session_id")
                if pkce_session_id:
                    from ..oauth_session import get_oauth2_session_manager

                    session_manager = get_oauth2_session_manager(self.config)
                    pkce_session = session_manager.get_session(pkce_session_id)

                    if pkce_session:
                        stored_verifier = pkce_session.get("pkce_verifier")
                        if stored_verifier and stored_verifier != code_verifier:
                            return self._json_error(400, "PKCE verification failed")
            except Exception as e:
                logger.warning(f"PKCE verification error: {e}")

        # Delegate to callback handler logic
        # For now, redirect to callback endpoint
        return self._json_error(
            400,
            "Use /oauth/spa/callback for authorization code exchange after redirect",
        )

    def _handle_revoke(self) -> dict[str, Any]:
        """
        Revoke access and/or refresh tokens.

        POST /oauth/spa/revoke

        Request body (JSON):
        - token: The token to revoke
        - token_type_hint: "access_token" or "refresh_token" (optional)

        Also clears related cookies.
        """
        # Parse request body
        try:
            body = self.request.body
            if body is None:
                body_str = "{}"
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = str(body)

            params = json.loads(body_str) if body_str else {}
        except json.JSONDecodeError:
            return self._json_error(400, "Invalid JSON in request body")

        token = params.get("token")
        token_type_hint = params.get("token_type_hint", "access_token")

        if not token:
            # Try to get from Authorization header
            auth_header = (
                self.request.headers.get("Authorization", "")
                if self.request.headers
                else ""
            )
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            # Try cookie
            if self.request.cookies:
                token = self.request.cookies.get("access_token") or self.request.cookies.get("oauth_token")

        if not token:
            return self._json_error(400, "No token provided")

        # Revoke the token
        try:
            from ..oauth_session import get_oauth2_session_manager

            session_manager = get_oauth2_session_manager(self.config)

            if token_type_hint == "refresh_token":
                session_manager.revoke_refresh_token(token)
            else:
                session_manager.revoke_access_token(token)

            # Also try to revoke with OAuth provider
            try:
                from ..oauth2 import OAuth2Authenticator

                authenticator = OAuth2Authenticator(self.config)
                authenticator.revoke_token(token)
            except Exception as e:
                logger.debug(f"Provider token revocation failed (non-critical): {e}")

        except Exception as e:
            logger.warning(f"Token revocation error: {e}")

        # Clear cookies
        self._clear_token_cookies()

        return {
            "success": True,
            "message": "Token revoked successfully",
        }

    def _handle_logout(self) -> dict[str, Any]:
        """
        Logout and clear all session data.

        POST /oauth/spa/logout

        Clears all tokens and cookies.
        """
        # Get token to revoke
        token = None
        auth_header = (
            self.request.headers.get("Authorization", "")
            if self.request.headers
            else ""
        )
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token and self.request.cookies:
            token = self.request.cookies.get("access_token") or self.request.cookies.get("oauth_token")

        # Revoke tokens if we have one
        if token:
            try:
                from ..oauth_session import get_oauth2_session_manager

                session_manager = get_oauth2_session_manager(self.config)
                session_manager.revoke_access_token(token)

                # Also revoke with OAuth provider
                from ..oauth2 import OAuth2Authenticator

                authenticator = OAuth2Authenticator(self.config)
                authenticator.revoke_token(token)
            except Exception as e:
                logger.debug(f"Token revocation during logout: {e}")

        # Revoke refresh token if in cookie
        if self.request.cookies:
            refresh_token = self.request.cookies.get("refresh_token")
            if refresh_token:
                try:
                    from ..oauth_session import get_oauth2_session_manager

                    session_manager = get_oauth2_session_manager(self.config)
                    session_manager.revoke_refresh_token(refresh_token)
                except Exception as e:
                    logger.debug(f"Refresh token revocation during logout: {e}")

        # Clear all cookies
        self._clear_token_cookies()

        return {
            "success": True,
            "message": "Logged out successfully",
            "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
        }

    def _handle_session_check(self) -> dict[str, Any]:
        """
        Check current session status.

        GET /oauth/spa/session

        Returns information about the current session if authenticated,
        or indicates no active session.
        """
        # Try to get token from various sources
        token = None

        # Check Authorization header
        auth_header = (
            self.request.headers.get("Authorization", "")
            if self.request.headers
            else ""
        )
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        # Check cookies
        if not token and self.request.cookies:
            token = self.request.cookies.get("access_token") or self.request.cookies.get("oauth_token")

        if not token:
            return {
                "authenticated": False,
                "message": "No active session",
            }

        # Validate token
        try:
            from ..oauth_session import get_oauth2_session_manager

            session_manager = get_oauth2_session_manager(self.config)
            token_data = session_manager.validate_access_token(token)

            if not token_data:
                return {
                    "authenticated": False,
                    "message": "Invalid or expired token",
                }

            actor_id = token_data.get("actor_id")
            identifier = token_data.get("identifier")
            expires_at = token_data.get("expires_at", 0)

            return {
                "authenticated": True,
                "actor_id": actor_id,
                "identifier": identifier,
                "expires_at": expires_at,
                "expires_in": max(0, expires_at - int(time.time())),
            }

        except Exception as e:
            logger.warning(f"Session check error: {e}")
            return {
                "authenticated": False,
                "message": "Session validation failed",
            }

    def _generate_actingweb_token(self, actor_id: str, identifier: str) -> str:
        """Generate an ActingWeb access token for an actor."""
        # Use the config's token generation
        token = self.config.new_token()

        # Store token mapping
        try:
            from ..oauth_session import get_oauth2_session_manager

            session_manager = get_oauth2_session_manager(self.config)
            session_manager.store_access_token(token, actor_id, identifier)
        except Exception as e:
            logger.warning(f"Failed to store access token: {e}")

        return token

    def _set_token_cookies(
        self,
        access_token: str,
        refresh_token: str | None,
        expires_in: int,
        httponly: bool = True,
    ) -> None:
        """Set access and refresh token cookies."""
        if self.response:
            # Access token cookie
            self.response.set_cookie(
                "access_token",
                access_token,
                max_age=expires_in,
                path="/",
                secure=True,
                httponly=httponly,
                samesite="Lax",
            )

            # Also set oauth_token for compatibility
            self.response.set_cookie(
                "oauth_token",
                access_token,
                max_age=expires_in,
                path="/",
                secure=True,
                httponly=httponly,
                samesite="Lax",
            )

            if refresh_token:
                self._set_refresh_token_cookie(refresh_token, httponly)

    def _set_refresh_token_cookie(
        self, refresh_token: str, httponly: bool = True
    ) -> None:
        """Set refresh token cookie."""
        if self.response:
            self.response.set_cookie(
                "refresh_token",
                refresh_token,
                max_age=86400 * 14,  # 2 weeks
                path="/",  # Use root path so browser stores it properly
                secure=True,
                httponly=httponly,
                samesite="Lax",  # Lax allows the cookie on same-site navigations
            )

    def _clear_token_cookies(self) -> None:
        """Clear all token cookies."""
        if self.response:
            for cookie_name in [
                "access_token",
                "oauth_token",
                "refresh_token",
                "session_id",
            ]:
                self.response.set_cookie(
                    cookie_name, "", max_age=-1, path="/", secure=True
                )
                # Also clear with different path for refresh token
                if cookie_name == "refresh_token":
                    self.response.set_cookie(
                        cookie_name,
                        "",
                        max_age=-1,
                        path="/oauth/spa/token",
                        secure=True,
                    )

    def _json_error(self, status_code: int, message: str) -> dict[str, Any]:
        """Create JSON error response."""
        if self.response:
            self.response.set_status(status_code)
            self.response.headers["Content-Type"] = "application/json"

        return {
            "error": True,
            "status_code": status_code,
            "message": message,
        }
