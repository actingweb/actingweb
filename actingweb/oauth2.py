"""
OAuth2 authentication module for ActingWeb using oauthlib.

This module provides a comprehensive OAuth2 implementation using the standard oauthlib library,
supporting both Google OAuth2 and generic OAuth2 providers. It consolidates all OAuth2
functionality into a single, maintainable module.
"""

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import requests  # type: ignore[import-untyped]
from oauthlib.common import generate_token  # type: ignore[import-untyped]
from oauthlib.oauth2 import WebApplicationClient  # type: ignore[import-untyped]

from . import actor as actor_module
from . import config as config_class
from . import deletion
from .constants import ESTABLISHED_VIA_OAUTH2_INTERACTIVE
from .db.creator_rules import is_exempt, normalise_creator
from .db.exceptions import CreatorTaken, DbError
from .interface.actor_interface import ActorInterface
from .oauth2_id_token import JWKSIdTokenValidator

if TYPE_CHECKING:
    from .attribute import InternalStore
    from .interface.hooks import HookRegistry

logger = logging.getLogger(__name__)

# Simple cache for invalid tokens to avoid repeat network requests
_invalid_token_cache: dict[str, float] = {}
_INVALID_TOKEN_CACHE_TTL = 300  # 5 minutes

# Sensitive fields that must never be written to logs, even inside an error body.
_REDACT_FIELDS = ("client_assertion", "assertion", "id_token", "client_secret")


def _redact_token_response(text: str, *, limit: int = 500) -> str:
    """Redact sensitive fields and truncate an OAuth error body for logging.

    Token-exchange error bodies can echo back the request (including the Apple
    ES256 ``client_secret`` JWT or a submitted ``assertion``/``id_token``). We
    redact those before logging and cap the length to avoid leaking secrets.
    """
    if not text:
        return ""
    redacted = text[:limit]
    for field in _REDACT_FIELDS:
        # Match JSON ("field":"...") and form (field=...) shapes, value redacted.
        redacted = re.sub(
            rf'("{field}"\s*:\s*")[^"]*(")',
            r"\1<redacted>\2",
            redacted,
        )
        redacted = re.sub(
            rf"({field}=)[^&\s]*",
            r"\1<redacted>",
            redacted,
        )
    return redacted


