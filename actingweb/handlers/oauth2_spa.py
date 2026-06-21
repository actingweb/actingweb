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
from urllib.parse import urlparse

from ..constants import SPA_REFRESH_TOKEN_REUSE_WINDOW
from .base_handler import BaseHandler
from .oauth2_utils import normalize_user_info

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

# Token refresh grace period constants (in seconds)
# These handle concurrent refresh token requests from SPAs
GRACE_PERIOD_IMMEDIATE = 10  # Normal concurrent requests (common in SPAs)
GRACE_PERIOD_EXTENDED = 60  # Network delays or slow processing
# Reuse within (GRACE_PERIOD_EXTENDED, SPA_REFRESH_TOKEN_REUSE_WINDOW] is treated
# as potential theft (chain revoked); beyond that horizon a reused token is
# treated as expired (the row is only still present because the purge lagged).


_KNOWN_PROVIDER_PREFIXES = ("google", "github", "apple", "google-native")


def _is_known_provider(name: str) -> bool:
    """Check if a provider name is a known provider or variant (e.g. google-mobile)."""
    return any(
        name == prefix or name.startswith(f"{prefix}-")
        for prefix in _KNOWN_PROVIDER_PREFIXES
    )


def _provider_response_mode(name: str) -> str:
    """Authorization response mode for a provider: Apple uses form_post."""
    if name == "apple" or name.startswith("apple-"):
        return "form_post"
    return "query"


