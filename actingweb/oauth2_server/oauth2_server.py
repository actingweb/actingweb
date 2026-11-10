"""
OAuth2 Authorization Server implementation for ActingWeb MCP clients.

This module implements ActingWeb as a full OAuth2 authorization server that
can issue its own tokens to MCP clients while proxying user authentication
to Google OAuth2.
"""

import logging
import re
import secrets
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from ..db.exceptions import DbError
from ..oauth2 import create_oauth2_authenticator
from ..secret_compare import secret_equals
from .client_registry import get_mcp_client_registry
from .state_manager import get_oauth2_state_manager
from .token_manager import get_actingweb_token_manager

if TYPE_CHECKING:
    from .. import config as config_class

logger = logging.getLogger(__name__)

# RFC 7636 §4.2: a code_challenge is 43-128 unreserved characters.
_PKCE_CHALLENGE_RE = re.compile(r"[A-Za-z0-9._~-]{43,128}")


class ActingWebOAuth2Server:
    """
    ActingWeb OAuth2 Authorization Server for MCP clients.

    This server implements standard OAuth2 endpoints:
    - /oauth/register - Dynamic client registration (RFC 7591)
    - /oauth/authorize - Authorization endpoint
    - /oauth/token - Token endpoint
    - /oauth/callback - Google OAuth2 callback handler
    - /.well-known/oauth-authorization-server - Discovery endpoint
    """

    def __init__(self, config: "config_class.Config"):
        self.config = config
        self.client_registry = get_mcp_client_registry(config)
        self.token_manager = get_actingweb_token_manager(config)
        self.state_manager = get_oauth2_state_manager(config)

        # OAuth2 authenticators are created on demand (and cached) so that any
        # configured provider — including Apple — is reachable without being
        # pre-instantiated for a fixed set of providers.
        self._authenticator_cache: dict[str, Any] = {}

        if (
            not self._get_authenticator("google").is_enabled()
            and not self._get_authenticator("github").is_enabled()
            and not self._get_authenticator("apple").is_enabled()
        ):
            logger.warning(
                "OAuth2 not configured - MCP OAuth2 server will not work properly"
            )

    def _get_authenticator(self, provider_name: str) -> Any:
        """Lazily create and cache an OAuth2 authenticator for ``provider_name``."""
        if provider_name not in self._authenticator_cache:
            self._authenticator_cache[provider_name] = create_oauth2_authenticator(
                self.config, provider_name
            )
        return self._authenticator_cache[provider_name]

    @property
    def google_authenticator(self) -> Any:
        """Backward-compat accessor (kept for existing call sites/tests)."""
        return self._get_authenticator("google")

    @property
    def github_authenticator(self) -> Any:
        """Backward-compat accessor (kept for existing call sites/tests)."""
        return self._get_authenticator("github")

    def handle_client_registration(
        self, registration_data: dict[str, Any], actor_id: str | None = None
    ) -> dict[str, Any]:
        """
        Handle dynamic client registration (RFC 7591).

        Args:
            registration_data: Client registration request
            actor_id: Actor to associate the client with (if known)

        Returns:
            Client registration response
        """
        try:
            # For MCP, we need an actor context
            # If no actor_id provided, we'll need to determine it from the request context
            if not actor_id:
                # An anonymous registration (RFC 7591): the client lives on the
                # OAuth2 system actor, and a user grants it a level later, at
                # sign-in. It may not choose its own level or a grant that
                # needs no user (3.16).
                registration_data = self._anonymous_registration(registration_data)
                from .system_actor import ensure_oauth2_system_actor

                actor_id = ensure_oauth2_system_actor(self.config)

            # Register the client
            response = self.client_registry.register_client(actor_id, registration_data)

            logger.debug(
                f"Registered MCP client {response['client_id']} for actor {actor_id}"
            )
            return response

        except ValueError as e:
            raise ValueError(f"Client registration failed: {str(e)}") from e
        except DbError:
            # A store fault is not a bad registration request (400).
            raise
        except Exception as e:
            logger.error(f"Client registration error: {e}")
            raise ValueError("Internal server error during client registration") from e

    def _anonymous_registration(
        self, registration_data: dict[str, Any]
    ) -> dict[str, Any]:
        """An anonymous registration's data as stored (3.16): a requested
        ``trust_type`` the client list does not accept, or ``grant_types``
        asking for ``client_credentials``, is refused (``ValueError``, a 400
        ``invalid_client_metadata``); the client's row on the system actor is
        always the default client type, the requested one kept as
        ``requested_trust_type``. An owner creates a client with another
        level or ``client_credentials`` through
        ``OAuth2ClientManager.create_client``."""
        from ..permission_integration import (
            client_trust_type_acceptable,
            default_client_trust_type,
        )

        requested = registration_data.get("trust_type")
        if requested and not client_trust_type_acceptable(self.config, requested):
            raise ValueError(
                f"trust_type {requested!r} is not offered to clients; an "
                "actor's owner creates such a client with "
                "OAuth2ClientManager.create_client"
            )
        grants = registration_data.get("grant_types") or []
        if isinstance(grants, list) and "client_credentials" in grants:
            raise ValueError(
                "client_credentials is not offered to an anonymously "
                "registered client; an actor's owner creates such a client "
                "with OAuth2ClientManager.create_client"
            )
        default = default_client_trust_type(self.config)
        if not default:
            raise ValueError("no trust type is offered to clients")
        data = dict(registration_data)
        data["trust_type"] = default
        if requested:
            data["requested_trust_type"] = requested
        return data

    def handle_authorization_request(
        self, params: dict[str, Any], method: str = "GET"
    ) -> dict[str, Any]:
        """
        Handle OAuth2 authorization request.

        For GET: Show email form (same as GET /)
        For POST: Process email and redirect to Google

        Args:
            params: Request parameters
            method: HTTP method (GET or POST)

        Returns:
            Response dict with action to take
        """
        try:
            client_id = params.get("client_id")
            redirect_uri = params.get("redirect_uri")
            response_type = params.get("response_type", "code")
            params.get("scope", "")
            state = params.get("state", "")
            code_challenge = params.get("code_challenge") or None
            code_challenge_method = params.get("code_challenge_method") or None

            # Validate required parameters
            if not client_id:
                return self._error_response("invalid_request", "client_id is required")

            if not redirect_uri:
                return self._error_response(
                    "invalid_request", "redirect_uri is required"
                )

            if response_type != "code":
                return self._error_response(
                    "unsupported_response_type",
                    "Only 'code' response type is supported",
                )

            # Validate client and redirect URI
            client_data = self.client_registry.validate_client(client_id)
            if not client_data:
                return self._error_response("invalid_client", "Invalid client_id")

            if not self.client_registry.validate_redirect_uri(client_id, redirect_uri):
                return self._error_response("invalid_request", "Invalid redirect_uri")

            # PKCE validation. This authorize path binds S256 only, as the
            # metadata advertises; an absent method is refused rather than
            # defaulted to plain (RFC 7636 §4.3). Exchange still accepts a
            # stored "plain" challenge created directly through
            # TokenManager.create_authorization_code.
            if code_challenge:
                if code_challenge_method != "S256":
                    return self._error_response(
                        "invalid_request",
                        "code_challenge_method must be S256; plain is not accepted",
                    )
                if not _PKCE_CHALLENGE_RE.fullmatch(str(code_challenge)):
                    return self._error_response(
                        "invalid_request",
                        "code_challenge must be 43-128 characters of [A-Za-z0-9._~-]",
                    )
            elif client_data.get("token_endpoint_auth_method") == "none":
                # For public clients (auth method "none"), PKCE is required
                return self._error_response(
                    "invalid_request", "code_challenge required for public clients"
                )

            if method == "GET":
                # Show email form (same UX as GET /). The nonce binds the
                # sign-in to the browser that shows the form (3.16): the
                # caller sets it as a cookie and puts it in the form.
                return {
                    "action": "show_form",
                    "form_nonce": secrets.token_urlsafe(24),
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": code_challenge_method,
                    "client_name": client_data.get("client_name", "MCP Client"),
                }

            elif method == "POST":
                # Get email and provider from form submission
                email = params.get("email", "").strip()
                provider = params.get("provider", "").strip()

                # Email is required if no provider specified (old email form flow)
                # Provider is required if no email specified (new OAuth button flow)
                if not email and not provider:
                    return self._error_response(
                        "invalid_request", "Email or provider is required"
                    )

                # Get trust type from form submission: one the client list
                # accepts, and the client's own allowed_trust_types when it
                # has them (3.16; any registered type was taken).
                from ..permission_integration import (
                    client_trust_type_acceptable,
                    default_client_trust_type,
                )

                trust_type = (params.get("trust_type") or "").strip() or (
                    default_client_trust_type(self.config) or ""
                )
                per_client = client_data.get("allowed_trust_types")
                if not client_trust_type_acceptable(self.config, trust_type) or (
                    isinstance(per_client, list) and trust_type not in per_client
                ):
                    logger.warning(
                        f"Authorization for client {client_id} asked for trust "
                        f"type {trust_type!r}, which is not offered; declined"
                    )
                    return self._error_response(
                        "access_denied", "The requested access level is not offered"
                    )

                # Create state with MCP context including PKCE parameters and trust type
                mcp_state = self.state_manager.create_mcp_state(
                    client_id=client_id,
                    original_state=state,
                    redirect_uri=redirect_uri,
                    email_hint=email if email else None,
                    trust_type=trust_type,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    provider=provider,
                    form_nonce=(params.get("form_nonce") or "").strip() or None,
                )

                # Create OAuth2 authorization URL based on provider
                oauth_url = None
                if provider == "apple" or provider.startswith("apple-"):
                    # Apple uses response_mode=form_post (cross-site POST). The
                    # encrypted MCP state cannot ride in that POST safely, so we
                    # wrap it in a server-side single-use nonce carrying the
                    # mcp_context; /oauth/callback/apple consumes it and dispatches
                    # back to the MCP completion path.
                    from ..oauth_state_store import StateNonceStore

                    nonce = StateNonceStore(self.config).create(
                        {"provider": provider, "mcp_state": mcp_state}
                    )
                    oauth_url = self._get_authenticator(
                        provider
                    ).create_authorization_url(
                        state=nonce,
                        redirect_after_auth="",
                        email_hint=email if email else "",
                    )
                elif provider == "github":
                    # GitHub OAuth flow
                    oauth_url = self._get_authenticator(
                        "github"
                    ).create_authorization_url(
                        state=mcp_state,
                        redirect_after_auth="",
                        email_hint=email if email else "",
                    )
                else:
                    # Default to Google OAuth (or when email is provided)
                    # For MCP flows, we need to use a special method that preserves the encrypted state
                    oauth_url = self._create_google_oauth_url_for_mcp(
                        mcp_state, email if email else ""
                    )

                    if not oauth_url:
                        logger.error(
                            "Failed to create MCP Google OAuth2 URL, falling back to standard method"
                        )
                        # Fallback to standard method
                        oauth_url = self.google_authenticator.create_authorization_url(
                            state=mcp_state,
                            redirect_after_auth="",
                            email_hint=email if email else "",
                        )

                if not oauth_url:
                    return self._error_response(
                        "server_error", "Failed to create authorization URL"
                    )

                return {"action": "redirect", "url": oauth_url}

            else:
                return self._error_response("invalid_request", "Method not allowed")

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Authorization request error: {e}")
            return self._error_response("server_error", "Internal server error")

    def handle_oauth_callback(
        self,
        params: dict[str, Any],
        *,
        form_nonce_cookie: str | None = None,
        decide_trust: Any = None,
    ) -> dict[str, Any]:
        """
        Handle OAuth2 callback from Google.

        This completes the MCP client authorization by:
        1. Validating the Google OAuth2 callback
        2. Extracting MCP context from state
        3. Creating authorization code for MCP client
        4. Redirecting back to MCP client

        Args:
            params: Callback parameters from Google

        Returns:
            Response dict with redirect to MCP client
        """
        try:
            code = params.get("code")
            state = params.get("state")
            error = params.get("error")

            # Handle OAuth2 errors
            if error:
                logger.warning(f"Google OAuth2 error: {error}")
                return self._error_response(
                    "access_denied", f"Google OAuth2 error: {error}"
                )

            if not code or not state:
                return self._error_response(
                    "invalid_request", "Missing code or state parameter"
                )

            # Extract MCP context from state
            mcp_context = self.state_manager.extract_mcp_context(state)
            if not mcp_context:
                logger.warning(
                    "Failed to extract MCP context from state - invalid or expired"
                )
                return self._error_response(
                    "invalid_request", "Invalid or expired state parameter"
                )

            client_id = mcp_context.get("client_id")
            redirect_uri = mcp_context.get("redirect_uri")
            original_state = mcp_context.get("original_state")
            code_challenge = mcp_context.get("code_challenge")
            code_challenge_method = mcp_context.get("code_challenge_method")

            if not client_id or not redirect_uri:
                return self._error_response(
                    "invalid_request", "Invalid MCP context in state"
                )

            # Select the correct authenticator based on provider in MCP state
            provider_name = mcp_context.get("provider", "google") or "google"
            authenticator = self._get_authenticator(provider_name)

            # Exchange authorization code for tokens
            token_data = authenticator.exchange_code_for_token(code, "")
            if not token_data:
                return self._error_response(
                    "invalid_grant",
                    f"Failed to exchange {provider_name} authorization code",
                )

            # Get user info from provider. OIDC providers (Apple) carry identity
            # in the id_token; others use the userinfo endpoint.
            access_token = token_data.get("access_token", "")
            user_info = authenticator.provider.extract_user_info_from_token_response(
                token_data
            )
            if not user_info:
                user_info = authenticator.validate_token_and_get_user_info(access_token)
            # E1 (the id_token path; the userinfo fetch already decided).
            from ..oauth2 import drop_unverified_email

            user_info = drop_unverified_email(
                authenticator.provider, user_info, access_token
            )
            if not user_info:
                return self._error_response(
                    "invalid_grant",
                    f"Failed to get user information from {provider_name}",
                )

            # Extract email — GitHub may need a separate API call
            email = authenticator.get_email_from_user_info(
                user_info, access_token, require_email=True
            )
            if not email:
                return self._error_response(
                    "invalid_grant",
                    f"No verified email address available from {provider_name}. "
                    f"Please add a verified email to your {provider_name} account.",
                )

            # Get or create actor for this user
            actor_obj = self._get_or_create_actor_for_email(email, provider_name)
            if not actor_obj:
                return self._error_response(
                    "server_error", "Failed to create or retrieve user actor"
                )

            # The level the user chose (or the default for a provider link),
            # re-checked: a state minted before a list change, or by a client
            # that skipped the form, gets no more than the list offers (3.16).
            from .. import session_generation
            from ..permission_integration import (
                client_trust_type_acceptable,
                default_client_trust_type,
            )

            client_data = self.client_registry.validate_client(client_id) or {}
            if not client_data:
                return self._error_response("invalid_client", "Unknown client")
            requested = mcp_context.get("trust_type") or default_client_trust_type(
                self.config
            )
            per_client = client_data.get("allowed_trust_types")
            if not client_trust_type_acceptable(self.config, requested) or (
                isinstance(per_client, list) and requested not in per_client
            ):
                return self._denied(redirect_uri, original_state)
            record: dict[str, Any] = {
                "client_id": client_id,
                "client_name": client_data.get("client_name") or "MCP Client",
                "redirect_uri": redirect_uri,
                "original_state": original_state,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "provider": provider_name,
                "actor_id": str(actor_obj.id),
                "email": email,
                "token_data": dict(token_data),
                "trust_type": str(requested),
                "session_generation": client_data.get(session_generation.STAMP_FIELD),
            }
            effective = self._decided_type(actor_obj, record, decide_trust, False)
            if not effective or (
                isinstance(per_client, list) and effective not in per_client
            ):
                return self._denied(redirect_uri, original_state)
            changed = effective != record["trust_type"]
            record["trust_type"] = effective

            # The same browser that showed the form (its cookie carries the
            # nonce the state does), at the level the user chose: complete.
            # Otherwise (another browser, a client that posted the form
            # itself, or a hook that changed the level) the user confirms
            # the level shown first.
            state_nonce = str(mcp_context.get("form_nonce") or "")
            if (
                not changed
                and state_nonce
                and form_nonce_cookie
                and secret_equals(state_nonce, form_nonce_cookie)
            ):
                return self._complete(actor_obj, record)
            token = self.token_manager.store_pending_authorization(record)
            return self._confirmation(token, record)

        except DbError:
            raise
        except Exception as e:
            logger.error(f"OAuth2 callback error: {e}")
            return self._error_response("server_error", "Internal server error")

    def handle_token_request(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Handle OAuth2 token request.

        Args:
            params: Token request parameters

        Returns:
            Token response or error
        """
        try:
            grant_type = params.get("grant_type")

            if grant_type == "authorization_code":
                return self._handle_authorization_code_grant(params)
            elif grant_type == "refresh_token":
                return self._handle_refresh_token_grant(params)
            elif grant_type == "client_credentials":
                return self._handle_client_credentials_grant(params)
            else:
                return self._error_response(
                    "unsupported_grant_type", f"Grant type '{grant_type}' not supported"
                )

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Token request error: {e}")
            return self._error_response("server_error", "Internal server error")

    def _authenticate_client(
        self, client_id: str, client_secret: str | None
    ) -> dict[str, Any] | None:
        """Authenticate a client at the token endpoint. Fails closed.

        ``MCPClientRegistry.validate_client`` is a lookup that compares a
        secret only when one is passed; the authorize endpoint and the SDK
        rely on that. The grants need the stricter rule, so it lives here:

        - an unknown ``client_id`` is refused;
        - a public client (``token_endpoint_auth_method`` ``none``) is
          accepted whatever secret it presents, and the secret is ignored
          (RFC 6749 §2.3: sending one does not make it confidential); its
          proof is PKCE on the code grant and a single-use, client-bound
          refresh token on the refresh grant;
        - any other client must present a non-empty secret equal to the
          stored one.

        The client is read strictly: a store fault raises
        ``TokenStoreUnavailable`` (answered as ``server_error``) instead of
        reading as an unknown client, which would be 401 ``invalid_client``.

        Returns:
            The client record, or None when authentication fails.
        """
        return self._check_client_credentials(
            self.client_registry.load_client_strict(client_id), client_id, client_secret
        )

    @staticmethod
    def _check_client_credentials(
        client: dict[str, Any] | None, client_id: str, client_secret: str | None
    ) -> dict[str, Any] | None:
        """The rule of :meth:`_authenticate_client` on an already-loaded record."""
        if not client:
            return None
        if client.get("token_endpoint_auth_method") == "none":
            return client
        if not client_secret:
            logger.warning(f"Client {client_id} presented no client secret")
            return None
        if not secret_equals(client.get("client_secret"), client_secret):
            logger.warning(f"Invalid client secret for client {client_id}")
            return None
        return client

    def _handle_authorization_code_grant(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle authorization_code grant type."""

        code = params.get("code")
        client_id = params.get("client_id")
        client_secret = params.get("client_secret")
        redirect_uri = params.get("redirect_uri")  # Must match authorization request
        code_verifier = params.get("code_verifier")

        if not code:
            return self._error_response("invalid_request", "code is required")
        if not client_id:
            return self._error_response("invalid_request", "client_id is required")
        if not redirect_uri:
            return self._error_response("invalid_request", "redirect_uri is required")

        # Confidential clients prove themselves with their secret; public
        # clients ("none") with the PKCE verifier checked below.
        client_data = self._authenticate_client(client_id, client_secret)
        if not client_data:
            return self._error_response("invalid_client", "Invalid client credentials")

        # PKCE validation for public clients
        if client_data.get("token_endpoint_auth_method") == "none":
            if not code_verifier:
                return self._error_response(
                    "invalid_request", "code_verifier required for public clients"
                )

        # Exchange authorization code for ActingWeb token
        token_response = self.token_manager.exchange_authorization_code(
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )

        if not token_response:
            return self._error_response(
                "invalid_grant", "Invalid or expired authorization code"
            )

        # Trust relationships are created during OAuth2 callback, not here

        logger.info(f"Issued ActingWeb access token for client {client_id}")
        return token_response

    def _handle_refresh_token_grant(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle refresh_token grant type."""
        refresh_token = params.get("refresh_token")
        client_id = params.get("client_id")
        client_secret = params.get("client_secret")

        if not refresh_token:
            return self._error_response("invalid_request", "refresh_token is required")
        if not client_id:
            return self._error_response("invalid_request", "client_id is required")

        # Confidential clients must present their secret. A public client
        # ("none") is bound by the refresh token's client_id and by rotation:
        # each refresh token is single-use.
        client_data = self._authenticate_client(client_id, client_secret)
        if not client_data:
            return self._error_response("invalid_client", "Invalid client credentials")

        # Refresh the access token
        token_response = self.token_manager.refresh_access_token(
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )

        if not token_response:
            return self._error_response(
                "invalid_grant", "Invalid or expired refresh token"
            )

        logger.info(f"Refreshed ActingWeb access token for client {client_id}")
        return token_response

    def _handle_client_credentials_grant(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle client_credentials grant type."""
        client_id = params.get("client_id")
        client_secret = params.get("client_secret")
        scope = params.get("scope", "mcp")  # Default to mcp scope

        if not client_id:
            return self._error_response("invalid_request", "client_id is required")

        # Look the client up first so a public client is told it may not use
        # this grant, rather than that it forgot a secret it never had.
        registered = self.client_registry.load_client_strict(client_id)
        if registered and registered.get("token_endpoint_auth_method") == "none":
            return self._error_response(
                "unauthorized_client",
                "Public clients may not use the client_credentials grant",
            )

        if not client_secret:
            return self._error_response("invalid_request", "client_secret is required")

        client_data = self._check_client_credentials(
            registered, client_id, client_secret
        )
        if not client_data:
            return self._error_response("invalid_client", "Invalid client credentials")

        # Get the actor ID associated with this client
        actor_id = client_data.get("actor_id")
        if not actor_id:
            logger.error(f"No actor_id found for client {client_id}")
            return self._error_response(
                "invalid_client", "Client not properly configured"
            )
        # A client registered anonymously lives on the system actor: no user
        # granted it anything, so it has no grant that needs no user (3.16).
        # A client an actor's owner created keeps it.
        from ..constants import OAUTH2_SYSTEM_ACTOR

        if actor_id == OAUTH2_SYSTEM_ACTOR:
            return self._error_response(
                "unauthorized_client",
                "An anonymously registered client may not use client_credentials",
            )

        # For client credentials flow, we need to determine the trust type
        # Use the trust type from the client registration
        trust_type = client_data.get("trust_type", "mcp_client")

        # Generate access token directly for the client
        # In client credentials flow, there's no user interaction - the client acts on its own behalf
        token_response = self.token_manager.create_access_token(
            actor_id=actor_id,
            client_id=client_id,
            scope=scope,
            trust_type=trust_type,
            grant_type="client_credentials",
            client_generation=client_data.get("session_generation"),
        )

        if not token_response:
            return self._error_response("server_error", "Failed to create access token")

        logger.info(
            f"Created client credentials access token for client {client_id} -> actor {actor_id}"
        )
        return token_response

    def handle_discovery_request(self) -> dict[str, Any]:
        """
        Handle OAuth2 authorization server discovery (RFC 8414).

        Returns:
            Authorization server metadata
        """
        base_url = f"{self.config.proto}{self.config.fqdn}"

        return {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "registration_endpoint": f"{base_url}/oauth/register",
            # offline_access is advertised because every authorization-code
            # token response already carries a refresh token (see
            # TokenManager.create_access_token) and refresh_token is an
            # advertised grant. Clients that gate long-lived sessions on the
            # scope being listed would otherwise re-prompt for authorization.
            "scopes_supported": ["mcp", "offline_access"],
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
                "client_credentials",
            ],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
                "none",
            ],
            "code_challenge_methods_supported": ["S256"],
            "service_documentation": f"{base_url}/mcp/info",
            "mcp_resource": f"{base_url}/mcp",
        }

    def validate_mcp_token(self, token: str) -> tuple[str, str, dict[str, Any]] | None:
        """
        Validate ActingWeb token for MCP endpoints.

        Args:
            token: ActingWeb access token

        Returns:
            Tuple of (actor_id, client_id, token_data) or None if invalid

        Raises:
            TokenStoreUnavailable: the token store could not be read.
        """
        return self.token_manager.validate_access_token(token)

    def handle_logout_request(self, token: str | None = None) -> dict[str, Any]:
        """
        Handle OAuth2 logout request.

        This endpoint revokes the current access token and refresh token,
        effectively logging out the user from MCP services.

        Args:
            token: Optional access token to revoke (if not provided, assumes current session)

        Returns:
            Response indicating logout success. When the token store faults
            (a token could not be read or its revocation could not be
            confirmed) the action is ``"retry"`` with ``retry_after`` seconds
            and no ``clear_cookies``: the token is still valid, so the caller
            keeps it and retries rather than reporting a logout that did not
            happen.
        """
        from .token_manager import TokenStoreUnavailable

        message = "Successfully logged out"
        try:
            if token:
                logger.info("Processing logout with token")
                # Validate and revoke the specific token
                try:
                    token_validation = self.token_manager.validate_access_token(token)
                    if token_validation:
                        actor_id, client_id, _ = token_validation
                        logger.info(
                            f"Token validated for actor {actor_id}, client {client_id}"
                        )

                        # Revoke access token using the generic revoke method
                        success = self.token_manager.revoke_token(token)
                        if success:
                            logger.info(
                                f"Successfully revoked token for client {client_id} for actor {actor_id}"
                            )
                        else:
                            logger.error(
                                f"Token revocation failed for client {client_id} - revoke_token returned False"
                            )
                    else:
                        logger.warning("Logout attempted with invalid or expired token")
                except TokenStoreUnavailable as store_error:
                    logger.error(f"Token store fault during logout: {store_error}")
                    return {
                        "action": "retry",
                        "message": "Token store temporarily unavailable; retry the logout",
                        "retry_after": 5,
                    }
                except DbError:
                    raise
                except Exception as revoke_error:
                    logger.error(
                        f"Token revocation failed with exception: {revoke_error}"
                    )
                    import traceback

                    logger.error(
                        f"Token revocation error traceback: {traceback.format_exc()}"
                    )
                    # Continue with logout process even if revocation fails,
                    # but do not report a revocation that did not happen.
                    message = "Logged out (with errors)"
            else:
                logger.info("Logout requested without token - clearing cookies only")

            return {
                "action": "success",
                "message": message,
                "clear_cookies": [
                    "access_token",
                    "oauth_token",
                    "refresh_token",
                    "session_id",
                ],
                "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
            }

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Logout request error: {e}")
            import traceback

            logger.error(f"Full logout error traceback: {traceback.format_exc()}")
            return {
                "action": "success",  # Still return success to clear cookies
                "message": "Logged out (with errors)",
                "clear_cookies": [
                    "access_token",
                    "oauth_token",
                    "refresh_token",
                    "session_id",
                ],
                "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
            }

    def _get_or_create_actor_for_email(
        self, email: str, provider_name: str = "google"
    ) -> Any | None:
        """Get or create the actor for a provider-verified email address.

        Goes through the provider's authenticator so the adoption rule applies:
        an actor nobody vouched for is replaced or cleaned before the MCP
        client is handed access to it.
        """
        try:
            return self._get_authenticator(
                provider_name
            ).lookup_or_create_actor_by_identifier(email, finish_stalled_deletion=True)
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error creating actor for email {email}: {e}")
            return None

    def _create_google_oauth_url_for_mcp(self, mcp_state: str, email_hint: str) -> str:
        """
        Create Google OAuth2 URL for MCP flows that preserves the encrypted state.

        This bypasses the normal create_authorization_url method to prevent
        JSON wrapping of the encrypted MCP state parameter.

        Args:
            mcp_state: Encrypted MCP state parameter
            email_hint: Email hint for Google OAuth2

        Returns:
            Google OAuth2 authorization URL
        """
        try:
            if not self.google_authenticator.is_enabled():
                logger.error("Google authenticator is not enabled")
                return ""

            if not self.google_authenticator.client:
                logger.error("Google authenticator client is None")
                return ""

            # Get the provider config
            provider = self.google_authenticator.provider

            # Prepare Google OAuth2 parameters
            extra_params = {
                "access_type": "offline",  # For Google to get refresh token
                "prompt": "consent",  # Force consent to get refresh token
            }

            # Add email hint for Google OAuth2
            if email_hint:
                extra_params["login_hint"] = email_hint

            # Use oauthlib directly to generate the authorization URL with the encrypted state
            authorization_url = self.google_authenticator.client.prepare_request_uri(
                provider.auth_uri,
                redirect_uri=provider.redirect_uri,
                scope=provider.scope.split(),
                state=mcp_state,  # Use the encrypted MCP state directly
                **extra_params,
            )

            return str(authorization_url)

        except Exception as e:  # folds DbError: no DB access
            logger.error(f"Error creating Google OAuth2 URL for MCP: {e}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            return ""

    # ------------------------------------------------------------------
    # Completing a client's authorisation (3.16)
    # ------------------------------------------------------------------

    def _denied(self, redirect_uri: str, original_state: str | None) -> dict[str, Any]:
        """Back to the client with ``access_denied`` (RFC 6749 §4.1.2.1)."""
        params = {"error": "access_denied"}
        if original_state:
            params["state"] = original_state
        sep = "&" if "?" in redirect_uri else "?"
        return {"action": "redirect", "url": f"{redirect_uri}{sep}{urlencode(params)}"}

    def _decided_type(
        self, actor_obj: Any, record: dict[str, Any], decide_trust: Any, confirmed: bool
    ) -> str | None:
        """The type after the application's ``oauth2_trust_requested`` hooks
        (``decide_trust``), or the requested one when there are none; None
        when declined or not acceptable."""
        from ..permission_integration import client_trust_type_acceptable

        requested = str(record.get("trust_type") or "")
        if decide_trust is None:
            return (
                requested
                if client_trust_type_acceptable(self.config, requested)
                else None
            )
        from ..interface.actor_interface import ActorInterface

        registry = getattr(self.config, "service_registry", None)
        actor = ActorInterface(core_actor=actor_obj, service_registry=registry)
        result = decide_trust(
            actor,
            requested,
            client_id=record.get("client_id"),
            client_name=record.get("client_name"),
            redirect_uri=record.get("redirect_uri"),
            provider=record.get("provider"),
            email=record.get("email"),
            confirmed=confirmed,
        )
        return str(result) if result else None

    def _confirmation(self, token: str, record: dict[str, Any]) -> dict[str, Any]:
        """What the user confirms: the client, where it goes, the level."""
        from urllib.parse import urlparse

        from ..trust_type_registry import get_registry

        trust_type = str(record.get("trust_type") or "")
        type_info = get_registry(self.config).get_type(trust_type)
        return {
            "action": "confirm",
            "token": token,
            "client_name": record.get("client_name") or "MCP Client",
            "client_id": record.get("client_id"),
            "redirect_host": urlparse(str(record.get("redirect_uri") or "")).netloc,
            "trust_type": trust_type,
            "trust_type_display_name": getattr(type_info, "display_name", trust_type),
            "trust_type_description": getattr(type_info, "description", ""),
        }

    def _complete(self, actor_obj: Any, record: dict[str, Any]) -> dict[str, Any]:
        """The trust at the approved type, then the code: no code when the
        trust could not be written (3.16; it was issued anyway)."""
        from ..interface.actor_interface import ActorInterface
        from ..oauth2 import create_oauth2_trust_relationship

        client_id = str(record["client_id"])
        email = str(record.get("email") or "")
        trust_type = str(record["trust_type"])
        registry = getattr(self.config, "service_registry", None)
        try:
            created = create_oauth2_trust_relationship(
                actor=ActorInterface(core_actor=actor_obj, service_registry=registry),
                email=email,
                trust_type=trust_type,
                oauth_tokens=dict(record.get("token_data") or {}),
                established_via="oauth2_client",
                client_id=client_id,
            )
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Trust for client {client_id} could not be written: {e}")
            created = False
        if not created:
            logger.error(
                f"No trust for client {client_id} on actor {actor_obj.id}; no code issued"
            )
            return self._error_response(
                "server_error", "The client's access could not be recorded"
            )
        auth_code = self.token_manager.create_authorization_code(
            actor_id=str(actor_obj.id),
            client_id=client_id,
            provider_token_data=dict(record.get("token_data") or {}),
            user_email=email,
            trust_type=trust_type,
            code_challenge=record.get("code_challenge"),
            code_challenge_method=record.get("code_challenge_method"),
            redirect_uri=record.get("redirect_uri"),
        )
        redirect_params = {"code": auth_code}
        if record.get("original_state"):
            redirect_params["state"] = str(record["original_state"])
        logger.info(f"OAuth2 authorization completed for client {client_id}")
        return {
            "action": "redirect",
            "url": f"{record['redirect_uri']}?{urlencode(redirect_params)}",
        }

    def handle_confirmation(
        self, token: str, approve: bool, *, decide_trust: Any = None
    ) -> dict[str, Any]:
        """The user's answer to a paused authorisation (3.16).

        The record is consumed once; an unknown, used or expired token is
        ``invalid_request`` ("start again from the client"). Decline sends
        the browser back to the client with ``access_denied``. Approve
        re-checks the client (still registered, same ``session_generation``),
        the actor (still there) and the level, runs the decision hook with
        ``confirmed=True``, then writes the trust and issues the code. A
        store that cannot answer raises (503)."""
        from .. import actor as actor_module
        from .. import session_generation

        record = self.token_manager.consume_pending_authorization(token)
        if not record:
            return self._error_response(
                "invalid_request",
                "This confirmation has expired or was used; start again from the client",
            )
        redirect_uri = str(record.get("redirect_uri") or "")
        if not approve:
            return self._denied(redirect_uri, record.get("original_state"))
        client_data = self.client_registry.validate_client(str(record["client_id"]))
        if not client_data or client_data.get(
            session_generation.STAMP_FIELD
        ) != record.get("session_generation"):
            return self._denied(redirect_uri, record.get("original_state"))
        actor_obj = actor_module.Actor(config=self.config)
        actor_obj.get(actor_id=str(record["actor_id"]))
        if not actor_obj.id:
            return self._denied(redirect_uri, record.get("original_state"))
        # The level the page showed is the one granted: the hook may still
        # decline (or answer differently, which declines), never change it.
        effective = self._decided_type(actor_obj, record, decide_trust, True)
        if effective != record.get("trust_type"):
            return self._denied(redirect_uri, record.get("original_state"))
        return self._complete(actor_obj, record)

    def complete_client_authorization(
        self,
        actor: Any,
        client_id: str,
        redirect_uri: str,
        trust_type: str | None = None,
        *,
        state: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
        email: str | None = None,
        provider_token_data: dict[str, Any] | None = None,
        decide_trust: Any = None,
    ) -> dict[str, Any]:
        """Authorise ``client_id`` for ``actor`` from a route that signed the
        user in itself (3.16): the client list (and the client's own
        ``allowed_trust_types``), the decision hook, the trust, then the
        code, in one call. Returns ``{"action": "redirect", "url": ...}`` (a
        code, or ``access_denied``) or an error dict. ``actor`` is the core
        actor or an ``ActorInterface``."""
        from .. import session_generation
        from ..permission_integration import (
            client_trust_type_acceptable,
            default_client_trust_type,
        )

        core = getattr(actor, "core_actor", actor)
        client_data = self.client_registry.validate_client(client_id)
        if not client_data:
            return self._error_response("invalid_client", "Unknown client")
        if not self.client_registry.validate_redirect_uri(client_id, redirect_uri):
            return self._error_response("invalid_request", "Invalid redirect_uri")
        requested = trust_type or default_client_trust_type(self.config)
        per_client = client_data.get("allowed_trust_types")
        if not client_trust_type_acceptable(self.config, requested) or (
            isinstance(per_client, list) and requested not in per_client
        ):
            return self._denied(redirect_uri, state)
        record: dict[str, Any] = {
            "client_id": client_id,
            "client_name": client_data.get("client_name") or "MCP Client",
            "redirect_uri": redirect_uri,
            "original_state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "provider": "",
            "actor_id": str(core.id),
            "email": email or getattr(core, "creator", "") or "",
            "token_data": dict(provider_token_data or {}),
            "trust_type": str(requested),
            "session_generation": client_data.get(session_generation.STAMP_FIELD),
        }
        # The route's user approved ``requested``: the hook may decline it,
        # and a different answer declines too (no level the user did not see).
        effective = self._decided_type(core, record, decide_trust, True)
        if effective != record["trust_type"]:
            return self._denied(redirect_uri, state)
        return self._complete(core, record)

    def _error_response(self, error: str, description: str) -> dict[str, Any]:
        """Create OAuth2 error response."""
        return {"error": error, "error_description": description}


# Global OAuth2 server instance
_oauth2_server: ActingWebOAuth2Server | None = None
# The config the singleton above was built with. These singletons are
# module-global, so without this they would bind to the FIRST config ever
# passed and silently ignore the `config` argument on every later call. That
# is wrong whenever more than one ActingWeb application exists in one
# interpreter (the test suite does this routinely): a later app would get the
# earlier app's config -- including its *database backend* -- so writes and
# reads could land in different stores. That is not hypothetical; it made MCP
# client registration write trust rows to one backend while trust resolution
# read another, which fail-closed authorization then surfaced as a denial.
_oauth2_server_config: "config_class.Config | None" = None


def get_actingweb_oauth2_server(config: "config_class.Config") -> ActingWebOAuth2Server:
    """Get or create the global ActingWeb OAuth2 server."""
    global _oauth2_server, _oauth2_server_config
    if _oauth2_server is None or _oauth2_server_config is not config:
        _oauth2_server = ActingWebOAuth2Server(config)
        _oauth2_server_config = config
    return _oauth2_server