class OAuth2Provider:
    """Base OAuth2 provider configuration."""

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.auth_uri = config.get("auth_uri", "")
        self.token_uri = config.get("token_uri", "")
        self.userinfo_uri = config.get("userinfo_uri", "")
        self.revocation_uri = config.get("revocation_uri", "")
        self.scope = config.get("scope", "")
        self.redirect_uri = config.get("redirect_uri", "")
        # Custom-scheme deep link for native-mobile flows that route through the
        # HTTPS callback and hand the app an opaque ticket (Apple-on-Android,
        # GitHub mobile). Empty for plain web/SPA providers. Read the generic key
        # first, falling back to the legacy Apple-specific key.
        self.mobile_deep_link = config.get("mobile_deep_link", "") or config.get(
            "apple_mobile_deep_link", ""
        )
        # Optional OIDC id_token validator (set by providers like Apple, or by
        # Google native when audiences are configured). None means this provider
        # validates identity via the userinfo endpoint instead.
        self.id_token_validator: JWKSIdTokenValidator | None = None

    def is_enabled(self) -> bool:
        """Check if provider is properly configured.

        A static ``client_secret`` is not required when the provider can validate
        id_tokens itself (``id_token_validator`` set, e.g. ``google-native`` used
        purely through the JWT-bearer grant). Such providers are still usable —
        and must be advertised by ``/oauth/config`` — without a secret.
        """
        has_credential = bool(self.client_secret) or self.id_token_validator is not None
        return bool(
            self.client_id and has_credential and self.auth_uri and self.token_uri
        )

    @property
    def display_name(self) -> str:
        """Human-friendly display name for this provider."""
        return get_provider_display_name(self.name)

    # ----- Strategy methods (overridden by provider subclasses) -----
    #
    # These carry all provider-specific behavior so that ``OAuth2Authenticator``
    # stays a thin orchestrator with no ``provider.name == "..."`` branches.

    def make_client_secret(self, time_bucket: int | None = None) -> str:
        """Return the client_secret value for token/refresh/revoke requests.

        Default: the static configured secret. Providers like Apple override
        this to mint a freshly-signed ES256 JWT.
        """
        return self.client_secret

    def authorize_extra_params(self, email_hint: str = "") -> dict[str, str]:
        """Provider-specific extra query parameters for the authorize URL."""
        return {}

    def authorize_prompt_params(self, requested: str) -> dict[str, str]:
        """Extra authorize parameters for a client-requested ``prompt``.

        Additive: ``consent`` is always sent (it is what yields a refresh
        token), and the client may add ``select_account``. Providers that do
        not support the value drop it (the default).
        """
        return {}

    def token_request_headers(self) -> dict[str, str]:
        """Headers for token-exchange / refresh requests."""
        return {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

    def userinfo_request_headers(self, access_token: str) -> dict[str, str]:
        """Headers for the userinfo request."""
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    def supports_refresh_tokens(self) -> bool:
        """Whether this provider issues usable refresh tokens."""
        return True

    def supports_revoke(self) -> bool:
        """Whether this provider supports token revocation."""
        return bool(self.revocation_uri)

    def extract_user_info_from_token_response(
        self, token_response: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Extract user info directly from the token response (e.g. an OIDC
        ``id_token``). Default ``None`` means "use the userinfo endpoint".
        """
        return None

    def extract_identifier_from_user_info(
        self, user_info: dict[str, Any]
    ) -> str | None:
        """Provider-specific stable identifier used when no email is available."""
        username = user_info.get("preferred_username", "")
        if username:
            return f"{self.name}:{username}".lower()
        return None

    def get_primary_email(self, access_token: str) -> str | None:
        """Provider-specific email fallback (e.g. GitHub's ``/user/emails``)."""
        return None

    def get_verified_emails(self, access_token: str) -> list[str] | None:
        """All verified emails the provider will vouch for, lowercased.

        Default: no provider-side verified-email listing API, so an empty
        list (distinct from ``None``, which means the lookup itself failed
        and the caller should not treat it as "no verified emails").
        """
        return []

    def store_provider_identity(self, store: Any, identifier: str) -> None:
        """Persist provider-specific identity fields on ``actor.store``."""
        return None

    def discovery_extras(self) -> dict[str, Any]:
        """Provider-specific additions to OIDC discovery metadata."""
        return {}


class GoogleOAuth2Provider(OAuth2Provider):
    """Google OAuth2 provider with specific configuration."""

    def __init__(
        self,
        config: config_class.Config,
        provider_config: dict[str, Any] | None = None,
    ):
        oauth_config = provider_config or config.oauth or {}
        # Only use redirect_uri from explicit provider_config (e.g. mobile apps),
        # not from config.oauth which has a different default path.
        custom_redirect = provider_config.get("redirect_uri") if provider_config else ""
        google_config = {
            "client_id": oauth_config.get("client_id", ""),
            "client_secret": oauth_config.get("client_secret", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "userinfo_uri": "https://www.googleapis.com/oauth2/v2/userinfo",
            "revocation_uri": "https://oauth2.googleapis.com/revoke",
            "scope": "openid email profile",
            "redirect_uri": custom_redirect
            or f"{config.proto}{config.fqdn}/oauth/callback",
        }
        super().__init__("google", google_config)

        # Native sign-in (google-native) validates the id_token directly against
        # Google's JWKS when acceptable audiences are configured.
        self.audiences: list[str] = list(
            (provider_config or {}).get("audiences", []) or []
        )
        if self.audiences:
            self.id_token_validator = JWKSIdTokenValidator(
                jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
                expected_iss=(
                    "accounts.google.com",
                    "https://accounts.google.com",
                ),
                audiences=self.audiences,
            )

    GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
    GOOGLE_EXPECTED_ISS = ("accounts.google.com", "https://accounts.google.com")

    def authorize_extra_params(self, email_hint: str = "") -> dict[str, str]:
        if email_hint:
            return {"login_hint": email_hint}
        return {}

    def authorize_prompt_params(self, requested: str) -> dict[str, str]:
        # Google takes a space-delimited list; consent stays so a refresh
        # token is still issued.
        return {"prompt": f"{requested} consent"}

    def extract_user_info_from_token_response(
        self, token_response: dict[str, Any]
    ) -> dict[str, Any] | None:
        # Only used for the native id_token path; the web flow has no id_token
        # validator and falls back to the userinfo endpoint.
        id_token = token_response.get("id_token")
        if not id_token or not self.id_token_validator:
            return None
        return self.id_token_validator.validate(id_token)

    def extract_identifier_from_user_info(
        self, user_info: dict[str, Any]
    ) -> str | None:
        # Google 'sub' claim is a stable unique identifier (never changes).
        sub = user_info.get("sub")
        if sub:
            return f"google:{sub}"
        return super().extract_identifier_from_user_info(user_info)

    def store_provider_identity(self, store: Any, identifier: str) -> None:
        if identifier.startswith("google:"):
            store.oauth_sub = identifier.split(":", 1)[1]

    def discovery_extras(self) -> dict[str, Any]:
        return {
            "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }


class GitHubOAuth2Provider(OAuth2Provider):
    """GitHub OAuth2 provider with specific configuration."""

    def __init__(
        self,
        config: config_class.Config,
        provider_config: dict[str, Any] | None = None,
    ):
        oauth_config = provider_config or config.oauth or {}
        custom_redirect = provider_config.get("redirect_uri") if provider_config else ""
        github_config = {
            "client_id": oauth_config.get("client_id", ""),
            "client_secret": oauth_config.get("client_secret", ""),
            "auth_uri": "https://github.com/login/oauth/authorize",
            "token_uri": "https://github.com/login/oauth/access_token",
            "userinfo_uri": "https://api.github.com/user",
            "scope": "user:email",
            "redirect_uri": custom_redirect
            or f"{config.proto}{config.fqdn}/oauth/callback",
            # Native-mobile deep link (github-mobile): the code is exchanged
            # server-side via the mobile_ticket grant; the app only sees a ticket.
            "mobile_deep_link": (oauth_config.get("mobile_deep_link", ""))
            if provider_config
            else "",
        }
        super().__init__("github", github_config)

    def token_request_headers(self) -> dict[str, str]:
        headers = super().token_request_headers()
        headers["User-Agent"] = "ActingWeb-OAuth2-Client"
        return headers

    def userinfo_request_headers(self, access_token: str) -> dict[str, str]:
        headers = super().userinfo_request_headers(access_token)
        headers["User-Agent"] = "ActingWeb-OAuth2-Client"
        return headers

    def supports_refresh_tokens(self) -> bool:
        return False

    def supports_revoke(self) -> bool:
        return False

    def extract_identifier_from_user_info(
        self, user_info: dict[str, Any]
    ) -> str | None:
        # GitHub user ID is most stable (doesn't change even if username changes).
        user_id = user_info.get("id")
        if user_id:
            return f"github:{user_id}"
        # Fallback to username (can change but better than nothing).
        login = user_info.get("login")
        if login:
            logger.warning(
                f"Using GitHub username '{login}' as identifier - this may change"
            )
            return f"github:{login}".lower()
        return super().extract_identifier_from_user_info(user_info)

    def store_provider_identity(self, store: Any, identifier: str) -> None:
        if identifier.startswith("github:"):
            store.oauth_github_id = identifier.split(":", 1)[1]

    def get_primary_email(self, access_token: str) -> str | None:
        return _get_github_primary_email(access_token)

    def get_verified_emails(self, access_token: str) -> list[str] | None:
        return _get_github_verified_emails(access_token)


class AppleOAuth2Provider(OAuth2Provider):
    """Sign in with Apple provider.

    Differs from generic OAuth2 in three ways handled here:
      - ``client_secret`` is a freshly-signed ES256 JWT (not a static string).
      - There is no userinfo endpoint; identity comes from the ``id_token``.
      - id_tokens are validated against Apple's JWKS (RS256).
    """

    AUTH_URI = "https://appleid.apple.com/auth/authorize"
    TOKEN_URI = "https://appleid.apple.com/auth/token"
    REVOCATION_URI = "https://appleid.apple.com/auth/revoke"
    JWKS_URI = "https://appleid.apple.com/auth/keys"
    EXPECTED_ISS = ("https://appleid.apple.com", "https://account.apple.com")

    def __init__(
        self,
        config: config_class.Config,
        provider_config: dict[str, Any] | None = None,
    ):
        prov = provider_config or {}
        custom_redirect = prov.get("redirect_uri", "")
        apple_config = {
            "client_id": prov.get("client_id", ""),
            "client_secret": "",  # minted on demand as an ES256 JWT
            "auth_uri": self.AUTH_URI,
            "token_uri": self.TOKEN_URI,
            "userinfo_uri": "",  # Apple has no userinfo endpoint
            "revocation_uri": self.REVOCATION_URI,
            "scope": prov.get("scope", "openid name email"),
            "redirect_uri": custom_redirect
            or f"{config.proto}{config.fqdn}/oauth/callback/apple",
        }
        # Provider name is "apple" for the web flow; mobile variants register
        # their own entry via the factory's prefix matching but reuse this class.
        super().__init__("apple", apple_config)

        self._provider_name = prov.get("_provider_name", "apple")
        self.team_id = prov.get("apple_team_id", "")
        self.key_id = prov.get("apple_key_id", "")
        self.audiences: list[str] = list(prov.get("audiences", []) or [])
        self._private_key_pem = prov.get("apple_private_key_pem", "")
        # Custom-scheme deep link for the Android Capacitor flow (apple-mobile).
        # Apple's redirect_uri stays HTTPS; this is only the final deep-link.
        # (base __init__ also reads these keys; set explicitly because Apple's
        # config dict above does not carry the deep-link key.)
        self.mobile_deep_link = prov.get("mobile_deep_link", "") or prov.get(
            "apple_mobile_deep_link", ""
        )

        # Register credentials for cached client_secret minting, and wire up the
        # id_token validator (fail-closed when audiences are unset).
        if self.team_id and self.key_id and self.client_id and self._private_key_pem:
            from . import oauth2_apple

            oauth2_apple.register_apple_credentials(
                self._provider_name,
                team_id=self.team_id,
                key_id=self.key_id,
                client_id=self.client_id,
                private_key_pem=self._private_key_pem,
            )

        self.id_token_validator = JWKSIdTokenValidator(
            jwks_uri=self.JWKS_URI,
            expected_iss=self.EXPECTED_ISS,
            audiences=self.audiences or ([self.client_id] if self.client_id else []),
            # Apple's native flow hashes the nonce (SHA256) into the token claim;
            # accept the raw nonce or its hash so callers pass one uniform value.
            nonce_hash_tolerant=True,
        )

    def is_enabled(self) -> bool:
        # Apple has no static client_secret; "enabled" means we can mint one.
        return bool(
            self.client_id
            and self.team_id
            and self.key_id
            and self._private_key_pem
            and self.auth_uri
            and self.token_uri
        )

    def make_client_secret(self, time_bucket: int | None = None) -> str:
        from . import oauth2_apple

        return oauth2_apple.get_client_secret(self._provider_name)

    def authorize_extra_params(self, email_hint: str = "") -> dict[str, str]:
        # Apple requires form_post when name/email scopes are requested.
        return {"response_mode": "form_post"}

    def supports_refresh_tokens(self) -> bool:
        return True

    def supports_revoke(self) -> bool:
        return True

    def extract_user_info_from_token_response(
        self, token_response: dict[str, Any]
    ) -> dict[str, Any] | None:
        id_token = token_response.get("id_token")
        if not id_token or not self.id_token_validator:
            return None
        return self.id_token_validator.validate(id_token)

    def extract_identifier_from_user_info(
        self, user_info: dict[str, Any]
    ) -> str | None:
        sub = user_info.get("sub")
        if sub:
            return f"apple:{sub}"
        return super().extract_identifier_from_user_info(user_info)

    def store_provider_identity(self, store: Any, identifier: str) -> None:
        if identifier.startswith("apple:"):
            store.oauth_sub = identifier.split(":", 1)[1]

    def discovery_extras(self) -> dict[str, Any]:
        return {
            "jwks_uri": self.JWKS_URI,
            "id_token_signing_alg_values_supported": ["RS256"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }


class OAuth2Authenticator:
    """
    Comprehensive OAuth2 authenticator using oauthlib.

    Handles the complete OAuth2 flow:
    1. Authorization URL generation
    2. Authorization code exchange for tokens
    3. Token validation and refresh
    4. User information retrieval
    5. Actor lookup/creation based on OAuth2 identity
    """

    def __init__(
        self, config: config_class.Config, provider: OAuth2Provider | None = None
    ):
        self.config = config
        self.provider = provider or GoogleOAuth2Provider(config)
        self.client = (
            WebApplicationClient(self.provider.client_id)
            if self.provider.is_enabled()
            else None
        )

        # Session and token management
        self._sessions: dict[str, dict[str, Any]] = {}

        if not self.provider.is_enabled():
            logger.warning(
                f"OAuth2 provider '{self.provider.name}' not configured - client_id and client_secret required"
            )

    def is_enabled(self) -> bool:
        """Check if OAuth2 is properly configured."""
        return self.provider.is_enabled()

    def create_authorization_url(
        self,
        state: str = "",
        redirect_after_auth: str = "",
        email_hint: str = "",
        trust_type: str = "",
        user_agent: str = "",
        code_challenge: str = "",
        code_challenge_method: str = "",
        prompt: str = "",
    ) -> str:
        """
        Create OAuth2 authorization URL using oauthlib with trust type selection.

        Args:
            state: State parameter to prevent CSRF attacks
            redirect_after_auth: Where to redirect after successful auth
            email_hint: Email to hint which account to use for authentication
            trust_type: Trust relationship type to establish (e.g., 'mcp_client', 'web_user')
            user_agent: User-Agent header for client identification and MCP coordination
            code_challenge: PKCE code challenge for SPA OAuth flows
            code_challenge_method: PKCE challenge method (typically "S256")
            prompt: Optional account-selection request (``select_account``),
                added to the always-sent ``consent`` for providers that
                support it; others ignore it

        Returns:
            OAuth2 authorization URL
        """
        if not self.is_enabled() or not self.client:
            return ""

        # Generate state if not provided
        if not state:
            state = generate_token()

        # Encode redirect URL, email hint, trust type, and user agent in state if provided
        # IMPORTANT: Don't overwrite encrypted MCP state (which is base64 encoded)
        if (
            redirect_after_auth or email_hint or trust_type or user_agent
        ) and not self._looks_like_encrypted_state(state):
            state_data = {
                "csrf": state,
                "redirect": redirect_after_auth,
                "expected_email": email_hint,  # Store original email for validation
                "trust_type": trust_type,  # Store trust type for automatic relationship creation
                "user_agent": user_agent[:100]
                if user_agent
                else "",  # Truncate user agent to prevent large state
            }
            state = json.dumps(state_data)

        # Prepare additional parameters for provider-specific features
        extra_params = {
            "access_type": "offline",  # For Google to get refresh token
            "prompt": "consent",  # Force consent to get refresh token
        }

        # Add provider-specific authorize params (e.g. Google's login_hint)
        extra_params.update(self.provider.authorize_extra_params(email_hint))
        if prompt:
            extra_params.update(self.provider.authorize_prompt_params(prompt))

        # Add PKCE parameters if provided (for SPA OAuth flows)
        if code_challenge and code_challenge_method:
            extra_params["code_challenge"] = code_challenge
            extra_params["code_challenge_method"] = code_challenge_method

        # Use oauthlib to generate the authorization URL
        authorization_url = self.client.prepare_request_uri(
            self.provider.auth_uri,
            redirect_uri=self.provider.redirect_uri,
            scope=self.provider.scope.split(),
            state=state,
            **extra_params,
        )

        return str(authorization_url)

    def _looks_like_encrypted_state(self, state: str) -> bool:
        """
        Check if state parameter looks like an encrypted MCP state.

        MCP states are base64-encoded encrypted data and won't be valid JSON.
        Standard ActingWeb states are JSON strings.

        Args:
            state: State parameter to check

        Returns:
            True if this looks like an encrypted MCP state
        """
        if not state:
            return False

        # If it starts with '{' it's likely JSON (standard ActingWeb state)
        if state.strip().startswith("{"):
            return False

        # If it contains only base64-safe characters and is reasonably long,
        # it's likely an encrypted MCP state

        if len(state) > 50 and re.fullmatch(r"[A-Za-z0-9+/_=-]+", state):
            return True

        return False

    def exchange_code_for_token(
        self,
        code: str,
        state: str = "",
        code_verifier: str | None = None,
        redirect_uri: str | None = None,
    ) -> dict[str, Any] | None:  # pylint: disable=unused-argument
        """
        Exchange authorization code for access token using oauthlib.

        Args:
            code: Authorization code from OAuth2 provider
            state: State parameter from callback
            code_verifier: PKCE code verifier (required if PKCE was used in authorization)
            redirect_uri: Override redirect_uri for the token exchange (e.g. for mobile apps)

        Returns:
            Token response from OAuth2 provider or None if failed
        """
        if not self.is_enabled() or not self.client or not code:
            return None

        # Prepare token request using oauthlib
        # Include code_verifier if PKCE was used
        prepare_kwargs: dict[str, Any] = {
            "code": code,
            "redirect_uri": redirect_uri or self.provider.redirect_uri,
            "client_id": self.provider.client_id,
            "client_secret": self.provider.make_client_secret(),
        }
        if code_verifier:
            prepare_kwargs["code_verifier"] = code_verifier

        token_request_body = self.client.prepare_request_body(**prepare_kwargs)

        headers = self.provider.token_request_headers()

        try:
            # Use requests library with better timeout and connection handling
            response = requests.post(
                url=self.provider.token_uri,
                data=token_request_body,
                headers=headers,
                timeout=(5, 15),  # (connect timeout, read timeout)
            )

            if response.status_code != 200:
                logger.error(
                    "OAuth2 token exchange failed: %s %s",
                    response.status_code,
                    _redact_token_response(response.text),
                )
                return None

            token_data = response.json()

            # Parse token response using oauthlib
            self.client.parse_request_body_response(response.text)

            return dict(token_data)

        except Exception as e:  # folds DbError: provider HTTP only
            logger.error(f"Exception during token exchange: {e}")
            return None

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any] | None:
        """
        Refresh access token using oauthlib.

        Args:
            refresh_token: OAuth2 refresh token

        Returns:
            New token response or None if failed
        """
        if not self.is_enabled() or not self.client or not refresh_token:
            return None

        # Prepare refresh request using oauthlib
        refresh_request_body = self.client.prepare_refresh_body(
            refresh_token=refresh_token,
            client_id=self.provider.client_id,
            client_secret=self.provider.make_client_secret(),
        )

        headers = self.provider.token_request_headers()

        # Some providers (e.g. GitHub) don't support refresh tokens
        if not self.provider.supports_refresh_tokens():
            logger.warning(
                f"Provider '{self.provider.name}' doesn't support refresh tokens "
                "- user will need to re-authenticate"
            )
            return None

        try:
            # Use requests library with better timeout and connection handling
            response = requests.post(
                url=self.provider.token_uri,
                data=refresh_request_body,
                headers=headers,
                timeout=(5, 15),  # (connect timeout, read timeout)
            )

            if response.status_code != 200:
                logger.error(
                    "OAuth2 token refresh failed: %s %s",
                    response.status_code,
                    _redact_token_response(response.text),
                )
                return None

            token_data = response.json()

            # Parse token response using oauthlib
            self.client.parse_request_body_response(response.text)

            return dict(token_data)

        except Exception as e:  # folds DbError: provider HTTP only
            logger.error(f"Exception during token refresh: {e}")
            return None

    def validate_token_and_get_user_info(
        self, access_token: str
    ) -> dict[str, Any] | None:
        """
        Validate access token and extract user information.

        Args:
            access_token: OAuth2 access token

        Returns:
            User information dict or None if validation failed
        """
        if not access_token or not self.provider.userinfo_uri:
            return None

        # Check cache for previously validated invalid tokens
        current_time = time.time()
        token_hash = hashlib.sha256(access_token.encode()).hexdigest()[:16]
        if token_hash in _invalid_token_cache:
            cache_time = _invalid_token_cache[token_hash]
            if current_time - cache_time < _INVALID_TOKEN_CACHE_TTL:
                logger.debug(
                    "Token found in invalid token cache - skipping network request"
                )
                return None

        headers = self.provider.userinfo_request_headers(access_token)

        try:
            # Use requests library with better timeout handling
            response = requests.get(
                url=self.provider.userinfo_uri,
                headers=headers,
                timeout=(5, 10),  # (connect timeout, read timeout)
            )

            if response.status_code != 200:
                logger.debug(
                    f"OAuth2 userinfo request failed: {response.status_code} "
                    f"{_redact_token_response(response.text)}"
                )
                # Cache this invalid token to avoid future network requests
                _invalid_token_cache[token_hash] = current_time
                return None

            userinfo = response.json()
            return dict(userinfo)

        except Exception as e:  # folds DbError: provider HTTP only
            logger.error(f"Exception during token validation: {e}")
            # Cache this invalid token to avoid future network requests
            _invalid_token_cache[token_hash] = current_time
            return None

    async def validate_token_and_get_user_info_async(
        self, access_token: str
    ) -> dict[str, Any] | None:
        """
        Async version: Validate access token and extract user information.

        Uses httpx for non-blocking HTTP requests, suitable for use within
        async handlers where blocking the event loop would cause issues.

        Args:
            access_token: OAuth2 access token

        Returns:
            User information dict or None if validation failed
        """
        if not access_token or not self.provider.userinfo_uri:
            return None

        # Check cache for previously validated invalid tokens
        current_time = time.time()
        token_hash = hashlib.sha256(access_token.encode()).hexdigest()[:16]
        if token_hash in _invalid_token_cache:
            cache_time = _invalid_token_cache[token_hash]
            if current_time - cache_time < _INVALID_TOKEN_CACHE_TTL:
                logger.debug(
                    "Token found in invalid token cache - skipping network request"
                )
                return None

        headers = self.provider.userinfo_request_headers(access_token)

        try:
            import httpx

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0)
            ) as client:
                response = await client.get(
                    url=self.provider.userinfo_uri,
                    headers=headers,
                )

            if response.status_code != 200:
                logger.debug(
                    f"OAuth2 userinfo request failed (async): {response.status_code} "
                    f"{_redact_token_response(response.text)}"
                )
                # Cache this invalid token to avoid future network requests
                _invalid_token_cache[token_hash] = current_time
                return None

            userinfo = response.json()
            return dict(userinfo)

        except ImportError:
            logger.warning("httpx not available, falling back to sync validation")
            return self.validate_token_and_get_user_info(access_token)
        except Exception as e:  # folds DbError: provider HTTP only
            logger.error(f"Exception during async token validation: {e}")
            # Cache this invalid token to avoid future network requests
            _invalid_token_cache[token_hash] = current_time
            return None

    def get_email_from_user_info(
        self,
        user_info: dict[str, Any],
        access_token: str | None = None,
        require_email: bool = False,
    ) -> str | None:
        """
        Extract email or unique provider identifier from user info.

        Behavior depends on require_email flag:
        - If True: Only return valid email addresses (respects force_email_prop_as_creator)
        - If False: Return provider-specific unique identifier if email unavailable

        Args:
            user_info: User information from OAuth2 provider
            access_token: OAuth2 access token (for additional API calls)
            require_email: If True, only return valid emails (not provider IDs)

        Returns:
            Email address or provider-specific identifier, or None if unavailable
        """
        if not user_info:
            return None

        # Always try to get email first (preferred for both modes)
        email = user_info.get("email")
        if email:
            return str(email).lower()

        # If email is required (force_email_prop_as_creator=True), try harder
        if require_email:
            if access_token:
                # Try a provider-specific email fallback (e.g. GitHub emails API)
                email = self.provider.get_primary_email(access_token)
                if email:
                    return email.lower()

            # If still no email and email is required, return None
            # This will trigger email input form
            return None

        # Email not required - use provider-specific unique identifier
        logger.info(
            f"Email not available, using provider-specific identifier for {self.provider.name}"
        )

        identifier = self.provider.extract_identifier_from_user_info(user_info)
        if identifier:
            return identifier

        # No identifier available
        logger.error(
            f"Failed to extract any identifier from {self.provider.name} user info"
        )
        return None

    def _get_github_primary_email(self, access_token: str) -> str | None:
        """Get primary email from GitHub's emails API.

        Backward-compat shim delegating to the module-level helper.
        """
        return _get_github_primary_email(access_token)

    def get_github_verified_emails(self, access_token: str) -> list[str] | None:
        """
        Fetch ALL verified emails from GitHub's emails API.

        Backward-compat shim delegating to ``self.provider.get_verified_emails``.
        Returns ``[]`` when GitHub answered with no verified emails, ``None``
        when the API call itself failed (non-200 or exception). Both existing
        in-package callers use truthiness, so this contract change (previously
        an empty result and a failed call were both ``None``) is safe for them.

        Args:
            access_token: GitHub OAuth access token

        Returns:
            List of verified email addresses (possibly empty), or None if the
            API call failed.
        """
        return self.provider.get_verified_emails(access_token)

    def lookup_or_create_actor_by_email(
        self,
        email: str,
        *,
        hooks: "HookRegistry | None" = None,
        create_only: bool = False,
        auth_method: str | None = None,
    ) -> actor_module.Actor | None:
        """
        Look up actor by email or create new one if not found.

        DEPRECATED: Use lookup_or_create_actor_by_identifier() instead.

        Args:
            email: User email from OAuth2 provider
            hooks: Lifecycle hooks to pass through to actor creation. When
                omitted, falls back to ``config._hooks`` (set by
                ``ActingWebApp.get_config()``); a handler built with a bare
                ``Config`` needs to pass this explicitly or ``actor_created``
                never fires.

        Returns:
            Actor instance or None if failed
        """
        return self.lookup_or_create_actor_by_identifier(
            email,
            user_info=None,
            hooks=hooks,
            create_only=create_only,
            auth_method=auth_method,
        )

    def lookup_or_create_actor_by_identifier(
        self,
        identifier: str,
        user_info: dict[str, Any] | None = None,
        *,
        hooks: "HookRegistry | None" = None,
        create_only: bool = False,
        auth_method: str | None = None,
    ) -> actor_module.Actor | None:
        """
        Look up actor by identifier (email or provider ID) or create new one if not found.

        An existing actor nobody vouched for (see :func:`is_vouched_actor`) is
        replaced or cleaned before it is returned; see :func:`adopt_actor`.

        Args:
            identifier: User identifier - can be email or provider-specific ID
            user_info: Optional user info for additional metadata storage
            hooks: Lifecycle hooks to pass through to actor creation. When
                omitted, falls back to ``config._hooks``.
            create_only: Refuse to adopt an existing actor. Returns ``None``
                if one already has this creator, instead of returning it.
                Used by the free-text branch of ``POST /oauth/email``, where
                adopting an existing actor is the vulnerability being closed:
                the caller's own existence probe runs before the session is
                claimed, leaving a window in which an *independent* login can
                create that actor first. Checking again here, immediately
                before the create, narrows that window to the gap between
                these two adjacent statements. Without
                ``with_unique_creator()`` it cannot close it, so this is a
                best-effort narrowing, not a guarantee; with the flag on the
                database refuses the second create (``CreatorTaken``, 409).
                See ``docs/migration/v3.16.rst``, "Creator uniqueness".
            auth_method: Marker written on a newly created actor. Defaults to
                ``"<provider>_oauth2"``; the self-asserted email form passes
                ``"email_unverified"``.

        Returns:
            Actor instance, or None if failed or refused under ``create_only``
        """
        if not identifier:
            return None

        effective_hooks = (
            hooks if hooks is not None else getattr(self.config, "_hooks", None)
        )

        try:
            # Use get_from_creator() method to find existing actor by identifier
            existing_actor = actor_module.Actor(config=self.config)
            if existing_actor.get_from_creator(identifier):
                if create_only:
                    logger.warning(
                        f"Refusing to adopt existing actor for identifier "
                        f"{identifier}: caller asked for create-only"
                    )
                    return None
                logger.info(f"Found existing actor for identifier: {identifier}")
                # Vouched actors only get the provider recorded; an actor
                # nobody vouched for is replaced or cleaned first.
                try:
                    return adopt_actor(
                        existing_actor,
                        provider=self.provider,
                        config=self.config,
                        hooks=effective_hooks,
                        user_info=user_info,
                    )
                except CreatorTaken:  # folds DbError: loads the swap's winner
                    if not self.config.unique_creator:
                        raise
                    # A concurrent sign-in replaced the same squatter first:
                    # look up once more and take its successor. A squatter
                    # renamed away leaves nobody, and the conflict stands.
                    winner = actor_module.Actor(config=self.config)
                    if (
                        not winner.get_from_creator(identifier)
                        or winner.id == existing_actor.id
                        or not _winner_is_marked(winner)
                    ):
                        raise
                    return adopt_actor(
                        winner,
                        provider=self.provider,
                        config=self.config,
                        hooks=effective_hooks,
                        user_info=user_info,
                    )

            # Create new actor with identifier as creator
            logger.info(f"Creating new actor for identifier: {identifier}")

            try:
                return _create_actor_for_identifier(
                    self.config,
                    self.provider,
                    identifier,
                    user_info,
                    effective_hooks,
                    auth_method=auth_method,
                )
            except CreatorTaken:  # folds DbError: loads the race winner
                if not self.config.unique_creator or create_only:
                    raise
                # A concurrent first sign-in (another tab, a retried callback)
                # created the actor between the lookup and this create: load
                # the winner, once, instead of answering a 409 to its owner.
                winner = actor_module.Actor(config=self.config)
                if not winner.get_from_creator(identifier) or not _winner_is_marked(
                    winner
                ):
                    raise
                logger.info(
                    f"Concurrent sign-in for {identifier} created actor "
                    f"{winner.id}; using it"
                )
                return adopt_actor(
                    winner,
                    provider=self.provider,
                    config=self.config,
                    hooks=effective_hooks,
                    user_info=user_info,
                )
            except DbError:
                raise

            except Exception as create_error:
                logger.error(
                    f"Failed to create actor for identifier {identifier}: {create_error}"
                )
                return None

        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Exception during actor lookup/creation for {identifier}: {e}"
            )
            return None

    def validate_email_from_state(self, state: str, authenticated_email: str) -> bool:
        from .oauth_state import validate_expected_email

        return validate_expected_email(state, authenticated_email)

    def authenticate_bearer_token(
        self, bearer_token: str
    ) -> tuple[actor_module.Actor | None, str | None]:
        """
        Authenticate Bearer token and return associated actor.

        Args:
            bearer_token: Bearer token from Authorization header

        Returns:
            Tuple of (Actor, email) or (None, None) if authentication failed
        """
        if not bearer_token:
            return None, None

        # Validate token and get user info
        user_info = self.validate_token_and_get_user_info(bearer_token)
        if not user_info:
            return None, None

        # Extract email from user info
        email = self.get_email_from_user_info(user_info, bearer_token)
        if not email:
            return None, None

        # Look up or create actor by email
        actor_instance = self.lookup_or_create_actor_by_email(email)
        if not actor_instance:
            return None, None

        return actor_instance, email

    def create_www_authenticate_header(self) -> str:
        """
        Create WWW-Authenticate header for OAuth2.

        Returns:
            WWW-Authenticate header value
        """
        if not self.is_enabled():
            return 'Bearer realm="ActingWeb"'

        # Include authorization URL in the header for client convenience
        auth_url = self.create_authorization_url()
        return f'Bearer realm="ActingWeb", authorization_uri="{auth_url}"'

    def store_session_data(self, session_id: str, data: dict[str, Any]) -> None:
        """Store session data for OAuth2 flow."""
        self._sessions[session_id] = data

    def get_session_data(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data for OAuth2 flow."""
        return self._sessions.get(session_id)

    def clear_session_data(self, session_id: str) -> None:
        """Clear session data after OAuth2 flow completion."""
        self._sessions.pop(session_id, None)

    def revoke_token(self, token: str) -> bool:
        """
        Revoke an OAuth2 access or refresh token.

        This method calls the provider's revocation endpoint to invalidate
        the token, ensuring it cannot be used for further authentication.

        Args:
            token: OAuth2 access token or refresh token to revoke

        Returns:
            True if revocation was successful, False otherwise
        """
        try:
            if not self.is_enabled():
                logger.warning("OAuth2 provider not enabled, cannot revoke token")
                return False

            if not token:
                logger.warning("No token provided for revocation")
                return False

            # Get the revocation endpoint from the provider
            revocation_url = self.provider.revocation_uri
            if not revocation_url:
                logger.warning(
                    f"Provider {self.provider.__class__.__name__} does not support token revocation"
                )
                return False

            # Prepare revocation request
            import requests

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "ActingWeb/1.0",
            }

            data = {"token": token, "client_id": self.provider.client_id}

            # Add client secret if available (for confidential clients).
            # Providers like Apple mint a fresh ES256 JWT here.
            client_secret = self.provider.make_client_secret()
            if client_secret:
                data["client_secret"] = client_secret

            # Make revocation request
            response = requests.post(
                revocation_url, data=data, headers=headers, timeout=10
            )

            # Google returns 200 for both successful revocations and already-invalid tokens
            # This is per RFC 7009 - revocation should be idempotent
            if response.status_code == 200:
                return True
            else:
                logger.warning(
                    f"Token revocation failed with status {response.status_code}: "
                    f"{_redact_token_response(response.text)}"
                )
                return False

        except Exception as e:  # folds DbError: provider HTTP only
            logger.error(f"Error during token revocation: {e}")
            return False


# Factory functions for backward compatibility and convenience


def _get_github_primary_email(access_token: str) -> str | None:
    """Get primary verified email from GitHub's emails API.

    Lives at module level so it can be reused by ``GitHubOAuth2Provider``
    without holding authenticator state.
    """
    if not access_token:
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "ActingWeb-OAuth2-Client",
    }

    try:
        # Use requests library with better timeout handling
        response = requests.get(
            url="https://api.github.com/user/emails",
            headers=headers,
            timeout=(5, 10),  # (connect timeout, read timeout)
        )

        if response.status_code != 200:
            logger.warning(f"GitHub emails API request failed: {response.status_code}")
            return None

        emails = response.json()

        # Find the primary email (must also be verified to prevent
        # account-linking attacks via unverified primary emails).
        for email_info in emails:
            if email_info.get("primary", False) and email_info.get("verified", False):
                email = email_info.get("email")
                return str(email) if email else None

        # If no verified primary email found, use the first verified email
        for email_info in emails:
            if email_info.get("verified", False):
                email = email_info.get("email")
                return str(email) if email else None

        return None

    except Exception as e:  # folds DbError: provider HTTP only
        logger.warning(f"Failed to get GitHub primary email: {e}")
        return None


def _get_github_verified_emails(access_token: str) -> list[str] | None:
    """Get all verified emails from GitHub's emails API.

    Lives at module level so it can be reused by ``GitHubOAuth2Provider``
    without holding authenticator state (mirrors ``_get_github_primary_email``).

    Returns ``[]`` when GitHub answered 200 with no verified emails (a
    legitimate "nothing to offer" result); ``None`` when the API call itself
    failed — a non-200 status (e.g. a 404 from a token whose scope omits
    ``user:email``) or a network exception — so callers can tell "GitHub
    vouches for nothing" apart from "we could not ask GitHub".
    """
    if not access_token:
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "ActingWeb-OAuth2-Client",
    }

    try:
        response = requests.get(
            url="https://api.github.com/user/emails",
            headers=headers,
            timeout=(5, 10),
        )

        if response.status_code != 200:
            logger.warning(f"GitHub emails API request failed: {response.status_code}")
            return None

        emails = response.json()

        verified = []
        for email_info in emails:
            if email_info.get("verified", False):
                email = email_info.get("email")
                if email:
                    verified.append(str(email).lower())

        logger.debug(f"Found {len(verified)} verified emails from GitHub")
        return verified

    except Exception as e:  # folds DbError: provider HTTP only
        logger.warning(f"Failed to get GitHub verified emails: {e}")
        return None


def _get_provider_config(
    config: config_class.Config, provider_name: str
) -> dict[str, Any] | None:
    """Look up per-provider credentials from ``config.oauth_providers``.

    Returns the provider's config dict, or ``None`` if not found
    (in which case the provider class will fall back to ``config.oauth``).
    """
    providers = getattr(config, "oauth_providers", {})
    return providers.get(provider_name)  # type: ignore[no-any-return]


# Display-name mapping for known OAuth providers.
_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "github": "GitHub",
    "google": "Google",
    "apple": "Apple",
    "apple-mobile": "Apple",
}

# Registry of provider classes, keyed by the base provider name (the part
# before any ``-`` suffix). Variants like ``google-mobile`` / ``github-mobile`` /
# ``apple-mobile`` / ``google-native`` resolve to the same class via prefix
# matching in the factory.
_PROVIDER_REGISTRY: dict[str, Callable[..., OAuth2Provider]] = {
    "google": GoogleOAuth2Provider,
    "github": GitHubOAuth2Provider,
    "apple": AppleOAuth2Provider,
}


def get_provider_display_name(name: str) -> str:
    """Return a human-friendly display name for an OAuth provider."""
    return _PROVIDER_DISPLAY_NAMES.get(name, name.capitalize())


def create_oauth2_authenticator(
    config: config_class.Config, provider_name: str = ""
) -> OAuth2Authenticator:
    """
    Factory function to create OAuth2 authenticator for the configured provider.

    Args:
        config: ActingWeb configuration
        provider_name: Provider name (auto-detected from config if not specified)

    Returns:
        OAuth2Authenticator configured for the specified provider
    """
    # Auto-detect provider from config if not specified
    if not provider_name:
        provider_name = getattr(config, "oauth2_provider", "google")

    prov_cfg = _get_provider_config(config, provider_name)

    # Built-in provider support (prefix match for variants like google-mobile,
    # github-mobile, google-native, apple-mobile). Default to Google if the
    # provider name is not recognized.
    base_name = provider_name.split("-", 1)[0]
    provider_cls = _PROVIDER_REGISTRY.get(base_name, GoogleOAuth2Provider)
    # Thread the concrete provider name through so providers like Apple can key
    # their per-variant credential registry (apple vs apple-mobile).
    if prov_cfg is not None:
        prov_cfg = {**prov_cfg, "_provider_name": provider_name}
    return OAuth2Authenticator(config, provider_cls(config, provider_config=prov_cfg))


def create_google_authenticator(config: config_class.Config) -> OAuth2Authenticator:
    """
    Factory function to create Google OAuth2 authenticator.

    Args:
        config: ActingWeb configuration

    Returns:
        OAuth2Authenticator configured for Google
    """
    prov_cfg = _get_provider_config(config, "google")
    return OAuth2Authenticator(
        config, GoogleOAuth2Provider(config, provider_config=prov_cfg)
    )


def create_github_authenticator(config: config_class.Config) -> OAuth2Authenticator:
    """
    Factory function to create GitHub OAuth2 authenticator.

    Args:
        config: ActingWeb configuration

    Returns:
        OAuth2Authenticator configured for GitHub
    """
    prov_cfg = _get_provider_config(config, "github")
    return OAuth2Authenticator(
        config, GitHubOAuth2Provider(config, provider_config=prov_cfg)
    )


def create_apple_authenticator(config: config_class.Config) -> OAuth2Authenticator:
    """
    Factory function to create a Sign in with Apple OAuth2 authenticator.

    Args:
        config: ActingWeb configuration

    Returns:
        OAuth2Authenticator configured for Apple
    """
    return create_oauth2_authenticator(config, "apple")


def create_generic_authenticator(
    config: config_class.Config, provider_config: dict[str, Any]
) -> OAuth2Authenticator:
    """
    Factory function to create generic OAuth2 authenticator.

    Args:
        config: ActingWeb configuration
        provider_config: OAuth2 provider configuration dict

    Returns:
        OAuth2Authenticator configured for generic provider
    """
    provider = OAuth2Provider("generic", provider_config)
    return OAuth2Authenticator(config, provider)


# Utility functions


def extract_bearer_token(auth_header: str) -> str | None:
    """
    Extract Bearer token from Authorization header.

    Args:
        auth_header: Authorization header value

    Returns:
        Bearer token or None if not found
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:].strip()


"""Legacy helpers removed: use actingweb.oauth_state.decode_state and validate_expected_email"""


def validate_redirect_url(redirect_url: str, allowed_domains: list[str]) -> bool:
    """
    Validate that redirect URL is safe (same domain or allowed).

    Args:
        redirect_url: URL to validate
        allowed_domains: List of allowed domains

    Returns:
        True if URL is safe to redirect to
    """
    if not redirect_url:
        return False

    try:
        parsed = urlparse(redirect_url)

        # Allow relative URLs (no scheme/netloc)
        if not parsed.scheme and not parsed.netloc:
            return True

        # Allow same domain and allowed domains
        if parsed.netloc in allowed_domains:
            return True

        return False

    except Exception:  # folds DbError: no DB access
        return False


def create_oauth2_trust_relationship(
    actor: ActorInterface,
    email: str,
    trust_type: str,
    oauth_tokens: dict[str, Any],
    established_via: str | None = None,
    client_id: str | None = None,
    client_name: str | None = None,
    client_version: str | None = None,
    client_platform: str | None = None,
) -> bool:
    """
    Create trust relationship after successful OAuth2 authentication.

    Args:
        actor: ActorInterface for the user's actor
        email: Authenticated user's email
        trust_type: Type of trust relationship to create
        oauth_tokens: OAuth2 tokens from authentication
        established_via: Optional override for how relationship was established
        client_id: Optional MCP client ID for unique identification per client
        client_name: Optional client application name
        client_version: Optional client application version
        client_platform: Optional client platform/user-agent info

    Returns:
        True if trust relationship was created successfully
    """
    try:
        # All OAuth2 trust relationships are established via OAuth2, regardless of trust type
        if established_via is None:
            established_via = ESTABLISHED_VIA_OAUTH2_INTERACTIVE

        # Delegate to TrustManager for unified behavior
        from .interface.trust_manager import TrustManager

        tm = TrustManager(actor.core_actor)
        return tm.create_or_update_oauth_trust(
            email=email,
            trust_type=trust_type,
            oauth_tokens=oauth_tokens,
            established_via=established_via,
            client_id=client_id,
            client_name=client_name,
            client_version=client_version,
            client_platform=client_platform,
        )
    except DbError:
        raise
    except Exception as e:
        logger.error(f"Error creating OAuth2 trust relationship: {e}")
        return False


def clear_pending_email_verification(
    actor_instance: actor_module.Actor, config: config_class.Config
) -> bool:
    """
    Clear squatted pending-verification state on a provider-verified login.

    A form-created actor left in ``email_verified == "false"`` (its typed
    address never clicked the verification link) can later be logged into
    by its real owner through a provider that *does* vouch for the same
    identifier (e.g. the identifier resolves via provider id, or a second
    provider login lands on the same creator). That login is authoritative;
    the leftover pending-verification token and index row are stale and
    would otherwise let the abandoned link keep "verifying" the actor.

    No-op unless ``store.email_verified == "false"``.

    Returns False when the pending flag was not confirmed gone: the actor
    still reads as unvouched (:func:`is_vouched_actor`).
    """
    if not actor_instance.store:
        return True
    if actor_instance.store.email_verified != "false":
        return True

    from .attribute import Attributes
    from .constants import ACTINGWEB_SYSTEM_ACTOR, EMAIL_VERIFY_TOKEN_INDEX_BUCKET

    token = actor_instance.store.email_verification_token
    if token:
        index = Attributes(
            actor_id=ACTINGWEB_SYSTEM_ACTOR,
            bucket=EMAIL_VERIFY_TOKEN_INDEX_BUCKET,
            config=config,
        )
        index.delete_attr(token)

    actor_instance.store.email_verification_token = None
    actor_instance.store.email_verification_created_at = None
    return actor_instance.store.set_confirmed("email_verified", None)


# ---------------------------------------------------------------------------
# Vouching and adoption
# ---------------------------------------------------------------------------

#: ``auth_method`` markers that say nobody vouched for the actor's creator: the
#: address was typed by whoever created the actor (or, for
#: ``creator_changed``, set later through ``PUT /<id>/trust/trustee``), not
#: proven by a provider.
UNVOUCHED_AUTH_METHODS = frozenset({"factory", "email_unverified", "creator_changed"})

#: Unvouched markers whose actor is deleted and recreated, not cleaned in
#: place. An actor made from unauthenticated input holds nothing legitimate.
REPLACE_AUTH_METHODS = frozenset({"factory"})


def _winner_is_marked(winner: actor_module.Actor) -> bool:
    """Whether a race winner a retry found carries its ``auth_method`` marker.

    ``Actor.create`` writes the marker before the row for a generated id,
    so a winner created by this version is always marked. An unmarked one
    is a pre-3.16 actor, a row an old flag-off process wrote, or a create
    whose answer was lost before its marker landed. Adopted, the adoption
    rule would clean it in place on the strength of a race; the conflict
    stands instead (409), and a plain sign-in decides it.
    """
    store = winner.store
    method = store.auth_method if store else None
    if isinstance(method, str) and method:
        return True
    if store is not None and not store.loaded:
        # The lazy load folds a fault into an empty bucket: a 503, not a
        # "creator taken" answer for a marker nobody could read.
        raise DbError("actor store read")
    logger.error(
        f"Actor {winner.id} won the race but carries no auth_method; "
        "the conflict stands"
    )
    return False


def is_vouched_actor(actor_instance: actor_module.Actor) -> bool:
    """Whether some party vouched for this actor's creator address.

    Vouched means ``auth_method`` is a non-empty string outside
    :data:`UNVOUCHED_AUTH_METHODS` **and** ``email_verified`` is not
    ``"false"`` (a pre-3.16 free-text actor carries ``"<provider>_oauth2"`` for
    an address the provider never verified). An actor with no marker, created
    before 3.16, is unvouched.
    """
    store = actor_instance.store
    if not store:
        return False
    return is_vouched_store(store, actor_instance.creator or "")


# The ``_internal`` attribute naming the address a vouched marker vouches
# for. Written beside every vouched marker; a creator changed since makes
# the vouch stale when it is read, whatever order concurrent writes landed
# in (a marker write cannot be conditioned on the actor row).
VOUCHED_CREATOR = "vouched_creator"


def is_vouched_store(store: "InternalStore", creator: str | None = None) -> bool:
    """:func:`is_vouched_actor` for an actor's ``_internal`` store.

    With ``creator`` (the actor's current creator, or the address a sign-in
    is resolving) the vouch must also be for that address: the recorded
    :data:`VOUCHED_CREATOR`, or the actor's own stored ``email`` (a provider
    or the emailed link wrote it). An actor vouched before 3.16 has no
    recorded address and is judged by its marker alone.
    """
    method = store.auth_method
    if not isinstance(method, str) or not method:
        return False
    if method in UNVOUCHED_AUTH_METHODS:
        return False
    if store.email_verified == "false":
        return False
    if creator is None:
        return True
    bound = getattr(store, VOUCHED_CREATOR, None)
    if not isinstance(bound, str) or not bound:
        return True  # vouched before the address was recorded
    current = normalise_creator(creator)
    if normalise_creator(bound) == current:
        return True
    email = store.email
    return isinstance(email, str) and "@" in current and email.lower() == current


MarkerClass = Literal["vouched", "unvouched", "replace"]


def classify_store(store: "InternalStore", creator: str | None = None) -> MarkerClass:
    """How the adoption rule treats an actor, from its loaded ``_internal``
    store: ``"vouched"``, ``"replace"`` (a marker in
    :data:`REPLACE_AUTH_METHODS`), or ``"unvouched"`` (cleaned in place).
    ``creator`` binds the vouch to that address (:func:`is_vouched_store`)."""
    if is_vouched_store(store, creator):
        return "vouched"
    if store.auth_method in REPLACE_AUTH_METHODS:
        return "replace"
    return "unvouched"


def classify_marker(
    config: config_class.Config, actor_id: str, creator: str | None = None
) -> MarkerClass | None:
    """:func:`classify_store` for an actor id; None when its ``_internal``
    bucket cannot be read (never raises). Every caller decides from this,
    so one unreadable bucket means the same thing everywhere: unknown."""
    from .attribute import InternalStore

    try:
        store = InternalStore(actor_id=actor_id, config=config)
        if not store.loaded:
            return None
        return classify_store(store, creator)
    except Exception as e:  # folds DbError: None means unreadable; every caller fails closed (raises, skips or retries)
        logger.warning(f"Could not read the marker of {actor_id}: {e}")
        return None


def _create_actor_for_identifier(
    config: config_class.Config,
    provider: "OAuth2Provider",
    identifier: str,
    user_info: dict[str, Any] | None,
    hooks: "HookRegistry | None",
    *,
    auth_method: str | None = None,
    replace_holder: str | None = None,
) -> actor_module.Actor:
    """Create an actor for a provider-proven identifier and seed its store.

    ``replace_holder`` (``with_unique_creator()``) moves the identifier from
    that actor to the new one in the same backend step.

    Raises on failure (``ActorInterface.create`` raises when nothing was
    persisted), ``CreatorTaken`` included.
    """
    actor_interface = ActorInterface.create(
        creator=identifier,
        config=config,
        passphrase="",  # ActingWeb will auto-generate
        hooks=hooks,
        auth_method=auth_method or f"{provider.name}_oauth2",
        replace_holder=replace_holder,
    )
    store = actor_interface.core_actor.store
    if store:
        store.created_at = str(int(time.time()))
        store.oauth_provider = provider.name

        # If identifier is provider-specific ID, store actual email separately
        if ":" in identifier and user_info:
            email = user_info.get("email")
            if email:
                store.email = email.lower()
                logger.debug(f"Stored display email for provider ID actor: {email}")

            # Store provider-specific ID for reference
            provider.store_provider_identity(store, identifier)
        elif "@" in identifier:
            # Identifier is an email - store it in email property too
            store.email = identifier

    return actor_interface.core_actor


def _revoke_all_actor_tokens(
    config: config_class.Config, actor_id: str, *, spa: bool = True
) -> int:
    """Revoke every SPA and MCP token of an actor. Raises if one cannot be.
    ``spa=False`` skips the SPA tokens, for a caller that revoked them for
    several actors in one pass (:func:`_revoke_spa_tokens`)."""
    from .oauth2_server.token_manager import get_actingweb_token_manager

    revoked = _revoke_spa_tokens(config, [actor_id]) if spa else 0
    revoked += get_actingweb_token_manager(config).revoke_actor_tokens(actor_id)
    return revoked


def _revoke_spa_tokens(config: config_class.Config, actor_ids: list[str]) -> int:
    """Revoke the SPA tokens of several actors in one pass over the system
    token buckets, which hold every user's tokens. Raises if one cannot be."""
    from .oauth_session import get_oauth2_session_manager

    return get_oauth2_session_manager(config).revoke_all_tokens_for_actors(
        actor_ids, strict=True
    )


def _actor_client_ids(config: config_class.Config, actor_id: str) -> list[str]:
    """Ids of the OAuth2 clients registered under an actor. Raises
    ``DbError`` if the bucket cannot be read (``list_clients_for_actor``
    answers a fault with an empty list)."""
    from . import attribute
    from .oauth2_server.client_registry import MCPClientRegistry

    bucket = attribute.Attributes(
        actor_id=actor_id,
        bucket=MCPClientRegistry(config).clients_bucket,
        config=config,
    )
    rows = bucket.get_bucket()  # strict: a fault raises DbError
    return sorted(str(k) for k in (rows or {}))


def _delete_actor_clients(
    config: config_class.Config, actor_id: str, client_ids: list[str]
) -> None:
    """Delete clients (row, index row, tokens). Call after the actor's trusts
    are gone: the registry's trust cleanup would otherwise notify the peer.
    Raises if a client could not be disabled."""
    from .oauth2_server.client_registry import MCPClientRegistry

    registry = MCPClientRegistry(config)
    for client_id in client_ids:
        if not registry.delete_client(client_id, actor_id=actor_id):
            raise RuntimeError(f"OAuth2 client {client_id} could not be deleted")


def _fire_lifecycle(
    hooks: "HookRegistry | None",
    event: str,
    actor_instance: actor_module.Actor | None,
    config: config_class.Config,
    **kwargs: Any,
) -> None:
    """Run a lifecycle hook; ``None`` hooks fire nothing, failures are logged.

    A ``DbError`` from ``actor_deleted``, which fires before the wipe, is
    raised: the sign-in fails before anything is removed. The replacement
    has already written its tombstone by then (on purpose, so callbacks the
    hook triggers are suppressed), and the next sign-in finishes it. One
    from a notification
    fired after the work committed (``actor_adopted``,
    ``actor_deleted_complete``) is logged: a 503 would tell the client to
    retry a sign-in that already completed.
    """
    if hooks is None:
        return
    try:
        wrapper = None
        if actor_instance is not None:
            registry = getattr(config, "service_registry", None)
            wrapper = ActorInterface(actor_instance, service_registry=registry)
        hooks.execute_lifecycle_hooks(event, wrapper, **kwargs)
    except DbError as e:
        if event in _POST_COMMIT_EVENTS:
            logger.error(f"Lifecycle hook {event} hit a store fault: {e}")
            return
        raise
    except Exception as e:
        logger.error(f"Lifecycle hook {event} failed: {e}")


_POST_COMMIT_EVENTS = frozenset({"actor_adopted", "actor_deleted_complete"})


def _remove_for_replacement(
    victim: actor_module.Actor,
    *,
    config: config_class.Config,
    hooks: "HookRegistry | None",
    creator: str,
    client_ids: list[str],
    spa_revoked: bool = False,
) -> int | None:
    """Delete an actor a sign-in replaces; return the tokens revoked.

    ``spa_revoked``: the caller already revoked its SPA tokens. Returns None
    when the row removal was not confirmed: the tombstone is written, so the
    next sign-in finishes it.
    """
    actor_id = victim.id or ""
    tokens_revoked = _revoke_all_actor_tokens(config, actor_id, spa=not spa_revoked)
    reason = {
        "reason": "replaced_at_adoption",
        "replaced_by_identifier": creator,
    }
    from . import subscription as subscription_module
    from . import trust as trust_module

    # Actor.delete reads these first, strictly; read them here too, before
    # the tombstone and the hook, so a fault raises DbError with nothing
    # written and actor_deleted not fired (the next sign-in retries). A fault
    # in actor_deleted itself comes after the tombstone, which the next
    # sign-in's replacement then finds and finishes.
    trust_module.Trusts(actor_id=actor_id, config=config).fetch()
    subscription_module.Subscriptions(actor_id=actor_id, config=config).fetch()
    deletion.mark_actor_deleted(actor_id, config)
    _fire_lifecycle(hooks, "actor_deleted", victim, config, **reason)
    if not victim.delete(notify_peers=False):
        logger.error(
            f"Adoption of actor {actor_id}: the backend did not confirm the "
            "row removed; the next sign-in finishes the replacement"
        )
        return None
    # The client rows went with the buckets, which already disables the
    # clients; this removes their index rows. Not fatal: the actor row is
    # gone, so failing here would skip the hooks below and leave nothing
    # for the next sign-in to resume.
    try:
        _delete_actor_clients(config, actor_id, client_ids)
    except Exception as e:  # folds DbError: client index cleanup after the actor row was removed; next sign-in cannot resume it
        logger.error(
            f"Adoption of actor {actor_id}: client index rows remain "
            f"after the replacement: {e}"
        )
    _fire_lifecycle(
        hooks, "actor_deleted_complete", None, config, actor_id=actor_id, **reason
    )
    return tokens_revoked


def _creator_rows(config: config_class.Config, creator: str) -> list[dict[str, Any]]:
    """The ids of the actors with this creator, as ``[{"id": ...}]`` from the
    index alone: no per-row read. A backend fault raises ``DbError``. The
    index can still list an actor deleted a moment ago; callers that act on
    a row read it first."""
    from .db import get_actor

    lookup = creator.lower() if "@" in creator else creator
    rows = get_actor(config).get_by_creator(creator=lookup, ids_only=True)
    if isinstance(rows, dict):
        rows = [rows]
    return [r for r in (rows or []) if r and r.get("id")]


def _factory_siblings(
    config: config_class.Config,
    creator: str,
    *,
    exclude: str,
    ids: list[str] | None = None,
    classes: dict[str, str] | None = None,
) -> list[str] | None:
    """The ids of up to :data:`SWEEP_LIMIT` other actors with this creator
    whose marker is in :data:`REPLACE_AUTH_METHODS`, lowest id first.

    ``ids`` and ``classes`` are the listing and the classification
    :meth:`Actor.get_from_creator` made; without them the actors are listed
    here. A listing that does not include ``exclude`` (the actor being
    replaced, which still exists) is incomplete, and returns None. Only the
    ids this returns are touched, so only they must be readable: each is
    loaded here, before anything is removed, and a fault raises ``DbError``.
    An unreadable marker is skipped and decided by the successor step, which
    creates nothing while it stays unreadable. Raises when the list itself
    cannot be read.
    """
    listed = (
        sorted(ids)
        if ids
        else sorted(str(r["id"]) for r in _creator_rows(config, creator))
    )
    if exclude not in listed:
        logger.error(
            f"Adoption for {creator!r}: actor {exclude} is missing from the "
            "actors with this creator; failing closed"
        )
        return None
    from .db import get_actor

    db_actor = get_actor(config)
    known = classes or {}
    siblings: list[str] = []
    for sibling_id in listed:
        if sibling_id == exclude:
            continue
        if len(siblings) >= SWEEP_LIMIT:
            break
        marker = known.get(sibling_id) or classify_marker(config, sibling_id)
        if marker != "replace":
            continue
        # Read before anything is removed: a fault raises DbError here, with
        # every actor still in place; None is a row deleted since the listing.
        if not db_actor.get(actor_id=sibling_id):
            continue
        siblings.append(sibling_id)
    return siblings


SWEEP_LIMIT = 10
"""Factory actors one sign-in removes. Each is a full wipe inside the
request; an open factory lets anyone add more, so later sign-ins go on."""


def _sweep_factory_actors(
    config: config_class.Config,
    hooks: "HookRegistry | None",
    creator: str,
    actor_ids: list[str],
) -> tuple[int, list[str]] | None:
    """Delete the ``factory`` actors a sign-in for ``creator`` found, at most
    :data:`SWEEP_LIMIT` (lowest ids first); return the tokens revoked and the
    ids removed, or None when one could not be removed (the next sign-in
    retries).

    Each marker is read when the SPA tokens are revoked (one pass for all)
    and again just before its actor is deleted: one vouched in between (the
    backfill) is kept.
    """
    pending = sorted(actor_ids)
    if len(pending) > SWEEP_LIMIT:
        logger.warning(
            f"Sweep for {creator!r}: {len(pending)} factory actors; removing "
            f"{SWEEP_LIMIT}, later sign-ins remove the rest"
        )
        pending = pending[:SWEEP_LIMIT]
    current: list[str] = []
    for sibling_id in pending:
        marker = classify_marker(config, sibling_id)
        if marker is None:
            logger.error(
                f"Sweep for {creator!r}: the marker of {sibling_id} could not "
                "be re-read; next sign-in retries"
            )
            return None
        if marker == "replace":
            current.append(sibling_id)
    if not current:
        return 0, []
    tokens_revoked = _revoke_spa_tokens(config, current)
    swept: list[str] = []
    for sibling_id in current:
        marker = classify_marker(config, sibling_id)
        if marker is None:
            logger.error(
                f"Sweep for {creator!r}: the marker of {sibling_id} could not "
                "be re-read; next sign-in retries"
            )
            return None
        if marker != "replace":
            continue  # vouched since the pass above (the backfill)
        sibling = actor_module.Actor(actor_id=sibling_id, config=config)
        if not sibling.id:
            from .deletion import DeletionStatus, get_deletion_status

            if get_deletion_status(sibling_id, config) == DeletionStatus.DELETED:
                continue  # deleted since it was listed
            logger.error(
                f"Sweep for {creator!r}: {sibling_id} could not be read; next "
                "sign-in retries"
            )
            return None
        removed = _remove_for_replacement(
            sibling,
            config=config,
            hooks=hooks,
            creator=creator,
            client_ids=_actor_client_ids(config, sibling_id),
            spa_revoked=True,
        )
        if removed is None:
            return None
        tokens_revoked += removed
        swept.append(sibling_id)
    return tokens_revoked, swept


def _replace_enforced(
    existing: actor_module.Actor,
    *,
    provider: "OAuth2Provider",
    config: config_class.Config,
    hooks: "HookRegistry | None",
    user_info: dict[str, Any] | None,
    client_ids: list[str],
) -> tuple[actor_module.Actor | None, list[dict[str, Any]], list[str], int]:
    """Replace a ``factory`` actor under ``with_unique_creator()``.

    The successor is created first, taking the creator from the squatter in
    the same backend step (:meth:`DbActorProtocol.replace_creator_holder`):
    one transaction moves the DynamoDB record, or renames the squatter to its
    ``#dup-`` value and inserts the successor on PostgreSQL. Only then is the
    squatter removed. There is no ranking, no sibling sweep and no second
    lookup: if the creator no longer names the squatter (a concurrent rename
    or sign-in), ``CreatorTaken`` propagates and the sign-in fails closed.

    ``actor_created`` for the successor therefore fires before
    ``actor_deleted`` for the squatter. If the removal fails after the swap,
    the squatter stays without the creator (``actingweb-unique-creators
    report`` lists it) and the sign-in fails closed; the next one finds the
    successor.

    Returns the successor (None when the removal was not confirmed), and the
    trusts, subscription peers and tokens the squatter lost.
    """
    from . import subscription as subscription_module
    from . import trust as trust_module

    actor_id = existing.id or ""
    creator = existing.creator or ""
    # The actor_adopted summary only: a fault leaves it empty.
    removed_trusts, subscription_peers = actor_module.relationship_summary(
        trust_module.Trusts(actor_id=actor_id, config=config).fetch(strict=False),
        subscription_module.Subscriptions(actor_id=actor_id, config=config).fetch(
            strict=False
        ),
    )
    try:
        successor = _create_actor_for_identifier(
            config, provider, creator, user_info, hooks, replace_holder=actor_id
        )
    except CreatorTaken:
        # The swap's own condition failed: the squatter was renamed, or a
        # concurrent sign-in swapped first and is removing it. Nothing was
        # written here; the caller looks up once more.
        raise
    except Exception:
        # The create failed after the swap committed (its marker or
        # trustee_root write): the squatter then no longer holds the creator
        # and must still go, or it would live on with its tokens.
        from .db import get_actor

        try:
            holder = get_actor(config).get_creator_holder(creator)
        except DbError:  # folds DbError: logged, then re-raised
            logger.error(
                f"Adoption of actor {actor_id}: whether the swap committed "
                "cannot be read; the squatter may still be live"
            )
            holder = None
        if holder is not None and holder != actor_id:
            logger.error(
                f"Adoption of actor {actor_id}: the successor {holder} took "
                "the creator but did not finish; removing the squatter"
            )
            try:
                _remove_for_replacement(
                    existing,
                    config=config,
                    hooks=hooks,
                    creator=creator,
                    client_ids=client_ids,
                )
            except Exception as e:  # folds DbError: logged; re-raised below
                logger.error(f"Adoption of actor {actor_id}: removal raised: {e}")
        raise
    removed = _remove_for_replacement(
        existing, config=config, hooks=hooks, creator=creator, client_ids=client_ids
    )
    if removed is None:
        logger.error(
            f"Adoption of actor {actor_id}: replaced by {successor.id}, but its "
            "removal was not confirmed; it no longer holds the creator"
        )
        return None, removed_trusts, subscription_peers, 0
    return successor, removed_trusts, subscription_peers, removed


def adopt_actor(
    existing: actor_module.Actor,
    *,
    provider: "OAuth2Provider | None",
    config: config_class.Config,
    hooks: "HookRegistry | None",
    user_info: dict[str, Any] | None = None,
    verified_by_email: bool = False,
) -> actor_module.Actor | None:
    """Apply the adoption rule to an actor a sign-in has just resolved.

    Called whenever a proof of the creator address (a provider login or the
    emailed verification link) lands on an existing actor. A vouched actor
    only has the provider recorded. An unvouched one is either

    * **replaced** when ``auth_method`` is in :data:`REPLACE_AUTH_METHODS`
      (and a provider is at hand to create the successor): deleted through the
      tested wipe and recreated, so the caller gets an actor with a *new id*; or
    * **cleaned in place**: passphrase rotated, every trust, subscription and
      token removed, data kept, and marked vouched.

    No request leaves the process: the peer URLs on an unvouched actor were
    chosen by whoever created it. Returns ``None`` when the adoption could
    not be completed, so the caller fails the sign-in closed and the next one
    retries. ``actor_adopted`` fires once on success. A backend fault raises
    ``DbError`` (``CreatorTaken`` included), which the integrations answer
    with 503 (409): the sign-in fails closed as "retry", not as a failed
    login.
    """
    try:
        return _adopt_actor(
            existing,
            provider=provider,
            config=config,
            hooks=hooks,
            user_info=user_info,
            verified_by_email=verified_by_email,
        )
    except DbError:
        raise
    except Exception as e:
        logger.error(
            f"Adoption of actor {getattr(existing, 'id', None)} failed: {e}",
            exc_info=True,
        )
        return None


def _adopt_actor(
    existing: actor_module.Actor,
    *,
    provider: "OAuth2Provider | None",
    config: config_class.Config,
    hooks: "HookRegistry | None",
    user_info: dict[str, Any] | None,
    verified_by_email: bool,
    carried: dict[str, Any] | None = None,
) -> actor_module.Actor | None:
    """``carried``: what a replacement already removed before handing the
    owner's own unvouched actor back here to be cleaned; reported with this
    adoption so ``actor_adopted`` names everything the sign-in removed."""
    store = existing.store
    if store is not None and not store.loaded:
        # A caught backend fault reads as "no marker", which would wipe a
        # vouched actor. Decide only from a read the backend answered.
        logger.error(
            f"Adoption of actor {existing.id}: its _internal bucket could not "
            "be read; failing the sign-in closed"
        )
        return None

    if is_vouched_actor(existing):
        if provider is not None and store:
            # Record the most recent provider on every sign-in (not only on
            # create) so revocation logic can rely on it. Bookkeeping: a
            # fault keeps the previous value and must not fail a sign-in that
            # nothing else blocked.
            try:
                store.oauth_provider = provider.name
            except DbError as e:  # folds DbError: provider bookkeeping write
                logger.error(
                    f"Sign-in to {existing.id}: recording the provider faulted: {e}"
                )
        if existing.factory_sibling_ids and existing.creator:
            # The lookup found factory actors beside this one. No lookup
            # reaches them, but each one costs every later sign-in a read;
            # the owner's sign-in removes them. Not fatal: the owner is in.
            try:
                if (
                    _sweep_factory_actors(
                        config, hooks, existing.creator, existing.factory_sibling_ids
                    )
                    is None
                ):
                    logger.error(
                        f"Sign-in to {existing.id}: factory actors beside it "
                        "remain; the next sign-in retries"
                    )
            except Exception as e:  # folds DbError: best-effort factory sweep after the sign-in succeeded; next sign-in retries
                logger.error(
                    f"Sign-in to {existing.id}: factory actors beside it remain: {e}"
                )
        # Nothing is pending here: a pending verification unvouches. A
        # tombstone is not read here: one left on a live actor (a DELETE
        # that stalled, a clear on create that faulted) must not wipe it.
        return existing

    from . import property as property_module
    from . import subscription as subscription_module
    from . import trust as trust_module
    from .deletion import DeletionStatus, get_deletion_status

    actor_id = existing.id or ""
    marker = store.auth_method if store else None
    previous = marker if isinstance(marker, str) and marker else "legacy"
    # A tombstone on an unvouched actor that still resolves is a wipe that
    # stopped part-way: a replacement (or a DELETE) whose buckets, the marker
    # among them, are already gone. Finish it rather than clean what is left
    # in place under a tombstone. UNKNOWN is not evidence of a wipe, so it
    # falls through to the marker: cleaning in place keeps the data.
    deletion_status = get_deletion_status(actor_id, config)
    unfinished_wipe = deletion_status == DeletionStatus.DELETED
    if unfinished_wipe and provider is None:
        logger.error(
            f"Adoption of actor {actor_id}: a deletion of it is unfinished and "
            "there is no provider to create its successor; failing closed"
        )
        return None
    replace = provider is not None and (
        previous in REPLACE_AUTH_METHODS or unfinished_wipe
    )
    provider_name = provider.name if provider is not None else None
    now = str(int(time.time()))
    tokens_revoked = 0
    swept_ids: list[str] = []
    # Read before anything is removed; a fault fails the sign-in here.
    client_ids = _actor_client_ids(config, actor_id)

    if replace and config.unique_creator and not is_exempt(existing.creator):
        assert provider is not None
        if deletion_status == DeletionStatus.UNKNOWN:
            # Enforced: whether the actor is mid-deletion cannot be told, so
            # nothing is swapped; the sign-in answers 503 and is retried.
            raise DbError("actor deletion status", actor_id)
        result, removed_trusts, subscription_peers, tokens_revoked = _replace_enforced(
            existing,
            provider=provider,
            config=config,
            hooks=hooks,
            user_info=user_info,
            client_ids=client_ids,
        )
        if result is None:
            return None
        if result.store:
            result.store.auth_method_adopted_from = previous
            result.store.auth_method_adopted_at = now
            result.store.auth_method_replaced_actor_id = actor_id
        property_names = []
        mode = "replaced"
    elif replace:
        assert provider is not None
        creator = existing.creator or ""
        # Every other factory actor for the same address goes too: an open
        # factory lets anyone create several, and replacing one per sign-in
        # would spread the owner's sign-ins over a new actor each time. Listed
        # before anything is removed, so a read fault fails the sign-in with
        # every actor still in place.
        siblings = _factory_siblings(
            config,
            creator,
            exclude=actor_id,
            ids=existing.creator_ids or None,
            classes=existing.creator_classes,
        )
        if siblings is None:
            return None
        # The actor_adopted summary only: a fault leaves it empty, not the
        # sign-in failed.
        removed_trusts, subscription_peers = actor_module.relationship_summary(
            trust_module.Trusts(actor_id=actor_id, config=config).fetch(strict=False),
            subscription_module.Subscriptions(actor_id=actor_id, config=config).fetch(
                strict=False
            ),
        )
        property_names: list[str] = []
        removed = _remove_for_replacement(
            existing, config=config, hooks=hooks, creator=creator, client_ids=client_ids
        )
        if removed is None:
            return None
        tokens_revoked = removed
        swept = _sweep_factory_actors(config, hooks, creator, siblings)
        if swept is None:
            return None
        tokens_revoked += swept[0]
        swept_ids = swept[1]
        # A concurrent first sign-in may already have created the successor,
        # and a vouched actor for the address may exist beside the factory
        # ones (get_from_creator prefers it). This narrows the race to the
        # gap between two statements; with with_unique_creator() off nothing
        # in the database enforces one actor per creator (the enforced path
        # is the branch above; docs/migration/v3.16.rst, "Creator uniqueness").
        # A new actor is created only when every actor left is a factory one
        # (BR): one whose marker cannot be read fails the sign-in, since a new
        # vouched actor would outrank the owner's unvouched one for good. The
        # ids are listed again (index only, no per-row read) because a
        # concurrent first sign-in may have created one since the listing;
        # actors the listing classified keep their class, new ones are read.
        removed_ids = {actor_id, *swept_ids}
        known = existing.creator_classes
        remaining: dict[str, str] = {}
        from .db import get_actor as _get_db_actor

        db_actor = _get_db_actor(config)
        for row in _creator_rows(config, creator):
            rid = str(row["id"])
            if rid in removed_ids or rid in remaining:
                continue
            if rid in known:
                remaining[rid] = known[rid]
                continue
            if not db_actor.get(actor_id=rid):
                continue  # deleted since the index listed it
            marker = classify_marker(config, rid, creator)
            if marker is None:
                logger.error(
                    f"Adoption of actor {actor_id}: the marker of {rid} for "
                    f"{creator!r} could not be read; next sign-in retries"
                )
                return None
            remaining[rid] = marker
        marker_class: str | None = None
        successor = actor_module.Actor(config=config)
        for wanted in ("vouched", "unvouched"):
            picks = sorted(i for i, c in remaining.items() if c == wanted)
            if not picks:
                continue
            successor = actor_module.Actor(actor_id=picks[0], config=config)
            if not (
                successor.id and successor.store is not None and successor.store.loaded
            ):
                logger.error(
                    f"Adoption of actor {actor_id}: actor {picks[0]} for "
                    f"{creator!r} remains but could not be read; next sign-in "
                    "retries"
                )
                return None
            marker_class = wanted
            break
        if marker_class == "vouched":
            result = successor
            if result.store is not None:
                result.store.oauth_provider = provider.name
        elif marker_class == "unvouched":
            # The owner's own unvouched actor (from before 3.16, or the email
            # form's) sat beside the factory ones: clean it in place instead
            # of leaving it, and its data, behind a new actor.
            return _adopt_actor(
                successor,
                provider=provider,
                config=config,
                hooks=hooks,
                user_info=user_info,
                verified_by_email=verified_by_email,
                carried={
                    "replaced_ids": [actor_id, *swept_ids],
                    "removed_trusts": removed_trusts,
                    "subscription_peers": subscription_peers,
                    "tokens_revoked": tokens_revoked,
                    "client_ids": client_ids,
                },
            )
        else:
            # Nothing left, or only a factory actor created since the listing
            # (the owner's next sign-in sweeps it).
            result = _create_actor_for_identifier(
                config, provider, creator, user_info, hooks
            )
            if result.store:
                result.store.auth_method_adopted_from = previous
                result.store.auth_method_adopted_at = now
                result.store.auth_method_replaced_actor_id = actor_id
        mode = "replaced"
    else:
        new_passphrase = config.new_token()
        if not new_passphrase:
            logger.error(f"Adoption of actor {actor_id} aborted: empty passphrase")
            return None
        # Rotate first: even if everything after this fails, the creator's
        # passphrase no longer opens the actor. Then revoke the sessions, so
        # nothing the creator holds can add a relationship during the wipe.
        if not existing.modify(passphrase=new_passphrase):
            logger.error(f"Adoption of actor {actor_id}: passphrase rotation failed")
            return None
        tokens_revoked = _revoke_all_actor_tokens(config, actor_id)
        # The actor_adopted summary only (strict=False).
        fetched = property_module.Properties(actor_id=actor_id, config=config).fetch(
            strict=False
        )
        property_names = (
            sorted(str(k) for k in fetched) if isinstance(fetched, dict) else []
        )
        purged = existing.purge_relationships(notify_peers=False)
        if not purged["confirmed"]:
            logger.error(
                f"Adoption of actor {actor_id}: trusts or subscriptions remain "
                "after the wipe; actor left unvouched, next sign-in retries"
            )
            return None
        # After the purge: with the client trusts gone, the registry's trust
        # cleanup has nothing left to notify.
        _delete_actor_clients(config, actor_id, client_ids)
        removed_trusts = purged["trusts"]
        subscription_peers = purged["subscription_peers"]
        if store:
            # What the previous creator left in _internal goes on every clean,
            # each removal confirmed before the marker vouches:
            # - its provider tokens: a provider sign-in writes its own
            #   afterwards, but only those it got (often no refresh token on a
            #   repeat consent, no access token on the native JWT-bearer
            #   grant), and the emailed link proves the address, not that
            #   provider account;
            # - trustee_root, which it chose (the factory body, or
            #   PUT /<id>/trust/trustee) and the actor would keep publishing.
            # The stored email becomes the proven address, so a later load
            # under force_email_prop_as_creator cannot hand the actor back to
            # an address the previous creator wrote.
            resets: dict[str, str | None] = {
                "oauth_token": None,
                "oauth_refresh_token": None,
                "oauth_token_expiry": None,
                "oauth_token_timestamp": None,
                "trustee_root": None,
            }
            # A provider-id creator ("apple:…") has no address of its own: the
            # provider's email when it gave one, else none.
            proven_email = (
                (existing.creator or "").lower()
                if "@" in (existing.creator or "")
                else str((user_info or {}).get("email") or "").lower() or None
            )
            resets["email"] = proven_email
            # The address this sign-in proves, written before the vouched
            # marker: a rename landing during the clean leaves the vouch
            # stale instead of vouching the new address.
            resets[VOUCHED_CREATOR] = normalise_creator(existing.creator)
            for name, value in resets.items():
                if value is None and getattr(store, name, None) is None:
                    continue  # not there (the bucket read answered)
                if not store.set_confirmed(name, value):
                    logger.error(
                        f"Adoption of actor {actor_id}: {name} could not be "
                        "reset; actor left unvouched, next sign-in retries"
                    )
                    return None
            if not store.set_confirmed(
                "auth_method",
                f"{provider_name}_oauth2" if provider_name else "email_verified",
            ):
                logger.error(
                    f"Adoption of actor {actor_id}: the vouched marker did not "
                    "land; actor left unvouched, next sign-in retries"
                )
                return None
            store.auth_method_adopted_from = previous
            store.auth_method_adopted_at = now
            if provider_name:
                store.oauth_provider = provider_name
        if not verified_by_email and not clear_pending_email_verification(
            existing, config
        ):
            # The marker vouches, but a pending flag still unvouches the
            # actor: every later sign-in would clean it again.
            logger.error(
                f"Adoption of actor {actor_id}: the pending email verification "
                "could not be cleared; next sign-in retries"
            )
            return None
        result = existing
        mode = "cleaned"

    if carried:
        removed_trusts = [*carried["removed_trusts"], *removed_trusts]
        subscription_peers = [*carried["subscription_peers"], *subscription_peers]
        tokens_revoked += carried["tokens_revoked"]
        client_ids = [*carried["client_ids"], *client_ids]
        swept_ids = [*carried["replaced_ids"], *swept_ids]
    logger.warning(
        f"Adopted unvouched actor {actor_id} (was {previous!r}) via "
        f"{provider_name or 'email verification'}: mode={mode}, "
        f"trusts={len(removed_trusts)}, subscriptions={len(subscription_peers)}, "
        f"tokens={tokens_revoked}, clients={len(client_ids)}, "
        f"properties={len(property_names)}, "
        f"peers={[t['peerid'] for t in removed_trusts][:10]}, "
        f"siblings={swept_ids}"
    )
    _fire_lifecycle(
        hooks,
        "actor_adopted",
        result,
        config,
        previous_auth_method=previous,
        previous_actor_id=actor_id if replace else None,
        provider=provider_name,
        mode=mode,
        removed_trusts=removed_trusts,
        removed_subscription_peers=subscription_peers,
        tokens_revoked=tokens_revoked,
        removed_client_ids=client_ids,
        property_names=property_names,
        removed_sibling_ids=swept_ids,
    )
    return result
