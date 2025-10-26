"""
OAuth2 callback handler for ActingWeb.

This handler processes OAuth2 callbacks from various providers after user authentication,
exchanges the authorization code for an access token, and sets up the user session.
Uses the consolidated oauth2 module for provider-agnostic OAuth2 handling.
"""

import logging
import time
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

from .base_handler import BaseHandler

if TYPE_CHECKING:
    from .. import aw_web_request
    from ..interface.hooks import HookRegistry
from .. import config as config_class
from ..oauth2 import create_oauth2_authenticator, create_oauth2_trust_relationship
from ..oauth_state import decode_state, validate_expected_email

logger = logging.getLogger(__name__)


class OAuth2CallbackHandler(BaseHandler):
    """
    Handles OAuth2 callbacks at /oauth/callback for Google/GitHub OAuth flows.

    This handler processes TWO types of OAuth2 flows:

    1. Web UI Login (no trust_type in state):
       - User clicks "Login with Google/GitHub" on factory page
       - After OAuth, creates/looks up actor and redirects to /www
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

    def __init__(self, webobj: Optional['aw_web_request.AWWebObj'] = None, config: config_class.Config | None = None, hooks: Optional['HookRegistry'] = None) -> None:
        if config is None:
            raise RuntimeError("Config is required for OAuth2CallbackHandler")
        if webobj is None:
            from .. import aw_web_request
            webobj = aw_web_request.AWWebObj()
        super().__init__(webobj, config, hooks)
        # Use generic OAuth2 authenticator (configurable provider)
        self.authenticator = create_oauth2_authenticator(config) if config else None

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

        # Check for error parameter
        error = self.request.get("error")
        if error:
            error_description = self.request.get("error_description")
            if not error_description:
                error_description = ""
            logger.warning(f"OAuth2 error: {error} - {error_description}")
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
        _, redirect_url, actor_id, trust_type, _expected_email, user_agent = decode_state(state)
        logger.debug(f"Parsed state - redirect_url: '{redirect_url}', actor_id: '{actor_id}', trust_type: '{trust_type}'")

        # Critical debug: Check if trust_type was parsed correctly
        if trust_type:
            logger.debug(f"Trust type '{trust_type}' found in state - will create trust relationship")
        else:
            logger.warning("No trust_type found in parsed state - trust relationship will NOT be created")

        # Exchange code for access token
        token_data = self.authenticator.exchange_code_for_token(code, state)
        if not token_data or "access_token" not in token_data:
            logger.error("Failed to exchange authorization code for access token")
            return self.error_response(502, "Token exchange failed")

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        # Validate token and get user info
        user_info = self.authenticator.validate_token_and_get_user_info(access_token)
        if not user_info:
            logger.error("Failed to validate token or extract user info")
            return self.error_response(502, "Token validation failed")

        # Determine if email is required based on config
        require_email = bool(
            self.config and
            getattr(self.config, 'force_email_prop_as_creator', False)
        )

        logger.debug(f"OAuth identifier extraction mode: require_email={require_email}")

        # Extract identifier (email or provider ID) based on config
        identifier = self.authenticator.get_email_from_user_info(
            user_info,
            access_token,
            require_email=require_email
        )

        if not identifier:
            logger.warning("Failed to extract identifier from user info")

            # If in provider ID mode (require_email=False), this is a critical error
            if not require_email:
                logger.error("Provider ID mode enabled but no identifier available from OAuth provider")
                return self.error_response(
                    502,
                    "OAuth provider did not return user identifier. Please contact support."
                )

            # Email required mode - try to get verified emails for dropdown
            verified_emails: list[str] | None = None

            if self.authenticator.provider.name == "github" and access_token:
                verified_emails = self.authenticator._get_github_verified_emails(access_token)
                if verified_emails:
                    logger.info(f"Found {len(verified_emails)} verified emails from GitHub")

            # Check if this is an MCP authorization flow
            if trust_type:
                logger.error("Cannot complete MCP authorization without identifier")
                return self.error_response(
                    502,
                    f"Email required but not provided by OAuth provider. "
                    f"Configure your {self.authenticator.provider.name} account to make email public."
                )

            # Web UI flow - redirect to email input form
            logger.info("Web UI login flow - redirecting to email input form")
            try:
                from ..oauth_session import get_oauth2_session_manager

                session_manager = get_oauth2_session_manager(self.config)
                provider_name = getattr(self.config, 'oauth2_provider', 'google')
                session_id = session_manager.store_session(
                    token_data=token_data,
                    user_info=user_info,
                    state=state,
                    provider=provider_name,
                    verified_emails=verified_emails  # NEW: Pass verified emails
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
                    "redirect_performed": True
                }

            except Exception as session_error:
                logger.error(f"Failed to create OAuth session: {session_error}")
                # Fall back to error response if session storage fails
                return self.error_response(502, "Email extraction failed and could not store session")

        # Validate identifier format based on mode
        if require_email:
            # Must be a valid email
            if "@" not in identifier:
                logger.error(f"force_email_prop_as_creator enabled but got non-email: {identifier}")
                return self.error_response(
                    502,
                    "Configuration requires email but OAuth provider returned non-email identifier"
                )

            # Validate against expected email from form (if provided)
            if not validate_expected_email(state, identifier):
                logger.error(f"Email validation failed - authenticated as {identifier}")
                return self.error_response(
                    403,
                    "Authentication email does not match the email provided in the form"
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
                    logger.warning(f"Actor {actor_id} from state not found, will lookup/create by identifier")
                    actor_instance = None
                else:
                    logger.debug(f"Using existing actor {actor_id} from state parameter")

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
                                f"You authenticated as '{identifier}' but this actor belongs to '{actor_instance.creator}'."
                            )
                        else:
                            # Web login - potential session fixation attack
                            return self.error_response(
                                403,
                                f"Authentication failed: You authenticated as '{identifier}' but attempted to "
                                f"access an actor belonging to '{actor_instance.creator}'. Please log in with the correct account."
                            )

            except Exception as e:
                logger.warning(f"Failed to load actor {actor_id} from state: {e}, will lookup/create by identifier")
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
                user_info=user_info  # Pass user_info for additional metadata
            )
            if not actor_instance:
                logger.error(f"Failed to lookup or create actor for identifier {identifier}")
                return self.error_response(502, "Actor creation failed")

        # Store OAuth tokens in actor properties
        # The auth system expects oauth_token (not oauth_access_token)
        if actor_instance.store:
            actor_instance.store.oauth_token = access_token  # This is what auth.py looks for
            actor_instance.store.oauth_token_expiry = str(int(time.time()) + expires_in) if expires_in else None
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

                    logger.debug(f"Extracted MCP client metadata: {client_name} v{client_version} on {client_platform}")

            except Exception as e:
                logger.debug(f"Could not retrieve MCP client info during OAuth callback: {e}")
                # Continue with User-Agent as platform info
                # Non-critical, don't fail the OAuth flow

        # Create trust relationship if trust_type was specified in state
        logger.debug(f"About to check trust_type for relationship creation: trust_type='{trust_type}'")
        if trust_type:
            logger.info(f"Creating trust relationship for trust_type='{trust_type}' and identifier='{identifier}'")
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(core_actor=actor_instance, service_registry=registry)

                # Prepare OAuth tokens for secure storage
                oauth_tokens = {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": int(time.time()) + expires_in if expires_in else 0,
                    "token_type": token_data.get("token_type", "Bearer")
                }

                # Create trust relationship with automatic approval and client metadata
                trust_created = create_oauth2_trust_relationship(
                    actor_interface,
                    identifier,
                    trust_type,
                    oauth_tokens,
                    client_name=client_name,
                    client_version=client_version,
                    client_platform=client_platform
                )

                if trust_created:
                    logger.info(f"Successfully created trust relationship: {identifier} -> {trust_type}")
                else:
                    logger.warning(f"Failed to create trust relationship for {identifier} with type {trust_type}")

            except Exception as e:
                logger.error(f"Error creating OAuth2 trust relationship: {e}")
                # Don't fail the OAuth flow - just log the error

        # Execute actor_created lifecycle hook for new actors
        if is_new_actor and self.hooks:
            try:
                # Convert core Actor to ActorInterface for hook consistency
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(core_actor=actor_instance, service_registry=registry)
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
                actor_interface = ActorInterface(core_actor=actor_instance, service_registry=registry)

                result = self.hooks.execute_lifecycle_hooks(
                    "oauth_success",
                    actor_interface,
                    email=identifier,  # Pass identifier (may be email or provider ID)
                    access_token=access_token,
                    token_data=token_data
                )
                oauth_valid = bool(result) if result is not None else True
            except Exception as e:
                logger.error(f"Error in lifecycle hook for oauth_success: {e}")
                oauth_valid = False

        if not oauth_valid:
            logger.warning(f"OAuth success hook rejected authentication for {identifier}")
            return self.error_response(403, "Authentication rejected")

        # Set up successful response
        response_data = {
            "status": "success",
            "message": "Authentication successful",
            "actor_id": actor_instance.id,
            "email": identifier,  # identifier (may be email or provider ID)
            "access_token": access_token,
            "expires_in": expires_in
        }

        # For interactive web authentication, redirect to the actor's www page
        # For API clients, they would use the Bearer token directly

        # For interactive authentication, always redirect to actor's www page
        # This avoids authentication loops with the original URL
        final_redirect = f"/{actor_instance.id}/www"
        logger.debug(f"Redirecting to actor www page: {final_redirect}")

        # Log the original URL for reference but don't use it
        if redirect_url:
            logger.debug(f"Original URL was: {redirect_url} (redirecting to www page instead)")

        # Set session cookie so user stays authenticated after redirect
        # The cookie should match the token stored in the actor (oauth_token)
        stored_token = actor_instance.store.oauth_token if actor_instance.store else access_token
        # Set a longer cookie expiry (2 weeks like ActingWeb default) since OAuth tokens are usually valid for 1 hour
        # but we want the session to persist longer than that
        cookie_max_age = 1209600  # 2 weeks, matching ActingWeb's default

        self.response.set_cookie(
            "oauth_token",
            str(stored_token),
            max_age=cookie_max_age,
            path="/",
            secure=True
        )

        logger.debug(f"Set oauth_token cookie with token length {len(str(stored_token))} and max_age {cookie_max_age}")

        # Perform the redirect for interactive authentication
        self.response.set_status(302, "Found")
        self.response.set_redirect(final_redirect)

        # Also include the information in the response data for completeness
        response_data["redirect_url"] = final_redirect
        response_data["redirect_performed"] = True

        # Execute OAuth completed lifecycle hook
        if self.hooks:
            try:
                self.hooks.execute_lifecycle_hooks(
                    "oauth_completed",
                    actor_instance,
                    email=identifier,
                    access_token=access_token,
                    redirect_url=response_data["redirect_url"]
                )
            except Exception as e:
                logger.error(f"Error executing oauth_completed hook: {e}")

        logger.debug(f"OAuth2 authentication completed successfully for {identifier} -> {actor_instance.id}")
        return response_data


    def _is_safe_redirect(self, url: str) -> bool:
        """
        Check if redirect URL is safe (same domain).

        Args:
            url: URL to validate

        Returns:
            True if URL is safe to redirect to
        """
        if not url:
            return False

        try:
            # Parse the URL
            parsed = urlparse(url)

            # Allow relative URLs (no scheme/netloc)
            if not parsed.scheme and not parsed.netloc:
                return True

            # Allow same domain redirects
            if parsed.netloc == self.config.fqdn:
                return True

            # Reject external redirects
            return False

        except Exception:
            return False

    def error_response(self, status_code: int, message: str) -> dict[str, Any]:
        """Create error response with template rendering for user-friendly errors."""
        self.response.set_status(status_code)

        # For user-facing errors, try to render template
        if status_code in [403, 400] and hasattr(self.response, 'template_values'):
            self.response.template_values = {
                "error": message,
                "status_code": status_code
            }

        return {
            "error": True,
            "status_code": status_code,
            "message": message
        }