def _provider_platform(name: str) -> str:
    """Target platform hint for a provider entry (web / any).

    Plain providers (``google``, ``github``, ``apple``) drive the web/SPA flow;
    ``-mobile`` and ``-native`` variants target native apps and are usable on any
    device. Clients can branch on this to pick the right flow per platform.
    """
    if name.endswith("-mobile") or name.endswith("-native"):
        return "any"
    return "web"


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

            self.response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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

        try:
            from ..oauth2 import (
                create_oauth2_authenticator,
                get_provider_display_name,
            )

            providers_cfg = getattr(self.config, "oauth_providers", {})
            if providers_cfg:
                # Multi-provider path: iterate all configured providers
                for prov_name in providers_cfg:
                    auth = create_oauth2_authenticator(self.config, prov_name)
                    if auth.is_enabled():
                        oauth_providers.append(
                            {
                                "name": auth.provider.name,
                                "display_name": get_provider_display_name(prov_name),
                                "authorization_endpoint": auth.provider.auth_uri,
                                "token_endpoint": auth.provider.token_uri,
                                "userinfo_endpoint": auth.provider.userinfo_uri,
                                "response_mode": _provider_response_mode(prov_name),
                                "platform": _provider_platform(prov_name),
                            }
                        )
                        oauth_enabled = True
            elif self.config.oauth and self.config.oauth.get("client_id"):
                # Single-provider backward-compat path
                auth = create_oauth2_authenticator(self.config)
                if auth.is_enabled():
                    oauth_providers.append(
                        {
                            "name": auth.provider.name,
                            "display_name": get_provider_display_name(
                                auth.provider.name
                            ),
                            "authorization_endpoint": auth.provider.auth_uri,
                            "token_endpoint": auth.provider.token_uri,
                            "userinfo_endpoint": auth.provider.userinfo_uri,
                            "response_mode": _provider_response_mode(
                                auth.provider.name
                            ),
                            "platform": _provider_platform(auth.provider.name),
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

        # Validate provider name (must be a known provider or variant)
        if not _is_known_provider(provider):
            return self._json_error(400, f"Unknown OAuth provider: {provider}")

        # Validate the post-auth redirect target. After OAuth completes the
        # browser is redirected here with a one-time ?session= id, so an
        # attacker-supplied origin would leak it (open redirect / token theft).
        if redirect_uri:
            from .oauth2_callback import is_safe_spa_redirect

            if not is_safe_spa_redirect(self.config, redirect_uri):
                return self._json_error(400, "Invalid redirect_uri")

        # Get the appropriate authenticator
        try:
            from ..oauth2 import create_oauth2_authenticator

            authenticator = create_oauth2_authenticator(self.config, provider)

            if not authenticator.is_enabled():
                return self._json_error(
                    400, f"OAuth provider {provider} is not enabled"
                )

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
                return self._json_error(400, "code_challenge required when pkce=client")
            if code_challenge_method != "S256":
                return self._json_error(
                    400, "Only S256 code_challenge_method is supported"
                )

        # Build state with SPA-specific fields
        # Only include trust_type if provided (for MCP client auth, not user login)
        state_data: dict[str, Any] = {
            "spa_mode": True,
            "provider": provider,
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

        # Apple uses response_mode=form_post (cross-site POST callback). A
        # cleartext-JSON state offers no CSRF protection there, so we store the
        # full state payload server-side and send Apple only an opaque single-use
        # nonce. Apple also does not support PKCE — don't forward a code_challenge.
        is_apple = provider == "apple" or provider.startswith("apple-")
        if is_apple:
            from ..oauth_state_store import StateNonceStore

            state_for_provider = StateNonceStore(self.config).create(state_data)
            apple_challenge = ""
        else:
            state_for_provider = state_json
            apple_challenge = code_challenge or ""

        try:
            auth_url = authenticator.create_authorization_url(
                state=state_for_provider,
                trust_type=trust_type or "",  # Convert None to "" for type safety
                code_challenge="" if is_apple else apple_challenge,
                code_challenge_method=""
                if is_apple
                else ("S256" if code_challenge else ""),
            )
        except Exception as e:
            logger.error(f"Failed to create authorization URL: {e}")
            return self._json_error(500, "Failed to create authorization URL")

        response_data: dict[str, Any] = {
            "authorization_url": auth_url,
            "state": state_for_provider,
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

        if token_delivery not in ["json", "cookie", "hybrid"]:
            return self._json_error(
                400, f"Invalid token_delivery mode: {token_delivery}"
            )

        if grant_type == "refresh_token":
            result = self._handle_refresh_token(params, token_delivery)
        elif grant_type == "authorization_code":
            result = self._handle_authorization_code(params, token_delivery)
        elif grant_type == "urn:ietf:params:oauth:grant-type:jwt-bearer":
            result = self._handle_jwt_bearer_grant(params, token_delivery)
        elif grant_type in ("mobile_ticket", "apple_mobile_ticket"):
            # apple_mobile_ticket is the original (Apple-only) name, kept as an
            # alias for the now provider-agnostic mobile_ticket grant.
            result = self._handle_mobile_ticket(params, token_delivery)
        elif grant_type == "passphrase":
            result = self._handle_passphrase_exchange(params, token_delivery)
        else:
            return self._json_error(400, f"Unsupported grant_type: {grant_type}")

        # Opportunistic, self-contained cleanup of expired SPA tokens. The token
        # endpoint is the natural heartbeat for this, and the underlying call is
        # throttled to at most once per interval per process — so the library
        # bounds token-table growth on its own, without requiring the
        # application to schedule a cron/Lambda. Best-effort: never let cleanup
        # affect the token response. (On DynamoDB this is a no-op; native TTL on
        # the attributes table handles expiry — see deployment docs.)
        try:
            from ..oauth_session import get_oauth2_session_manager

            get_oauth2_session_manager(self.config).maybe_purge_expired_tokens()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug(f"Opportunistic token purge skipped: {e}")

        return result

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

        # Atomically check and mark token as used (race-free)
        # This ensures only one concurrent request can successfully use the token
        success, token_data = session_manager.try_mark_refresh_token_used(refresh_token)

        if not token_data:
            return self._json_error(401, "Invalid or expired refresh_token")

        actor_id = token_data.get("actor_id")
        identifier = token_data.get("identifier")

        if not actor_id:
            return self._json_error(401, "Invalid refresh token data")

        # If token was already used, apply a grace window before treating the
        # reuse as theft:
        #   0 - GRACE_PERIOD_EXTENDED: benign reuse -> FULL rotation (same chain)
        #   > GRACE_PERIOD_EXTENDED:   potential theft -> revoke the chain
        #
        # Within the grace window the reuse is either a genuine concurrent /
        # duplicate request, or a client that dropped its previous rotation
        # (e.g. an iPad/Capacitor app suspended before it persisted the rotated
        # token). Either way we issue a full rotation in the same chain so the
        # client gets a fresh, usable refresh token and recovers.
        #
        # Earlier revisions issued an access-token-only response in the 10-60s
        # tier (no new refresh token). That stranded exactly the client this
        # window is meant to help: a client whose *stored* refresh token is the
        # reused one kept that already-used token and, one access-token lifetime
        # later, presented it again past the grace window -> a guaranteed theft
        # lockout. Rotating here lets it heal instead. The marginal security
        # cost (a token reuser in the grace window now also receives a refresh
        # token, not just a 1h access token) is bounded by chain-scoped theft
        # detection: any later reuse across the divergent branches revokes the
        # whole family.
        if not success:
            used_at = token_data.get("used_at", 0)
            time_since_use = int(time.time()) - used_at

            if time_since_use <= GRACE_PERIOD_IMMEDIATE:
                logger.debug(
                    f"Refresh token reuse within {time_since_use}s for actor {actor_id} "
                    f"(concurrent request) - issuing new tokens with rotation"
                )
                # Fall through to full rotation below.
            elif time_since_use <= GRACE_PERIOD_EXTENDED:
                logger.info(
                    f"Refresh token reuse after {time_since_use}s for actor {actor_id} "
                    f"(delayed or dropped-rotation request) - issuing new tokens with rotation"
                )
                # Fall through to full rotation below.
            elif time_since_use > SPA_REFRESH_TOKEN_REUSE_WINDOW:
                # Past the reuse-detection horizon. On rotation the consumed
                # token's storage TTL was shortened to this window, so it should
                # already be purged; we only still see it because the purge is
                # throttled (PostgreSQL) or eventually-consistent (DynamoDB TTL
                # can lag). Beyond the horizon we no longer assert theft — a
                # long-backgrounded client replaying a stale token must not be
                # able to revoke the family that has long since rotated past it.
                # Treat it as an expired token and reject WITHOUT revoking the
                # chain, identical to a token that was physically purged.
                logger.info(
                    f"Refresh token reuse {time_since_use}s after first use for "
                    f"actor {actor_id} - past the reuse-detection window, "
                    f"treating as expired (no revocation)"
                )
                return self._json_error(401, "Invalid or expired refresh_token")
            else:
                # Token reuse within the detection window (after the grace
                # period) - potential theft. Scope the response to the offending
                # refresh-token family (RFC 6819 token-family revocation) instead
                # of nuking every token for the actor: revoking only this chain
                # locks out the affected device/lineage while the actor's other
                # devices — which have their own chain_id — keep working. Legacy
                # tokens minted before chain_id existed fall back to revoking just
                # the presented token, which still avoids the mass-logout.
                chain_id = token_data.get("chain_id")
                if chain_id:
                    revoked = session_manager.revoke_token_chain(actor_id, chain_id)
                    logger.warning(
                        f"Refresh token reuse detected for actor {actor_id} "
                        f"({time_since_use}s after first use) - potential token theft, "
                        f"revoked {revoked} token(s) in chain {chain_id[:8]}..."
                    )
                else:
                    session_manager.revoke_refresh_token(refresh_token)
                    logger.warning(
                        f"Refresh token reuse detected for actor {actor_id} "
                        f"({time_since_use}s after first use) - potential token theft, "
                        f"revoked the reused (legacy, chain-less) token"
                    )
                return self._json_error(
                    401, "Refresh token already used - session revoked for security"
                )

        # Generate new tokens (rotation). Propagate the consumed token's chain_id
        # so the rotated tokens stay in the same family; if reuse is later
        # detected anywhere in this lineage, only this family is revoked — and
        # the access token is tagged with the chain so it is revoked too.
        chain_id = token_data.get("chain_id")
        new_access_token = self._generate_actingweb_token(
            actor_id, identifier or "", chain_id=chain_id
        )
        new_refresh_token = session_manager.create_refresh_token(
            actor_id, identifier, chain_id=chain_id
        )

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
        """
        Handle authorization code grant for mobile apps.

        Mobile apps receive the authorization code directly via deep link
        (custom URL scheme) and exchange it here for ActingWeb SPA tokens.

        Request params:
        - code: Authorization code from OAuth provider
        - provider: Provider name (e.g. "google-mobile", "github-mobile")
        - redirect_uri: The redirect_uri used in the authorization request
        - code_verifier: PKCE code verifier (recommended for mobile apps per RFC 7636)
        - token_delivery: "json", "cookie", or "hybrid"
        """
        code = params.get("code")
        provider = params.get("provider", "google")
        redirect_uri = params.get("redirect_uri")
        code_verifier = params.get("code_verifier")

        if not code:
            return self._json_error(400, "Missing authorization code")

        if not _is_known_provider(provider):
            return self._json_error(400, f"Unknown OAuth provider: {provider}")

        # PKCE is mandatory (fail-closed) for native authorization_code exchanges:
        # a native/`-mobile` provider, or any custom-scheme (non-http[s])
        # redirect_uri, where an intercepted code without a verifier is exploitable
        # (RFC 8252). Web/SPA same-origin flows (http/https redirect) keep working
        # with server-managed PKCE and only get a soft warning if a verifier is
        # absent.
        if not code_verifier:
            scheme = urlparse(redirect_uri).scheme if redirect_uri else ""
            is_native = (
                provider.endswith("-mobile")
                or provider.endswith("-native")
                or (scheme not in ("http", "https", ""))
            )
            if is_native:
                return self._json_error(
                    400,
                    "PKCE code_verifier required for native authorization_code "
                    "exchange",
                )
            logger.warning(
                "authorization_code exchange without PKCE code_verifier. "
                "PKCE is strongly recommended (RFC 7636)."
            )

        # Create authenticator for the specified provider
        try:
            from ..oauth2 import create_oauth2_authenticator

            authenticator = create_oauth2_authenticator(self.config, provider)

            if not authenticator.is_enabled():
                return self._json_error(
                    400, f"OAuth provider {provider} is not enabled"
                )
        except Exception as e:
            logger.error(f"Failed to create authenticator for {provider}: {e}")
            return self._json_error(500, "OAuth configuration error")

        # Exchange authorization code for tokens
        token_data = authenticator.exchange_code_for_token(
            code, code_verifier=code_verifier, redirect_uri=redirect_uri
        )
        if not token_data or "access_token" not in token_data:
            logger.error("Failed to exchange authorization code for access token")
            return self._json_error(401, "Token exchange failed")

        provider_access_token = token_data["access_token"]
        provider_refresh_token = token_data.get("refresh_token")
        provider_expires_in = token_data.get("expires_in", 3600)

        # Validate token and get user info
        user_info = authenticator.validate_token_and_get_user_info(
            provider_access_token
        )
        if not user_info:
            logger.error("Failed to validate token or extract user info")
            return self._json_error(401, "Token validation failed")

        # Normalize the user_info shape so the oauth_success hook sees a
        # consistent (display_name / given_name / family_name / email) shape.
        user_info = normalize_user_info(provider, user_info)

        # Extract identifier (email or provider ID)
        require_email = bool(
            self.config and getattr(self.config, "force_email_prop_as_creator", False)
        )
        identifier = authenticator.get_email_from_user_info(
            user_info, provider_access_token, require_email=require_email
        )

        if not identifier:
            if not require_email:
                return self._json_error(
                    401, "OAuth provider did not return user identifier"
                )
            return self._json_error(
                401,
                "Email required but not provided by OAuth provider. "
                f"Configure your {authenticator.provider.name} account to make email public.",
            )

        # Lookup or create actor
        from .. import actor as actor_module

        existing_check = actor_module.Actor(config=self.config)
        actor_exists = existing_check.get_from_creator(identifier)

        if actor_exists:
            # Use the already-fetched actor instead of doing another DB lookup
            actor_instance = existing_check
            is_new_actor = False
        else:
            actor_instance = authenticator.lookup_or_create_actor_by_identifier(
                identifier, user_info=user_info
            )
            is_new_actor = True

        if not actor_instance:
            logger.error(f"Failed to lookup or create actor for {identifier}")
            return self._json_error(500, "Actor creation failed")

        # Store OAuth tokens in actor properties
        if actor_instance.store:
            actor_instance.store.oauth_token = provider_access_token
            actor_instance.store.oauth_token_expiry = (
                str(int(time.time()) + provider_expires_in)
                if provider_expires_in
                else None
            )
            if provider_refresh_token:
                actor_instance.store.oauth_refresh_token = provider_refresh_token
            actor_instance.store.oauth_token_timestamp = str(int(time.time()))

        # Execute actor_created lifecycle hook for new actors
        if is_new_actor and self.hooks:
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor_instance, service_registry=registry
                )
                self.hooks.execute_lifecycle_hooks("actor_created", actor_interface)
            except Exception as e:
                logger.error(f"Error in lifecycle hook for actor_created: {e}")

        # Execute OAuth success lifecycle hook
        oauth_valid = True
        if self.hooks:
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor_instance, service_registry=registry
                )
                result = self.hooks.execute_lifecycle_hooks(
                    "oauth_success",
                    actor_interface,
                    email=identifier,
                    access_token=provider_access_token,
                    token_data=token_data,
                    user_info=user_info,
                )
                oauth_valid = bool(result) if result is not None else True
            except Exception as e:
                logger.error(f"Error in lifecycle hook for oauth_success: {e}")
                oauth_valid = False

        if not oauth_valid:
            logger.warning(
                f"OAuth success hook rejected authentication for {identifier}"
            )
            return self._json_error(403, "Authentication rejected")

        # Generate ActingWeb SPA tokens
        actor_id = actor_instance.id or ""
        spa_access_token = self._generate_actingweb_token(actor_id, identifier)

        from ..oauth_session import get_oauth2_session_manager

        session_manager = get_oauth2_session_manager(self.config)
        spa_refresh_token = session_manager.create_refresh_token(actor_id, identifier)

        expires_in = 3600  # 1 hour for access token
        refresh_expires_in = 86400 * 14  # 2 weeks for refresh token

        response_data: dict[str, Any] = {
            "success": True,
            "actor_id": actor_id,
            "email": identifier,
            "expires_in": expires_in,
            "expires_at": int(time.time()) + expires_in,
        }

        if token_delivery == "json":
            response_data["access_token"] = spa_access_token
            response_data["refresh_token"] = spa_refresh_token
            response_data["token_type"] = "Bearer"
            response_data["refresh_token_expires_in"] = refresh_expires_in
        elif token_delivery == "cookie":
            self._set_token_cookies(
                spa_access_token, spa_refresh_token, expires_in, httponly=True
            )
            response_data["token_delivery"] = "cookie"
        elif token_delivery == "hybrid":
            response_data["access_token"] = spa_access_token
            response_data["token_type"] = "Bearer"
            self._set_refresh_token_cookie(spa_refresh_token, httponly=True)
            response_data["token_delivery"] = "hybrid"

        logger.info(
            f"Mobile OAuth authorization_code exchange successful for {identifier} "
            f"via {provider}"
        )
        return response_data

    def _validate_id_token_for_provider(
        self, provider_name: str, assertion: str, nonce: str | None
    ) -> tuple[Any, dict[str, Any] | None, str | None]:
        """Validate a native ``id_token`` and bind it to the declared provider.

        Returns ``(authenticator, claims, error)``. Dispatch is by the declared
        ``provider_name``, but the validator is selected from that provider and
        the token's ``iss`` must match that provider's accepted issuers — so a
        Google id_token submitted with ``provider=apple-mobile`` is rejected.
        """
        from ..oauth2 import create_oauth2_authenticator

        authenticator = create_oauth2_authenticator(self.config, provider_name)
        validator = getattr(authenticator.provider, "id_token_validator", None)
        if validator is None:
            return None, None, "provider does not support id_token validation"

        # Pre-check issuer vs declared provider for a clear, specific error.
        try:
            import jwt

            unverified = jwt.decode(
                assertion, options={"verify_signature": False, "verify_aud": False}
            )
        except Exception:
            return None, None, "malformed id_token"

        iss = unverified.get("iss")
        if iss not in validator.expected_iss:
            return None, None, "id_token issuer does not match declared provider"

        claims = validator.validate(assertion, nonce=nonce)
        if not claims:
            return None, None, "id_token validation failed"

        return authenticator, claims, None

    def _finalize_native_session(
        self,
        provider: str,
        authenticator: Any,
        identifier: str,
        user_info: dict[str, Any],
        token_data: dict[str, Any],
        token_delivery: str,
        *,
        provider_access_token: str = "",
        provider_refresh_token: str | None = None,
        provider_expires_in: int | None = None,
    ) -> dict[str, Any]:
        """Shared tail for native grants: actor lookup/create, hooks, tokens.

        Mirrors the authorization_code grant's completion but works without an
        upstream access token (the JWT-bearer grant only has an id_token).
        """
        from .. import actor as actor_module

        existing_check = actor_module.Actor(config=self.config)
        if existing_check.get_from_creator(identifier):
            actor_instance = existing_check
            is_new_actor = False
        else:
            actor_instance = authenticator.lookup_or_create_actor_by_identifier(
                identifier, user_info=user_info
            )
            is_new_actor = True

        if not actor_instance:
            logger.error(f"Failed to lookup or create actor for {identifier}")
            return self._json_error(500, "Actor creation failed")

        # Persist upstream provider tokens when we have them (apple_mobile_ticket).
        if actor_instance.store and provider_access_token:
            actor_instance.store.oauth_token = provider_access_token
            actor_instance.store.oauth_token_expiry = (
                str(int(time.time()) + provider_expires_in)
                if provider_expires_in
                else None
            )
            if provider_refresh_token:
                actor_instance.store.oauth_refresh_token = provider_refresh_token
            actor_instance.store.oauth_token_timestamp = str(int(time.time()))

        if is_new_actor and self.hooks:
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor_instance, service_registry=registry
                )
                self.hooks.execute_lifecycle_hooks("actor_created", actor_interface)
            except Exception as e:
                logger.error(f"Error in lifecycle hook for actor_created: {e}")

        oauth_valid = True
        if self.hooks:
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor_instance, service_registry=registry
                )
                result = self.hooks.execute_lifecycle_hooks(
                    "oauth_success",
                    actor_interface,
                    email=identifier,
                    access_token=provider_access_token,
                    token_data=token_data,
                    user_info=user_info,
                )
                oauth_valid = bool(result) if result is not None else True
            except Exception as e:
                logger.error(f"Error in lifecycle hook for oauth_success: {e}")
                oauth_valid = False

        if not oauth_valid:
            logger.warning(
                f"OAuth success hook rejected authentication for {identifier}"
            )
            return self._json_error(403, "Authentication rejected")

        actor_id = actor_instance.id or ""
        spa_access_token = self._generate_actingweb_token(actor_id, identifier)

        from ..oauth_session import get_oauth2_session_manager

        session_manager = get_oauth2_session_manager(self.config)
        spa_refresh_token = session_manager.create_refresh_token(actor_id, identifier)

        expires_in = 3600
        refresh_expires_in = 86400 * 14

        response_data: dict[str, Any] = {
            "success": True,
            "actor_id": actor_id,
            "email": identifier,
            "expires_in": expires_in,
            "expires_at": int(time.time()) + expires_in,
        }

        if token_delivery == "json":
            response_data["access_token"] = spa_access_token
            response_data["refresh_token"] = spa_refresh_token
            response_data["token_type"] = "Bearer"
            response_data["refresh_token_expires_in"] = refresh_expires_in
        elif token_delivery == "cookie":
            self._set_token_cookies(
                spa_access_token, spa_refresh_token, expires_in, httponly=True
            )
            response_data["token_delivery"] = "cookie"
        elif token_delivery == "hybrid":
            response_data["access_token"] = spa_access_token
            response_data["token_type"] = "Bearer"
            self._set_refresh_token_cookie(spa_refresh_token, httponly=True)
            response_data["token_delivery"] = "hybrid"

        logger.info(f"Native OAuth session issued for {identifier} via {provider}")
        return response_data

    def _handle_jwt_bearer_grant(
        self, params: dict[str, Any], token_delivery: str
    ) -> dict[str, Any]:
        """JWT-bearer grant (RFC 7523): exchange a provider id_token for a session.

        Request body (JSON):
        - grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer"
        - provider: declared provider (e.g. "apple-mobile", "google-native")
        - assertion: the provider id_token (JWT)
        - nonce: the nonce the app sent to the IdP (required)
        """
        provider = params.get("provider", "")
        assertion = params.get("assertion", "")
        nonce = params.get("nonce")

        if not provider or not _is_known_provider(provider):
            return self._json_error(400, f"Unknown OAuth provider: {provider}")
        if not assertion:
            return self._json_error(400, "Missing assertion (id_token)")
        if nonce is None or nonce == "":
            return self._json_error(400, "Missing nonce")

        authenticator, claims, error = self._validate_id_token_for_provider(
            provider, assertion, nonce
        )
        if error or not claims or authenticator is None:
            return self._json_error(400, error or "id_token validation failed")

        # Replay protection: an id_token may be presented only once.
        from ..oauth2_replay import IdTokenReplayCache

        if not IdTokenReplayCache(self.config).check_and_record(claims):
            return self._json_error(400, "id_token replay rejected")

        # Honor email-as-creator mode: reject a provider-ID-only id_token when the
        # app requires email as the actor creator (parity with the web flow).
        require_email = bool(getattr(self.config, "force_email_prop_as_creator", False))
        identifier = authenticator.get_email_from_user_info(
            claims, require_email=require_email
        )
        if not identifier:
            return self._json_error(401, "id_token did not yield a user identifier")

        user_info = normalize_user_info(provider, claims)
        return self._finalize_native_session(
            provider,
            authenticator,
            identifier,
            user_info,
            token_data={"id_token": assertion},
            token_delivery=token_delivery,
        )

    def _handle_mobile_ticket(
        self, params: dict[str, Any], token_delivery: str
    ) -> dict[str, Any]:
        """Mobile-ticket grant: redeem a deep-link ticket for a session.

        Provider-agnostic completion of any native-mobile flow that routed its
        authorization code through the HTTPS callback (Apple-on-Android,
        GitHub mobile). The server exchanges the stored code and derives identity
        the way the provider supports it — from the id_token in the token
        response (Apple) or from the userinfo endpoint (GitHub).

        Request body (JSON):
        - grant_type: "mobile_ticket" (or the "apple_mobile_ticket" alias)
        - ticket: the opaque ticket delivered to the app's deep link
        """
        ticket = params.get("ticket", "")
        if not ticket:
            return self._json_error(400, "Missing ticket")

        from ..oauth_state_store import MobileTicketStore

        stored = MobileTicketStore(self.config).consume(ticket)
        if not stored:
            return self._json_error(400, "Invalid or expired ticket")

        provider = str(stored.get("provider", "apple-mobile"))
        code = str(stored.get("code", ""))
        redirect_uri = str(stored.get("redirect_uri", ""))
        if not code:
            return self._json_error(400, "Ticket missing authorization code")

        # Recover the server-managed PKCE verifier when the authorize step sent a
        # code_challenge (e.g. GitHub). Without it the provider rejects the
        # deferred exchange with invalid_grant.
        code_verifier: str | None = None
        extra = stored.get("extra") if isinstance(stored.get("extra"), dict) else {}
        pkce_session_id = (extra or {}).get("pkce_session_id")
        if pkce_session_id:
            from ..oauth_session import get_oauth2_session_manager

            pkce_session = get_oauth2_session_manager(self.config).get_session(
                str(pkce_session_id)
            )
            if pkce_session:
                code_verifier = pkce_session.get("pkce_verifier")

        from ..oauth2 import create_oauth2_authenticator

        authenticator = create_oauth2_authenticator(self.config, provider)
        token_data = authenticator.exchange_code_for_token(
            code, redirect_uri=redirect_uri, code_verifier=code_verifier
        )
        if not token_data or "access_token" not in token_data:
            return self._json_error(401, "Token exchange failed")

        # Identity: OIDC providers (Apple) carry it in the id_token within the
        # token response; others (GitHub) fetch it from the userinfo endpoint.
        claims = authenticator.provider.extract_user_info_from_token_response(
            token_data
        )
        if not claims:
            claims = authenticator.validate_token_and_get_user_info(
                token_data["access_token"]
            )
        if not claims:
            return self._json_error(401, "Failed to extract user info")

        # Honor email-as-creator mode: in that configuration a provider-ID
        # identifier (apple:sub / github:id) must not be accepted.
        require_email = bool(getattr(self.config, "force_email_prop_as_creator", False))
        identifier = authenticator.get_email_from_user_info(
            claims, token_data.get("access_token", ""), require_email=require_email
        )
        if not identifier:
            return self._json_error(401, "Sign-in did not yield a user identifier")

        user_info = normalize_user_info(provider, claims)
        return self._finalize_native_session(
            provider,
            authenticator,
            identifier,
            user_info,
            token_data=token_data,
            token_delivery=token_delivery,
            provider_access_token=token_data["access_token"],
            provider_refresh_token=token_data.get("refresh_token"),
            provider_expires_in=token_data.get("expires_in", 3600),
        )

    def _handle_passphrase_exchange(
        self, params: dict[str, Any], token_delivery: str
    ) -> dict[str, Any]:
        """
        Handle passphrase grant for devtest mode.

        This endpoint allows exchanging a valid creator passphrase for SPA tokens.
        It is ONLY available when devtest mode is enabled.

        This is useful for automated testing tools like Playwright that need
        authenticated access without going through the full OAuth2 flow.

        POST /oauth/spa/token with grant_type="passphrase"

        Request body (JSON):
        - grant_type: "passphrase"
        - actor_id: The actor ID
        - passphrase: The creator passphrase
        - token_delivery: "json", "cookie", or "hybrid" (optional, default: "json")

        Returns JSON with:
        - success: True if authentication successful
        - actor_id: The actor ID
        - access_token: Access token (if token_delivery is "json" or "hybrid")
        - refresh_token: Refresh token (if token_delivery is "json")
        - token_type: "Bearer"
        - expires_in: Token expiration in seconds
        - expires_at: Token expiration timestamp
        - refresh_token_expires_in: Refresh token expiration in seconds
        """
        # Security check: Only allow in devtest mode
        if not self.config.devtest:
            logger.warning("Passphrase grant attempted but devtest mode is disabled")
            return self._json_error(
                403, "Passphrase grant is only available in devtest mode"
            )

        # Validate required parameters
        actor_id = params.get("actor_id")
        passphrase = params.get("passphrase")

        if not actor_id:
            return self._json_error(400, "Missing required parameter: actor_id")

        if not passphrase:
            return self._json_error(400, "Missing required parameter: passphrase")

        # Load and validate actor
        from ..actor import Actor

        actor = Actor(actor_id, config=self.config)

        if not actor.id:
            logger.debug(f"Passphrase grant failed: actor {actor_id} not found")
            return self._json_error(404, "Actor not found")

        # Validate passphrase
        if not actor.passphrase or passphrase != actor.passphrase:
            logger.debug(
                f"Passphrase grant failed: invalid passphrase for actor {actor_id}"
            )
            return self._json_error(401, "Invalid passphrase")

        # Generate tokens
        identifier = actor.creator or ""
        access_token = self._generate_actingweb_token(actor_id, identifier)

        from ..oauth_session import get_oauth2_session_manager

        session_manager = get_oauth2_session_manager(self.config)
        refresh_token = session_manager.create_refresh_token(actor_id, identifier)

        expires_in = 3600  # 1 hour for access token
        refresh_expires_in = 86400 * 14  # 2 weeks for refresh token

        response_data: dict[str, Any] = {
            "success": True,
            "actor_id": actor_id,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "expires_at": int(time.time()) + expires_in,
            "refresh_token_expires_in": refresh_expires_in,
        }

        if token_delivery == "json":
            response_data["access_token"] = access_token
            response_data["refresh_token"] = refresh_token

        elif token_delivery == "cookie":
            self._set_token_cookies(
                access_token, refresh_token, expires_in, httponly=True
            )
            response_data["token_delivery"] = "cookie"

        elif token_delivery == "hybrid":
            response_data["access_token"] = access_token
            self._set_refresh_token_cookie(refresh_token, httponly=True)
            response_data["token_delivery"] = "hybrid"

        logger.info(f"Passphrase grant successful for actor {actor_id}")
        return response_data

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
                token = self.request.cookies.get(
                    "access_token"
                ) or self.request.cookies.get("oauth_token")

        if not token:
            return self._json_error(400, "No token provided")

        # Revoke the token
        try:
            from ..oauth_session import get_oauth2_session_manager

            session_manager = get_oauth2_session_manager(self.config)

            if token_type_hint == "refresh_token":
                session_manager.revoke_refresh_token(token)
            else:
                # Look up actor from session token and clear provider token
                try:
                    token_data = session_manager.validate_access_token(token)
                    if token_data:
                        actor_id = token_data.get("actor_id")
                        if actor_id:
                            self._clear_provider_token_for_actor(actor_id)
                except Exception as lookup_error:
                    logger.debug(f"Provider token lookup during revoke: {lookup_error}")
                session_manager.revoke_access_token(token)

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

        Clears all tokens and cookies. Also clears the stored provider token
        locally so the backend can no longer make API calls on behalf of the
        user — but does NOT call the provider's revocation endpoint (logout is
        not an account disconnect; see _clear_provider_token_for_actor).
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
            token = self.request.cookies.get(
                "access_token"
            ) or self.request.cookies.get("oauth_token")

        if token:
            try:
                from ..oauth_session import get_oauth2_session_manager

                session_manager = get_oauth2_session_manager(self.config)

                # Revoke provider token (e.g., Google) stored in actor.store
                try:
                    token_data = session_manager.validate_access_token(token)
                    if token_data:
                        actor_id = token_data.get("actor_id")
                        if actor_id:
                            self._clear_provider_token_for_actor(actor_id)
                except Exception as lookup_error:
                    logger.debug(f"Provider token lookup during logout: {lookup_error}")

                # Revoke the ActingWeb session token
                session_manager.revoke_access_token(token)
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
            token = self.request.cookies.get(
                "access_token"
            ) or self.request.cookies.get("oauth_token")

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

    def _generate_actingweb_token(
        self, actor_id: str, identifier: str, chain_id: str | None = None
    ) -> str:
        """Generate an ActingWeb access token for an actor.

        When ``chain_id`` is provided (the refresh-token family this access token
        is being minted alongside, on rotation), the access token is tagged with
        it so that revoking the family on reuse detection also revokes this
        access token instead of letting it live out its full TTL.
        """
        # Use the config's token generation
        token = self.config.new_token()

        # Store token mapping
        try:
            from ..oauth_session import get_oauth2_session_manager

            session_manager = get_oauth2_session_manager(self.config)
            session_manager.store_access_token(
                token, actor_id, identifier, chain_id=chain_id
            )
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

    def _clear_provider_token_for_actor(self, actor_id: str) -> None:
        """
        Clear the stored OAuth provider token from the actor store on logout.

        Logout (and session-token revocation) ends the local ActingWeb session
        only; it must NOT call the identity provider's token-revocation
        endpoint. For Apple in particular, hitting ``/auth/revoke`` emails the
        user ("… has revoked access to sign in with your Apple account") and
        severs the Sign in with Apple grant — the next login re-prompts for
        name/email consent and the stored refresh token is invalidated.
        Provider-side revocation belongs to an explicit account-disconnect /
        delete flow, not to logout.

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
