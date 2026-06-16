"""OAuth2 callback handler for ActingWeb.

This handler processes OAuth2 callbacks from various providers after user authentication,
exchanges the authorization code for an access token, and sets up the user session.
Uses the consolidated oauth2 module for provider-agnostic OAuth2 handling.

Supports SPA (Single Page Application) mode when spa_mode=true is included in the
OAuth state parameter. In SPA mode, returns JSON with tokens instead of redirecting.
"""

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

from .base_handler import BaseHandler
from .oauth2_utils import normalize_user_info

if TYPE_CHECKING:
    from .. import aw_web_request
    from ..interface.hooks import HookRegistry
from .. import config as config_class
from ..oauth2 import create_oauth2_authenticator, create_oauth2_trust_relationship
from ..oauth_state import decode_state, validate_expected_email


def _decode_state_with_extras(state: str) -> dict[str, Any]:
    """Decode state JSON and return full dict including extra fields like spa_mode."""
    if not state or not state.strip().startswith("{"):
        return {}
    try:
        result = json.loads(state)
        if isinstance(result, dict):
            return result
        return {}
    except (json.JSONDecodeError, TypeError):
        return {}


def is_safe_spa_redirect(config: "config_class.Config", url: str) -> bool:
    """Return True if ``url`` is a safe target for the post-auth SPA redirect.

    The SPA passes ``redirect_uri`` to ``/oauth/spa/authorize`` and the callback
    later 302-redirects the browser there with a one-time ``?session=`` id. If
    that target were attacker-controlled, the session id (exchangeable for tokens)
    would leak. Allowed targets:

    - Relative URLs (no scheme and no host) — same-origin by definition.
    - The backend's own FQDN (the common same-origin SPA case).
    - The origin of any configured OAuth ``redirect_uri`` / Apple mobile deep link
      (covers custom mobile schemes like ``io.actingweb.app://callback``).
    - Any origin explicitly listed in ``config.spa_redirect_origins`` (split-domain
      SPA deployments).

    Anything else is rejected.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Relative URLs (no scheme, no netloc) are same-origin.
    if not parsed.scheme and not parsed.netloc:
        return True

    # Same host as the configured backend FQDN.
    fqdn = getattr(config, "fqdn", "") or ""
    if fqdn and parsed.netloc == fqdn:
        return True

    target_origin = (parsed.scheme, parsed.netloc)

    def _origin_of(candidate: str) -> tuple[str, str] | None:
        if not candidate:
            return None
        try:
            cp = urlparse(candidate)
        except Exception:
            return None
        if not cp.scheme:
            return None
        return (cp.scheme, cp.netloc)

    # Origins of configured OAuth redirect URIs and Apple mobile deep links.
    providers = getattr(config, "oauth_providers", {}) or {}
    for prov_cfg in providers.values():
        if not isinstance(prov_cfg, dict):
            continue
        for key in ("redirect_uri", "mobile_deep_link", "apple_mobile_deep_link"):
            origin = _origin_of(str(prov_cfg.get(key, "")))
            if origin is not None and origin == target_origin:
                return True

    # Explicitly allowlisted SPA origins (split-domain deployments).
    for allowed in getattr(config, "spa_redirect_origins", None) or []:
        if _origin_of(str(allowed)) == target_origin:
            return True

    return False


logger = logging.getLogger(__name__)


class OAuth2CallbackHandler(BaseHandler):
    """Handles OAuth2 callbacks at /oauth/callback for Google/GitHub OAuth flows.

    This handler processes TWO types of OAuth2 flows:

    1. Web UI Login (no trust_type in state):

       - User clicks "Login with Google/GitHub" on factory page
       - After OAuth, creates/looks up actor and redirects to UI page
         (``/www`` if config.ui is enabled, ``/app`` for SPAs when config.ui is disabled)
       - If email is missing, redirects to /oauth/email for manual input

    2. MCP Authorization (trust_type in state, e.g., 'mcp_client'):

       - OAuth flow initiated with trust_type parameter
       - After OAuth, creates/looks up actor AND trust relationship
       - If email is missing, returns error (MCP clients can't use web forms)

    Note: MCP OAuth2 flow where ActingWeb is the auth server uses encrypted
    state and is routed to OAuth2EndpointsHandler, not this handler.

    Expected query parameters:

    - code: Authorization code to exchange for access token
    - state: CSRF protection and optional redirect URL, actor_id, trust_type
    - error: Error code if authentication failed
    """

    def __init__(
        self,
        webobj: Optional["aw_web_request.AWWebObj"] = None,
        config: config_class.Config | None = None,
        hooks: Optional["HookRegistry"] = None,
    ) -> None:
        if config is None:
            raise RuntimeError("Config is required for OAuth2CallbackHandler")
        if webobj is None:
            from .. import aw_web_request

            webobj = aw_web_request.AWWebObj()
        super().__init__(webobj, config, hooks)
        # Create a default authenticator; may be replaced once state is parsed
        # and the actual provider is known.
        self.authenticator = create_oauth2_authenticator(config) if config else None
        # Apple's web flow delivers a one-time `user` JSON (name/email) on the
        # first sign-in only; the Apple POST handler stashes it here so the shared
        # SPA session-creation path can merge it before firing oauth_success.
        self._pending_apple_user_json: str | None = None

    def _redirect_with_mobile_ticket(
        self, provider: str, code: str, pkce_session_id: str = ""
    ) -> dict[str, Any]:
        """Hand a native-mobile provider's authorization code to the app via an
        opaque single-use ticket deep link.

        The IdP ``code`` is stored server-side and the app receives only the
        ticket, which it redeems at ``/oauth/spa/token`` (``mobile_ticket``
        grant). Neither the code nor any ActingWeb token appears in the deep
        link. Shared by the Apple form_post handler and the query-mode callback
        (e.g. ``github-mobile``).

        ``pkce_session_id`` carries the server-managed PKCE session through the
        ticket so the deferred (server-side) code exchange can supply the stored
        ``code_verifier`` — required when a ``code_challenge`` was sent at
        authorize time (e.g. GitHub). Apple does not use PKCE, so it passes none.
        """
        from urllib.parse import urlencode, urlunparse

        from ..oauth_state_store import MobileTicketStore

        if not code:
            return self.error_response(400, "Missing authorization code")
        if not self.authenticator:
            return self.error_response(500, "OAuth2 not configured")
        deep_link = getattr(self.authenticator.provider, "mobile_deep_link", "")
        if not deep_link:
            logger.error("%s provider has no mobile deep link configured", provider)
            return self.error_response(500, "Mobile flow not configured")
        extra = {"pkce_session_id": pkce_session_id} if pkce_session_id else None
        ticket = MobileTicketStore(self.config).create(
            code=code,
            redirect_uri=self.authenticator.provider.redirect_uri,
            provider=provider,
            extra=extra,
        )
        parsed = urlparse(deep_link)
        deep_url = urlunparse(
            (
                parsed.scheme or "",
                parsed.netloc or "",
                parsed.path,
                parsed.params,
                urlencode({"ticket": ticket}),
                parsed.fragment,
            )
        )
        self.response.set_status(302, "Found")
        self.response.set_redirect(deep_url)
        return {"redirect_required": True, "redirect_url": deep_url}

    def get(self) -> dict[str, Any]:
        """
        Handle GET request to /oauth/callback from OAuth2 provider.

        Expected parameters:
        - code: Authorization code from OAuth2 provider
        - state: State parameter for CSRF protection
        - error: Error code if authentication failed

        Returns:
            Response dict with success/error status
        """
        if not self.authenticator or not self.authenticator.is_enabled():
            logger.error("OAuth2 not configured")
            return self.error_response(500, "OAuth2 not configured")

        # Check for error parameter (the provider rejected the request — most
        # commonly the user cancelled consent → ``error=access_denied``).
        error = self.request.get("error")
        if error:
            error_description = self.request.get("error_description")
            if not error_description:
                error_description = ""
            logger.warning(f"OAuth2 error: {error} - {error_description}")
            # SPA browser navigations must bounce the error back to the app's
            # callback so it can show a friendly message and a "Try again"
            # button. Returning a backend error page here renders
            # ``aw-root-failed.html`` — a 500 in apps that don't ship that
            # template — and is the wrong surface for a single-page app anyway.
            #
            # The CSRF token in ``state`` is intentionally NOT validated here:
            # there is no code to exchange and no session to create on the error
            # path, so a forged ``spa_mode`` state cannot do anything beyond
            # producing a redirect. The redirect target is independently
            # constrained by ``is_safe_spa_redirect`` (with a benign fallback to
            # the configured root), so an attacker cannot turn this into an open
            # redirect.
            state_extras = _decode_state_with_extras(self.request.get("state") or "")
            if self.config and state_extras.get("spa_mode"):
                spa_redirect_url = state_extras.get("redirect_url", "")
                if not spa_redirect_url or not is_safe_spa_redirect(
                    self.config, spa_redirect_url
                ):
                    spa_redirect_url = f"{self.config.proto}{self.config.fqdn}/"
                return self._redirect_to_spa_with_error(
                    spa_redirect_url, error, error_description
                )
            return self.error_response(400, f"Authentication failed: {error}")

        # Get authorization code
        code = self.request.get("code")
        if not code:
            logger.error("No authorization code in OAuth2 callback")
            return self.error_response(400, "Missing authorization code")

        # Get and parse state parameter
        state = self.request.get("state")
        if not state:
            state = ""
        _, redirect_url, actor_id, trust_type, _expected_email, user_agent = (
            decode_state(state)
        )

        # Extract extra fields including spa_mode
        state_extras = _decode_state_with_extras(state)
        spa_mode = state_extras.get("spa_mode", False)

        # Re-create authenticator with the correct provider from state (if present)
        state_provider = state_extras.get("provider", "")
        if state_provider and self.config:
            self.authenticator = create_oauth2_authenticator(
                self.config, state_provider
            )

        # For SPA mode, use redirect_url from state_extras (JSON format)
        # The legacy decode_state() doesn't parse JSON state properly
        spa_redirect_url = state_extras.get("redirect_url", "") if spa_mode else ""

        # Defense-in-depth: never honor an unsafe SPA redirect target. The
        # one-time ?session= id is appended to this URL, so an attacker-supplied
        # origin would leak it. Fall back to the backend root if it's not allowed.
        if spa_redirect_url and not is_safe_spa_redirect(self.config, spa_redirect_url):
            logger.warning(
                "Rejected unsafe SPA redirect target '%s'; falling back to root",
                spa_redirect_url,
            )
            spa_redirect_url = f"{self.config.proto}{self.config.fqdn}/"

        logger.debug(
            f"Parsed state - redirect_url: '{redirect_url}', spa_redirect_url: '{spa_redirect_url}', actor_id: '{actor_id}', trust_type: '{trust_type}', spa_mode: {spa_mode}"
        )

        # Native-mobile providers that route through the HTTPS query callback
        # (e.g. github-mobile) get only an opaque ticket on their deep link; the
        # code is exchanged server-side via the mobile_ticket grant. Apple's
        # form_post variant is handled by OAuth2AppleCallbackHandler instead, so
        # it never reaches here. Detected by a configured mobile deep link.
        if (
            state_provider
            and state_provider.endswith("-mobile")
            and getattr(self.authenticator.provider, "mobile_deep_link", "")
        ):
            # Carry the server-managed PKCE session so the deferred exchange can
            # supply the stored verifier (a code_challenge was sent at authorize).
            return self._redirect_with_mobile_ticket(
                state_provider, code, state_extras.get("pkce_session_id", "")
            )

        # For SPA mode, check if this is a browser navigation vs fetch request
        # Browser navigations need to redirect to SPA callback with code/state
        # Fetch requests (Accept: application/json) get JSON response with tokens
        if spa_mode and spa_redirect_url:
            accept_header = ""
            if hasattr(self.request, "headers") and self.request.headers:
                accept_header = self.request.headers.get("Accept", "")
                if not accept_header:
                    accept_header = self.request.headers.get("accept", "")

            # If not a JSON fetch request, this is the browser redirect from OAuth provider
            # We need to process the OAuth flow NOW (code is single-use) and pass
            # a session token to the SPA instead of the raw code
            if "application/json" not in accept_header:
                # Process the OAuth flow and create a pending session
                result = self._process_spa_oauth_and_create_session(
                    code, state, state_extras, spa_redirect_url
                )
                return result

        # Critical debug: Check if trust_type was parsed correctly
        if trust_type:
            logger.debug(
                f"Trust type '{trust_type}' found in state - will create trust relationship"
            )
        else:
            logger.warning(
                "No trust_type found in parsed state - trust relationship will NOT be created"
            )

        # Exchange code for access token
        token_data = self.authenticator.exchange_code_for_token(code, state)
        if not token_data or "access_token" not in token_data:
            logger.error("Failed to exchange authorization code for access token")
            return self.error_response(502, "Token exchange failed")

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        # Get user info. OIDC providers (Apple) carry identity in the id_token
        # within the token response; others fetch it from the userinfo endpoint.
        user_info = self.authenticator.provider.extract_user_info_from_token_response(
            token_data
        )
        if not user_info:
            user_info = self.authenticator.validate_token_and_get_user_info(
                access_token
            )
        # Merge Apple's first-sign-in `user` payload (name/email) if present.
        user_info = self._merge_apple_user_payload(user_info)
        if not user_info:
            logger.error("Failed to validate token or extract user info")
            return self.error_response(502, "Token validation failed")

        # Normalize to a consistent (display_name / given_name / family_name /
        # email) shape so the oauth_success hook reads ONE shape across
        # providers. GitHub's userinfo carries `name`, not `display_name`, so
        # without this the hook finds no display_name and stores nothing. This
        # mirrors the SPA token-exchange path.
        user_info = normalize_user_info(self.authenticator.provider.name, user_info)

        # Determine if email is required based on config
        require_email = bool(
            self.config and getattr(self.config, "force_email_prop_as_creator", False)
        )

        logger.debug(f"OAuth identifier extraction mode: require_email={require_email}")

        # Extract identifier (email or provider ID) based on config
        identifier = self.authenticator.get_email_from_user_info(
            user_info, access_token, require_email=require_email
        )

        if not identifier:
            logger.warning("Failed to extract identifier from user info")

            # If in provider ID mode (require_email=False), this is a critical error
            if not require_email:
                logger.error(
                    "Provider ID mode enabled but no identifier available from OAuth provider"
                )
                return self.error_response(
                    502,
                    "OAuth provider did not return user identifier. Please contact support.",
                )

            # Email required mode - try to get verified emails for dropdown
            verified_emails: list[str] | None = None

            if self.authenticator.provider.name == "github" and access_token:
                verified_emails = self.authenticator.get_github_verified_emails(
                    access_token
                )
                if verified_emails:
                    logger.info(
                        f"Found {len(verified_emails)} verified emails from GitHub"
                    )

            # Check if this is an MCP authorization flow
            if trust_type:
                logger.error("Cannot complete MCP authorization without identifier")
                return self.error_response(
                    502,
                    f"Email required but not provided by OAuth provider. "
                    f"Configure your {self.authenticator.provider.name} account to make email public.",
                )

            # Web UI flow - redirect to email input form
            logger.info("Web UI login flow - redirecting to email input form")
            try:
                from ..oauth_session import get_oauth2_session_manager

                session_manager = get_oauth2_session_manager(self.config)
                provider_name = getattr(self.config, "oauth2_provider", "google")
                session_id = session_manager.store_session(
                    token_data=token_data,
                    user_info=user_info,
                    state=state,
                    provider=provider_name,
                    verified_emails=verified_emails,  # NEW: Pass verified emails
                )

                # Redirect to email input form (app will provide template)
                email_form_url = f"/oauth/email?session={session_id}"
                self.response.set_status(302, "Found")
                self.response.set_redirect(email_form_url)

                return {
                    "status": "email_required",
                    "message": "Email could not be extracted from OAuth provider",
                    "session_id": session_id,
                    "redirect_url": email_form_url,
                    "redirect_performed": True,
                }

            except Exception as session_error:
                logger.error(f"Failed to create OAuth session: {session_error}")
                # Fall back to error response if session storage fails
                return self.error_response(
                    502, "Email extraction failed and could not store session"
                )

        # Validate identifier format based on mode
        if require_email:
            # Must be a valid email
            if "@" not in identifier:
                logger.error(
                    f"force_email_prop_as_creator enabled but got non-email: {identifier}"
                )
                return self.error_response(
                    502,
                    "Configuration requires email but OAuth provider returned non-email identifier",
                )

            # Validate against expected email from form (if provided)
            if not validate_expected_email(state, identifier):
                logger.error(f"Email validation failed - authenticated as {identifier}")
                return self.error_response(
                    403,
                    "Authentication email does not match the email provided in the form",
                )
        else:
            # Provider ID mode - identifier can be anything
            logger.debug(f"Using provider identifier: {identifier}")

        # Use existing actor from state if provided, otherwise lookup/create by identifier
        actor_instance = None
        if actor_id:
            # Try to use the existing actor from the state parameter
            from .. import actor as actor_module

            try:
                actor_instance = actor_module.Actor(config=self.config)
                if not actor_instance.get(actor_id):
                    logger.warning(
                        f"Actor {actor_id} from state not found, will lookup/create by identifier"
                    )
                    actor_instance = None
                else:
                    logger.debug(
                        f"Using existing actor {actor_id} from state parameter"
                    )

                    # SECURITY: Validate that OAuth identifier matches actor creator
                    # This prevents attackers from:
                    # 1. MCP flow: Authorizing access to someone else's actor
                    # 2. Web flow: Session fixation or account takeover attacks
                    if actor_instance.creator != identifier:
                        logger.error(
                            f"Security violation: OAuth identifier '{identifier}' does not match "
                            f"actor creator '{actor_instance.creator}'. "
                            f"Flow type: {'MCP authorization' if trust_type else 'Web login'}"
                        )

                        if trust_type:
                            # MCP authorization - clear error message
                            return self.error_response(
                                403,
                                f"You cannot authorize MCP access to an actor that doesn't belong to you. "
                                f"You authenticated as '{identifier}' but this actor belongs to '{actor_instance.creator}'.",
                            )
                        else:
                            # Web login - potential session fixation attack
                            return self.error_response(
                                403,
                                f"Authentication failed: You authenticated as '{identifier}' but attempted to "
                                f"access an actor belonging to '{actor_instance.creator}'. Please log in with the correct account.",
                            )

            except Exception as e:
                logger.warning(
                    f"Failed to load actor {actor_id} from state: {e}, will lookup/create by identifier"
                )
                actor_instance = None

        # If no actor from state or loading failed, lookup/create by identifier
        is_new_actor = False
        if not actor_instance:
            # Check if actor exists before attempting creation
            from actingweb.actor import Actor as CoreActor

            existing_check_actor = CoreActor(config=self.config)
            actor_exists = existing_check_actor.get_from_creator(identifier)
            is_new_actor = not actor_exists

            actor_instance = self.authenticator.lookup_or_create_actor_by_identifier(
                identifier,
                user_info=user_info,  # Pass user_info for additional metadata
            )
            if not actor_instance:
                logger.error(
                    f"Failed to lookup or create actor for identifier {identifier}"
                )
                return self.error_response(502, "Actor creation failed")

        # Store OAuth tokens in actor properties
        # The auth system expects oauth_token (not oauth_access_token)
        if actor_instance.store:
            actor_instance.store.oauth_token = (
                access_token  # This is what auth.py looks for
            )
            actor_instance.store.oauth_token_expiry = (
                str(int(time.time()) + expires_in) if expires_in else None
            )
            if refresh_token:
                actor_instance.store.oauth_refresh_token = refresh_token
            actor_instance.store.oauth_token_timestamp = str(int(time.time()))

        # Extract client metadata for trust relationship storage
        client_name = None
        client_version = None
        client_platform = user_agent  # Use User-Agent as platform info

        if user_agent:
            try:
                # Generate session key using same logic as MCP handler
                client_ip = getattr(self.request, "remote_addr", "unknown")
                session_key = f"{client_ip}:{hash(user_agent)}"

                # Import here to avoid circular dependencies
                from .mcp import MCPHandler

                stored_client_info = MCPHandler.get_stored_client_info(session_key)

                if stored_client_info and stored_client_info.get("client_info"):
                    mcp_client_info = stored_client_info["client_info"]
                    client_name = mcp_client_info.get("name", "MCP Client")
                    client_version = mcp_client_info.get("version")

                    # Use implementation info for better platform detection
                    if "implementation" in mcp_client_info:
                        impl = mcp_client_info["implementation"]
                        if isinstance(impl, dict):
                            impl_name = impl.get("name", "Unknown")
                            impl_version = impl.get("version", "")
                            client_platform = f"{impl_name} {impl_version}".strip()

                    logger.debug(
                        f"Extracted MCP client metadata: {client_name} v{client_version} on {client_platform}"
                    )

            except Exception as e:
                logger.debug(
                    f"Could not retrieve MCP client info during OAuth callback: {e}"
                )
                # Continue with User-Agent as platform info
                # Non-critical, don't fail the OAuth flow

        # Create trust relationship if trust_type was specified in state
        logger.debug(
            f"About to check trust_type for relationship creation: trust_type='{trust_type}'"
        )
        if trust_type:
            logger.info(
                f"Creating trust relationship for trust_type='{trust_type}' and identifier='{identifier}'"
            )
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor_instance, service_registry=registry
                )

                # Prepare OAuth tokens for secure storage
                oauth_tokens = {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": int(time.time()) + expires_in if expires_in else 0,
                    "token_type": token_data.get("token_type", "Bearer"),
                }

                # Create trust relationship with automatic approval and client metadata
                trust_created = create_oauth2_trust_relationship(
                    actor_interface,
                    identifier,
                    trust_type,
                    oauth_tokens,
                    client_name=client_name,
                    client_version=client_version,
                    client_platform=client_platform,
                )

                if trust_created:
                    logger.info(
                        f"Successfully created trust relationship: {identifier} -> {trust_type}"
                    )
                else:
                    logger.warning(
                        f"Failed to create trust relationship for {identifier} with type {trust_type}"
                    )

            except Exception as e:
                logger.error(f"Error creating OAuth2 trust relationship: {e}")
                # Don't fail the OAuth flow - just log the error

        # Execute actor_created lifecycle hook for new actors
        if is_new_actor and self.hooks:
            try:
                # Convert core Actor to ActorInterface for hook consistency
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
                # Convert core Actor to ActorInterface for hook consistency
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor_instance, service_registry=registry
                )

                result = self.hooks.execute_lifecycle_hooks(
                    "oauth_success",
                    actor_interface,
                    email=identifier,  # Pass identifier (may be email or provider ID)
                    access_token=access_token,
                    token_data=token_data,
                    user_info=user_info,  # Pass full user info for displayname etc.
                )
                oauth_valid = bool(result) if result is not None else True
            except Exception as e:
                logger.error(f"Error in lifecycle hook for oauth_success: {e}")
                oauth_valid = False

        if not oauth_valid:
            logger.warning(
                f"OAuth success hook rejected authentication for {identifier}"
            )
            return self.error_response(403, "Authentication rejected")

        # Set up successful response
        # Use return_path from state for SPA mode (defaults to /app), /www or /app for traditional mode
        if spa_mode:
            return_path = state_extras.get("return_path", "/app")
            # Support {actor_id} placeholder in return_path
            if "{actor_id}" in return_path:
                final_redirect = return_path.replace("{actor_id}", actor_instance.id)
            else:
                final_redirect = f"/{actor_instance.id}{return_path}"
        else:
            # Traditional (non-SPA) mode: redirect based on config.ui setting
            if self.config.ui:
                final_redirect = f"/{actor_instance.id}/www"
            else:
                final_redirect = f"/{actor_instance.id}/app"

        response_data = {
            "status": "success",
            "message": "Authentication successful",
            "actor_id": actor_instance.id,
            "email": identifier,  # identifier (may be email or provider ID)
            "access_token": access_token,
            "expires_in": expires_in,
            "redirect_url": final_redirect,
        }

        # SPA mode: Return JSON with tokens instead of redirecting
        if spa_mode:
            logger.debug(f"SPA mode enabled - returning JSON response for {identifier}")

            # Generate ActingWeb SPA tokens instead of returning OAuth provider tokens
            # This allows the session manager to validate these tokens later
            from ..oauth_session import get_oauth2_session_manager

            session_manager = get_oauth2_session_manager(self.config)

            # Generate ActingWeb access token and store it
            spa_access_token = self.config.new_token()
            actor_id_str = actor_instance.id or ""
            session_manager.store_access_token(
                spa_access_token, actor_id_str, identifier
            )

            # Generate refresh token for SPA
            spa_refresh_token = session_manager.create_refresh_token(
                actor_id_str, identifier
            )

            # Update response with SPA tokens (not OAuth provider tokens)
            response_data["access_token"] = spa_access_token
            response_data["success"] = True
            response_data["token_type"] = "Bearer"
            response_data["refresh_token"] = spa_refresh_token
            response_data["expires_at"] = int(time.time()) + 3600  # 1 hour

            # Set HttpOnly cookie for refresh token (hybrid mode)
            token_delivery = state_extras.get("token_delivery", "json")
            if token_delivery == "hybrid" and self.response:
                self.response.set_cookie(
                    "refresh_token",
                    spa_refresh_token,
                    max_age=86400 * 14,  # 2 weeks
                    path="/oauth/spa/token",
                    secure=True,
                    httponly=True,
                    samesite="Strict",
                )
                # Don't include refresh token in JSON for hybrid mode
                del response_data["refresh_token"]

            if self.response:
                self.response.write(json.dumps(response_data))
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)

            # Execute OAuth completed lifecycle hook
            if self.hooks:
                try:
                    self.hooks.execute_lifecycle_hooks(
                        "oauth_completed",
                        actor_instance,
                        email=identifier,
                        access_token=access_token,
                        redirect_url=response_data["redirect_url"],
                    )
                except Exception as e:
                    logger.error(f"Error executing oauth_completed hook: {e}")

            logger.debug(
                f"OAuth2 SPA authentication completed successfully for {identifier} -> {actor_instance.id}"
            )
            return response_data

        # For interactive web authentication, redirect to the actor's UI page
        # (/www if config.ui is enabled, /app for SPAs)
        # For API clients, they would use the Bearer token directly

        logger.debug(f"Redirecting to actor page: {final_redirect}")

        # Log the original URL for reference but don't use it
        if redirect_url:
            logger.debug(
                f"Original URL was: {redirect_url} (redirecting to UI page instead)"
            )

        # Generate ActingWeb session token for /www mode (same approach as SPA)
        # This avoids validating Google tokens on every request
        from ..oauth_session import get_oauth2_session_manager

        session_manager = get_oauth2_session_manager(self.config)

        # Generate ActingWeb access token and store it
        www_access_token = self.config.new_token()
        actor_id_str = actor_instance.id or ""
        session_manager.store_access_token(www_access_token, actor_id_str, identifier)

        # Set session cookie with ActingWeb token (not Google token)
        cookie_max_age = 3600  # 1 hour - matches token TTL in session manager

        self.response.set_cookie(
            "oauth_token",
            www_access_token,
            max_age=cookie_max_age,
            path="/",
            secure=True,
            httponly=True,  # Protect from XSS
            samesite="Lax",
        )

        logger.debug(
            f"Set oauth_token cookie with ActingWeb token for actor {actor_id_str}"
        )

        # Perform the redirect for interactive authentication
        self.response.set_status(302, "Found")
        self.response.set_redirect(final_redirect)

        # Also include the information in the response data for completeness
        response_data["redirect_performed"] = True

        # Execute OAuth completed lifecycle hook
        if self.hooks:
            try:
                self.hooks.execute_lifecycle_hooks(
                    "oauth_completed",
                    actor_instance,
                    email=identifier,
                    access_token=access_token,
                    redirect_url=response_data["redirect_url"],
                )
            except Exception as e:
                logger.error(f"Error executing oauth_completed hook: {e}")

        logger.debug(
            f"OAuth2 authentication completed successfully for {identifier} -> {actor_instance.id}"
        )
        return response_data

    def _is_safe_redirect(self, url: str) -> bool:
        """Check if redirect URL is safe (same origin or configured allowlist).

        Delegates to :func:`is_safe_spa_redirect`.
        """
        return is_safe_spa_redirect(self.config, url)

    def _merge_apple_user_payload(
        self, user_info: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Merge Apple's first-sign-in ``user`` JSON into ``user_info``.

        Apple returns ``{"name": {"firstName", "lastName"}, "email"}`` in the
        form_post body only on the very first sign-in. We normalize it into
        ``given_name`` / ``family_name`` / ``display_name`` (and ``email`` if the
        id_token lacked one) so the ``oauth_success`` hook sees a consistent shape.
        """
        payload = self._pending_apple_user_json
        if not payload or user_info is None:
            return user_info
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
        except (json.JSONDecodeError, TypeError):
            return user_info
        if not isinstance(data, dict):
            return user_info

        name = data.get("name") if isinstance(data.get("name"), dict) else {}
        first = (name or {}).get("firstName") or data.get("firstName") or ""
        last = (name or {}).get("lastName") or data.get("lastName") or ""
        if first and not user_info.get("given_name"):
            user_info["given_name"] = first
        if last and not user_info.get("family_name"):
            user_info["family_name"] = last
        if (first or last) and not user_info.get("display_name"):
            user_info["display_name"] = f"{first} {last}".strip()
        email = data.get("email")
        if email and not user_info.get("email"):
            user_info["email"] = email
        return user_info

    def error_response(self, status_code: int, message: str) -> dict[str, Any]:
        """Create error response with template rendering for user-friendly errors."""
        self.response.set_status(status_code)

        # For user-facing errors, try to render template
        if status_code in [403, 400] and hasattr(self.response, "template_values"):
            self.response.template_values = {
                "error": message,
                "status_code": status_code,
            }

        return {"error": True, "status_code": status_code, "message": message}

    def _redirect_to_spa_with_error(
        self, spa_redirect_url: str, error: str, error_description: str
    ) -> dict[str, Any]:
        """Bounce a provider error back to the SPA callback with the error
        params, so the app surfaces it (the SPA's callback route reads
        ``error`` / ``error_description``) instead of the backend rendering an
        error template. Used for the cancelled-consent case where there is no
        code to exchange.

        Any query params already present on ``spa_redirect_url`` (e.g. routing
        or correlation params the SPA passed to ``/oauth/spa/authorize``) are
        preserved; the ``error`` / ``error_description`` params are merged in."""
        from urllib.parse import parse_qsl, urlencode, urlunparse

        parsed = urlparse(spa_redirect_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["error"] = error
        if error_description:
            params["error_description"] = error_description
        url = urlunparse(
            (
                parsed.scheme or "",
                parsed.netloc or "",
                parsed.path,
                parsed.params,
                urlencode(params),
                parsed.fragment,
            )
        )
        self.response.set_status(302, "Found")
        self.response.set_redirect(url)
        return {"redirect_required": True, "redirect_url": url}

    def _process_spa_oauth_and_create_session(
        self,
        code: str,
        state: str,
        state_extras: dict[str, Any],
        spa_redirect_url: str,
    ) -> dict[str, Any]:
        """
        Process OAuth flow for SPA mode browser navigation.

        Since OAuth authorization codes are single-use, we must exchange the code
        immediately when the browser redirects from the OAuth provider. We then
        store the result in a pending session and redirect to the SPA with a
        session token instead of the raw code.

        Args:
            code: OAuth authorization code
            state: Original state parameter
            state_extras: Parsed state extras (spa_mode, redirect_url, etc.)
            spa_redirect_url: SPA callback URL to redirect to

        Returns:
            Response dict with redirect info
        """
        from urllib.parse import urlencode, urlparse, urlunparse

        from ..oauth_session import get_oauth2_session_manager

        # Ensure authenticator is available
        if not self.authenticator:
            logger.error("SPA OAuth: Authenticator not configured")
            parsed = urlparse(spa_redirect_url)
            params = {
                "error": "server_error",
                "error_description": "OAuth not configured",
            }
            spa_error_url = urlunparse(
                (
                    parsed.scheme or "",
                    parsed.netloc or "",
                    parsed.path,
                    parsed.params,
                    urlencode(params),
                    parsed.fragment,
                )
            )
            self.response.set_status(302, "Found")
            self.response.set_redirect(spa_error_url)
            return {"redirect_required": True, "redirect_url": spa_error_url}

        session_manager = get_oauth2_session_manager(self.config)

        # Retrieve PKCE code verifier if server-managed PKCE was used
        code_verifier = None
        pkce_session_id = state_extras.get("pkce_session_id")
        if pkce_session_id:
            pkce_session = session_manager.get_session(pkce_session_id)
            if pkce_session:
                code_verifier = pkce_session.get("pkce_verifier")
                logger.debug(
                    f"Retrieved PKCE code verifier from session {pkce_session_id[:8]}..."
                )
                # PKCE session will expire naturally (short TTL)
            else:
                logger.warning(
                    f"PKCE session {pkce_session_id[:8]}... not found or expired"
                )

        # Exchange code for tokens NOW (single-use code)
        token_data = self.authenticator.exchange_code_for_token(
            code, state, code_verifier=code_verifier
        )
        if not token_data or "access_token" not in token_data:
            logger.error("SPA OAuth: Failed to exchange authorization code")
            # Redirect to SPA with error
            parsed = urlparse(spa_redirect_url)
            params = {
                "error": "token_exchange_failed",
                "error_description": "Failed to exchange authorization code",
            }
            spa_error_url = urlunparse(
                (
                    parsed.scheme or "",
                    parsed.netloc or "",
                    parsed.path,
                    parsed.params,
                    urlencode(params),
                    parsed.fragment,
                )
            )
            self.response.set_status(302, "Found")
            self.response.set_redirect(spa_error_url)
            return {"redirect_required": True, "redirect_url": spa_error_url}

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        # Get user info. OIDC providers (Apple) carry identity in the id_token
        # within the token response; others fetch it from the userinfo endpoint.
        user_info = self.authenticator.provider.extract_user_info_from_token_response(
            token_data
        )
        if not user_info:
            user_info = self.authenticator.validate_token_and_get_user_info(
                access_token
            )
        # Merge Apple's first-sign-in `user` payload (name/email) if present.
        user_info = self._merge_apple_user_payload(user_info)
        if not user_info:
            logger.error("SPA OAuth: Failed to validate token")
            parsed = urlparse(spa_redirect_url)
            params = {
                "error": "validation_failed",
                "error_description": "Token validation failed",
            }
            spa_error_url = urlunparse(
                (
                    parsed.scheme or "",
                    parsed.netloc or "",
                    parsed.path,
                    parsed.params,
                    urlencode(params),
                    parsed.fragment,
                )
            )
            self.response.set_status(302, "Found")
            self.response.set_redirect(spa_error_url)
            return {"redirect_required": True, "redirect_url": spa_error_url}

        # Normalize to a consistent (display_name / given_name / family_name /
        # email) shape so the oauth_success hook reads ONE shape across
        # providers. GitHub's userinfo carries `name`, not `display_name`, so
        # without this the SPA-via-callback login stores no display name. This
        # mirrors the SPA token-exchange path.
        user_info = normalize_user_info(self.authenticator.provider.name, user_info)

        # Determine if email is required based on config
        require_email = bool(
            self.config and getattr(self.config, "force_email_prop_as_creator", False)
        )

        # Extract identifier
        identifier = self.authenticator.get_email_from_user_info(
            user_info, access_token, require_email=require_email
        )

        if not identifier:
            if require_email:
                # Email required but not available — redirect back to SPA
                logger.info(
                    "SPA OAuth: No verified email from provider, "
                    "redirecting to SPA with email_required"
                )

                # Try to get verified emails for dropdown
                verified_emails: list[str] | None = None
                if self.authenticator.provider.name == "github" and access_token:
                    verified_emails = self.authenticator.get_github_verified_emails(
                        access_token
                    )

                try:
                    provider_name = state_extras.get(
                        "provider",
                        getattr(self.config, "oauth2_provider", "github"),
                    )
                    session_id = session_manager.store_session(
                        token_data=token_data,
                        user_info=user_info,
                        state=state,
                        provider=provider_name,
                        verified_emails=verified_emails,
                    )

                    # Redirect back to SPA with email_required flag,
                    # matching the existing SPA redirect patterns
                    # (success: ?session=..., error: ?error=...)
                    parsed = urlparse(spa_redirect_url)
                    email_params = {
                        "email_required": "true",
                        "session": session_id,
                    }
                    spa_email_url = urlunparse(
                        (
                            parsed.scheme or "",
                            parsed.netloc or "",
                            parsed.path,
                            parsed.params,
                            urlencode(email_params),
                            parsed.fragment,
                        )
                    )
                    self.response.set_status(302, "Found")
                    self.response.set_redirect(spa_email_url)
                    return {
                        "status": "email_required",
                        "session_id": session_id,
                        "redirect_url": spa_email_url,
                        "redirect_performed": True,
                    }
                except Exception as session_error:
                    logger.error(
                        f"SPA OAuth: Failed to create email session: {session_error}"
                    )

            # Provider ID mode or session creation failed — hard error
            logger.error("SPA OAuth: Failed to extract identifier")
            parsed = urlparse(spa_redirect_url)
            params = {
                "error": "identifier_failed",
                "error_description": "Could not extract user identifier",
            }
            spa_error_url = urlunparse(
                (
                    parsed.scheme or "",
                    parsed.netloc or "",
                    parsed.path,
                    parsed.params,
                    urlencode(params),
                    parsed.fragment,
                )
            )
            self.response.set_status(302, "Found")
            self.response.set_redirect(spa_error_url)
            return {"redirect_required": True, "redirect_url": spa_error_url}

        # Lookup or create actor
        actor_instance = self.authenticator.lookup_or_create_actor_by_identifier(
            identifier, user_info=user_info
        )
        if not actor_instance:
            logger.error("SPA OAuth: Failed to create actor")
            parsed = urlparse(spa_redirect_url)
            params = {
                "error": "actor_failed",
                "error_description": "Failed to create user account",
            }
            spa_error_url = urlunparse(
                (
                    parsed.scheme or "",
                    parsed.netloc or "",
                    parsed.path,
                    parsed.params,
                    urlencode(params),
                    parsed.fragment,
                )
            )
            self.response.set_status(302, "Found")
            self.response.set_redirect(spa_error_url)
            return {"redirect_required": True, "redirect_url": spa_error_url}

        # Store OAuth tokens in actor properties
        if actor_instance.store:
            actor_instance.store.oauth_token = access_token
            actor_instance.store.oauth_token_expiry = (
                str(int(time.time()) + expires_in) if expires_in else None
            )
            if refresh_token:
                actor_instance.store.oauth_refresh_token = refresh_token
            actor_instance.store.oauth_token_timestamp = str(int(time.time()))

        # Execute oauth_success lifecycle hooks (same as non-SPA flow)
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
                    access_token=access_token,
                    token_data=token_data,
                    user_info=user_info,
                )
                oauth_valid = bool(result) if result is not None else True
            except Exception as e:
                logger.error(f"Error in SPA lifecycle hook for oauth_success: {e}")
                oauth_valid = False

            if not oauth_valid:
                logger.warning(
                    f"SPA OAuth success hook rejected authentication for {identifier}"
                )
                parsed = urlparse(spa_redirect_url)
                params = {
                    "error": "auth_rejected",
                    "error_description": "Authentication rejected by application",
                }
                spa_error_url = urlunparse(
                    (
                        parsed.scheme or "",
                        parsed.netloc or "",
                        parsed.path,
                        parsed.params,
                        urlencode(params),
                        parsed.fragment,
                    )
                )
                self.response.set_status(302, "Found")
                self.response.set_redirect(spa_error_url)
                return {"redirect_required": True, "redirect_url": spa_error_url}

        # Generate SPA session tokens (session_manager already initialized at start of method)
        spa_access_token = self.config.new_token()
        actor_id_str = actor_instance.id or ""
        session_manager.store_access_token(spa_access_token, actor_id_str, identifier)

        spa_refresh_token = session_manager.create_refresh_token(
            actor_id_str, identifier
        )

        # Build return path
        return_path = state_extras.get("return_path", "/app")
        if "{actor_id}" in return_path:
            final_redirect = return_path.replace("{actor_id}", actor_id_str)
        else:
            final_redirect = f"/{actor_id_str}{return_path}"

        # Store pending session data for SPA to retrieve
        # The SPA will call back to get this data using the session token
        pending_session_id = session_manager.store_session(
            token_data={
                "access_token": spa_access_token,
                "refresh_token": spa_refresh_token,
                "actor_id": actor_id_str,
                "email": identifier,
                "expires_at": int(time.time()) + 3600,
                "redirect_url": final_redirect,
            },
            user_info=user_info,
            state=state,
            provider=state_extras.get(
                "provider", getattr(self.config, "oauth2_provider", "google")
            ),
        )

        # Set HttpOnly cookie for refresh token (hybrid mode)
        token_delivery = state_extras.get("token_delivery", "json")
        if token_delivery == "hybrid" and self.response:
            self.response.set_cookie(
                "refresh_token",
                spa_refresh_token,
                max_age=86400 * 14,  # 2 weeks
                path="/oauth/spa/token",
                secure=True,
                httponly=True,
                samesite="Strict",
            )

        # Redirect to SPA callback with session token
        parsed = urlparse(spa_redirect_url)
        params = {"session": pending_session_id}
        spa_callback_url = urlunparse(
            (
                parsed.scheme or "",
                parsed.netloc or "",
                parsed.path,
                parsed.params,
                urlencode(params),
                parsed.fragment,
            )
        )

        logger.debug(f"SPA OAuth completed, redirecting to: {spa_callback_url}")
        self.response.set_status(302, "Found")
        self.response.set_redirect(spa_callback_url)
        return {"redirect_required": True, "redirect_url": spa_callback_url}


class OAuth2AppleCallbackHandler(OAuth2CallbackHandler):
    """Handles Apple's ``response_mode=form_post`` callback at POST /oauth/callback/apple.

    Apple POSTs the authorization response as a cross-site form submission. CSRF
    protection comes from a server-side single-use nonce (the ``state`` value is
    an opaque nonce; the full state payload is held server-side via
    ``StateNonceStore``). SameSite=Lax cookies are NOT relied upon for state
    binding here precisely because they do not survive Apple's cross-site POST.

    Two sub-flows, dispatched by the consumed payload's ``provider``:

    - ``apple`` (web/SPA): exchange the code with Apple (ES256 client_secret),
      validate the id_token, merge the first-sign-in ``user`` payload, and reuse
      the standard ``get()`` completion path.
    - ``apple-mobile`` (Android): persist the IdP ``code`` against an opaque
      ticket and deep-link the Capacitor app with only the ticket. No ActingWeb
      token is placed in the deep link.
    """

    def post(self) -> dict[str, Any]:
        from urllib.parse import parse_qs

        from ..oauth_state_store import StateNonceStore

        # Parse the form-encoded body.
        body = self.request.body
        if body is None:
            body_str = ""
        elif isinstance(body, bytes):
            body_str = body.decode("utf-8", "ignore")
        else:
            body_str = str(body)
        form = parse_qs(body_str)

        def _f(key: str) -> str:
            return form.get(key, [""])[0]

        error = _f("error")
        error_description = _f("error_description")
        state = _f("state")

        # Resolve the server-side state payload up front. On the error path this
        # lets us peek ``spa_mode`` so an SPA cancellation (Apple posts
        # ``error`` with ``response_mode=form_post``) bounces back to the app's
        # callback instead of rendering a backend error page — mirroring the GET
        # callback used by Google/GitHub.
        payload = StateNonceStore(self.config).consume(state) if state else None

        if error:
            logger.warning(f"Apple callback error: {error}")
            if self.config and payload and payload.get("spa_mode"):
                spa_redirect_url = str(payload.get("redirect_url", ""))
                if not spa_redirect_url or not is_safe_spa_redirect(
                    self.config, spa_redirect_url
                ):
                    spa_redirect_url = f"{self.config.proto}{self.config.fqdn}/"
                return self._redirect_to_spa_with_error(
                    spa_redirect_url, error, error_description
                )
            return self.error_response(400, f"Authentication failed: {error}")

        if not state:
            return self.error_response(400, "Missing state")

        if payload is None:
            logger.warning("Apple callback: invalid or expired state nonce")
            return self.error_response(400, "Invalid or expired state nonce")

        provider = str(payload.get("provider", "apple"))
        code = _f("code")
        id_token = _f("id_token")
        user_json = _f("user")

        # MCP (LLM-triggered) Apple flow: the nonce payload carries the encrypted
        # MCP state. Dispatch to the MCP OAuth2 server's completion path instead
        # of the SPA path.
        if "mcp_state" in payload:
            return self._dispatch_apple_mcp_callback(code, payload["mcp_state"])

        # Re-create the authenticator for the concrete Apple provider variant.
        self.authenticator = create_oauth2_authenticator(self.config, provider)

        logger.info(
            "Apple callback: provider=%s has_code=%s has_id_token=%s has_user=%s",
            provider,
            bool(code),
            bool(id_token),
            bool(user_json),
        )

        # Android flow: hand the code off via an opaque ticket deep link.
        if provider == "apple-mobile" or provider.startswith("apple-mobile"):
            return self._redirect_with_mobile_ticket(provider, code)

        # Web / SPA flow: stash the first-sign-in user payload and reuse the
        # standard callback completion by replaying it through get(). We rebuild
        # the request params with the JSON state payload so decode_state and the
        # SPA branch behave exactly as the GET callback does for Google/GitHub.
        if not code:
            return self.error_response(400, "Missing authorization code")

        self._pending_apple_user_json = user_json or None
        state_json = json.dumps(payload)
        new_params = {"code": code, "state": state_json}
        if id_token:
            new_params["id_token"] = id_token
        self.request.params = new_params
        return self.get()

    def _dispatch_apple_mcp_callback(self, code: str, mcp_state: str) -> dict[str, Any]:
        """Complete an LLM-triggered (MCP) Apple flow via the MCP OAuth2 server."""
        if not code:
            return self.error_response(400, "Missing authorization code")
        try:
            from ..oauth2_server.oauth2_server import ActingWebOAuth2Server

            server = ActingWebOAuth2Server(self.config)
            result = server.handle_oauth_callback({"code": code, "state": mcp_state})
        except Exception as e:
            logger.error(f"Apple MCP callback dispatch failed: {e}")
            return self.error_response(500, "Internal server error")

        if result.get("action") == "redirect" and result.get("url"):
            self.response.set_status(302, "Found")
            self.response.set_redirect(result["url"])
            return {"redirect_required": True, "redirect_url": result["url"]}

        error = result.get("error", "server_error")
        description = result.get("error_description", "OAuth2 callback failed")
        return self.error_response(400, f"{error}: {description}")
