"""
OAuth2 Authorization Server implementation for ActingWeb MCP clients.

This module implements ActingWeb as a full OAuth2 authorization server that
can issue its own tokens to MCP clients while proxying user authentication
to Google OAuth2.
"""

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from ..oauth2 import create_oauth2_authenticator
from .client_registry import get_mcp_client_registry
from .state_manager import get_oauth2_state_manager
from .token_manager import get_actingweb_token_manager

if TYPE_CHECKING:
    from .. import config as config_class
    from ..actor import Actor
    from ..interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


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

        # OAuth2 authenticators for user authentication
        self.google_authenticator = create_oauth2_authenticator(config, "google")
        self.github_authenticator = create_oauth2_authenticator(config, "github")

        if (
            not self.google_authenticator.is_enabled()
            and not self.github_authenticator.is_enabled()
        ):
            logger.warning(
                "OAuth2 not configured - MCP OAuth2 server will not work properly"
            )

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
                # In practice, this might come from authentication or be a default
                # For now, we'll create a system actor for the client
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
        except Exception as e:
            logger.error(f"Client registration error: {e}")
            raise ValueError("Internal server error during client registration") from e

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
            code_challenge = params.get("code_challenge")
            code_challenge_method = params.get("code_challenge_method", "plain")

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

            # PKCE validation
            if code_challenge:
                if code_challenge_method not in ["plain", "S256"]:
                    return self._error_response(
                        "invalid_request", "Unsupported code_challenge_method"
                    )
                if code_challenge_method == "S256" and len(code_challenge) < 43:
                    return self._error_response(
                        "invalid_request", "code_challenge too short for S256"
                    )
            elif client_data.get("token_endpoint_auth_method") == "none":
                # For public clients (auth method "none"), PKCE is required
                return self._error_response(
                    "invalid_request", "code_challenge required for public clients"
                )

            if method == "GET":
                # Show email form (same UX as GET /)
                return {
                    "action": "show_form",
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "state": state,
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

                # Get trust type from form submission
                trust_type = params.get("trust_type", "mcp_client").strip()

                # Create state with MCP context including PKCE parameters and trust type
                mcp_state = self.state_manager.create_mcp_state(
                    client_id=client_id,
                    original_state=state,
                    redirect_uri=redirect_uri,
                    email_hint=email if email else None,
                    trust_type=trust_type,  # Add trust type to state
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                )

                # Create OAuth2 authorization URL based on provider
                oauth_url = None
                if provider == "github":
                    # GitHub OAuth flow
                    oauth_url = self.github_authenticator.create_authorization_url(
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

        except Exception as e:
            logger.error(f"Authorization request error: {e}")
            return self._error_response("server_error", "Internal server error")

    def handle_oauth_callback(self, params: dict[str, Any]) -> dict[str, Any]:
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

            # Exchange Google authorization code for tokens
            google_token_data = self.google_authenticator.exchange_code_for_token(
                code, ""
            )
            if not google_token_data:
                return self._error_response(
                    "invalid_grant", "Failed to exchange Google authorization code"
                )

            # Get user info from Google
            access_token = google_token_data.get("access_token", "")
            user_info = self.google_authenticator.validate_token_and_get_user_info(
                access_token
            )
            if not user_info:
                return self._error_response(
                    "invalid_grant", "Failed to get user information from Google"
                )

            email = user_info.get("email")
            if not email:
                return self._error_response(
                    "invalid_grant", "No email address from Google"
                )

            # Get or create actor for this user
            actor_obj = self._get_or_create_actor_for_email(email)
            if not actor_obj:
                return self._error_response(
                    "server_error", "Failed to create or retrieve user actor"
                )

            # Determine trust type and establishment source
            trust_type = mcp_context.get("trust_type", "mcp_client")
            flow_type = mcp_context.get("flow_type")

            # Distinguish between OAuth2 interactive flows and client credentials flows
            if flow_type == "mcp_oauth2":
                established_via = "oauth2_client"  # MCP client credentials flow
            else:
                established_via = "oauth2_interactive"  # Regular user interactive flow

            effective_trust_type = trust_type if trust_type else "mcp_client"

            # Always create or update trust; select type based on flow
            try:
                from ..interface.actor_interface import ActorInterface
                from ..oauth2 import create_oauth2_trust_relationship

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor_obj, service_registry=registry
                )
                trust_created = create_oauth2_trust_relationship(
                    actor=actor_interface,
                    email=email,
                    trust_type=str(effective_trust_type),
                    oauth_tokens=dict(google_token_data),
                    established_via=established_via,
                    client_id=client_id,
                )
                if not trust_created:
                    logger.warning(
                        f"Failed to create trust for actor {actor_obj.id} and user {email} (via={established_via}, type={effective_trust_type})"
                    )
            except Exception as trust_error:
                logger.error(
                    f"Exception while creating trust for actor {actor_obj.id}: {trust_error}"
                )

            # Create authorization code for MCP client (store email and trust_type for later token exchange)
            auth_code = self.token_manager.create_authorization_code(
                actor_id=actor_obj.id,
                client_id=client_id,
                google_token_data=google_token_data,
                user_email=email,
                trust_type=trust_type,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
            )

            # Build redirect URL back to MCP client
            redirect_params = {"code": auth_code}
            if original_state:
                redirect_params["state"] = original_state

            callback_url = f"{redirect_uri}?{urlencode(redirect_params)}"

            logger.info(
                f"OAuth2 authorization completed for client {client_id}, user {email}"
            )

            # Store MCP client info if available from initialization
            self._store_mcp_client_info_in_trust(actor_obj, client_id)

            return {"action": "redirect", "url": callback_url}

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

        except Exception as e:
            logger.error(f"Token request error: {e}")
            return self._error_response("server_error", "Internal server error")

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

        # Validate client credentials (allow both secret-based and PKCE-based auth)
        client_data = self.client_registry.validate_client(client_id, client_secret)
        if not client_data:
            # For PKCE clients, allow validation without client_secret
            client_data = self.client_registry.validate_client(client_id)
            if (
                not client_data
                or client_data.get("token_endpoint_auth_method") != "none"
            ):
                return self._error_response(
                    "invalid_client", "Invalid client credentials"
                )

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

        # Validate client credentials
        client_data = self.client_registry.validate_client(client_id, client_secret)
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

        if not client_secret:
            return self._error_response("invalid_request", "client_secret is required")

        # Validate client credentials
        client_data = self.client_registry.validate_client(client_id, client_secret)
        if not client_data:
            return self._error_response("invalid_client", "Invalid client credentials")

        # Get the actor ID associated with this client
        actor_id = client_data.get("actor_id")
        if not actor_id:
            logger.error(f"No actor_id found for client {client_id}")
            return self._error_response(
                "invalid_client", "Client not properly configured"
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
            "scopes_supported": ["mcp"],
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
            Response indicating logout success
        """
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
                except Exception as revoke_error:
                    logger.error(
                        f"Token revocation failed with exception: {revoke_error}"
                    )
                    import traceback

                    logger.error(
                        f"Token revocation error traceback: {traceback.format_exc()}"
                    )
                    # Continue with logout process even if revocation fails
            else:
                logger.info("Logout requested without token - clearing cookies only")

            return {
                "action": "success",
                "message": "Successfully logged out",
                "clear_cookies": ["oauth_token", "oauth_refresh_token", "session_id"],
                "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
            }

        except Exception as e:
            logger.error(f"Logout request error: {e}")
            import traceback

            logger.error(f"Full logout error traceback: {traceback.format_exc()}")
            return {
                "action": "success",  # Still return success to clear cookies
                "message": "Logged out (with errors)",
                "clear_cookies": ["oauth_token", "oauth_refresh_token", "session_id"],
                "redirect_url": f"{self.config.proto}{self.config.fqdn}/",
            }

    def _get_or_create_actor_for_email(self, email: str) -> Any | None:
        """Get or create actor for email address."""
        try:
            from .. import actor as actor_module
            from ..interface.actor_interface import ActorInterface

            # Attempt to find an existing actor for this email
            existing_actor = actor_module.Actor(config=self.config)
            if existing_actor.get_from_creator(email):
                return existing_actor

            # Create new actor using ActorInterface for proper lifecycle hook execution
            try:
                passphrase = self.config.new_token() if self.config else ""
                actor_interface = ActorInterface.create(
                    creator=email,
                    config=self.config,
                    passphrase=passphrase,
                    hooks=getattr(
                        self.config, "_hooks", None
                    ),  # Pass hooks if available for lifecycle events
                )

                # Get the core actor for backward compatibility
                actor_obj = actor_interface.core_actor

                # The actor should now have its ID set from the create() method
                if not actor_obj.id:
                    logger.error("Actor creation succeeded but ID is not set")
                    return None

            except Exception as create_error:
                logger.error(
                    f"Failed to create actor for email {email}: {create_error}"
                )
                return None

            # Verify the actor has the necessary components
            if not actor_obj.property:
                logger.error(
                    f"Actor {actor_obj.id} does not have property object set after creation"
                )
                return None

            return actor_obj

        except Exception as e:
            logger.error(f"Error creating actor for email {email}: {e}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
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

        except Exception as e:
            logger.error(f"Error creating Google OAuth2 URL for MCP: {e}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            return ""

    def _store_mcp_client_info_in_trust(
        self, actor_obj: "Actor", client_id: str
    ) -> None:
        """Store MCP client info in the trust relationship for the OAuth2 client."""
        try:
            import time

            from ..handlers.mcp import _mcp_client_info_cache

            # Search through all cached client info to find match for this client
            # This is a fallback approach since we don't have request context here
            client_info = None

            # Try to find client info in the cache (there should only be one recent entry)
            current_time = time.time()
            for _session_key, data in _mcp_client_info_cache.items():
                if current_time - data["timestamp"] < 600:  # Within 10 minutes
                    client_info = data["client_info"]
                    break

            if client_info and actor_obj:
                # Store client metadata in trust relationship (new approach)
                from ..interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(actor_obj, service_registry=registry)
                client_name = client_info.get("name", "mcp_client")

                # Update trust relationship with client metadata instead of actor properties
                self._update_trust_with_client_info_oauth(
                    actor_interface, client_id, client_info
                )

                logger.info(
                    f"Stored MCP client info in trust relationship for actor {actor_obj.id}, client {client_name}"
                )

        except Exception as e:
            logger.debug(f"Could not store MCP client info: {e}")
            # This is not critical, so we don't raise the exception

    def _update_trust_with_client_info_oauth(
        self,
        actor_interface: "ActorInterface",
        client_id: str,
        client_info: dict[str, Any],
    ) -> None:
        """
        Update trust relationship with MCP client metadata for OAuth2 server context.

        Args:
            actor_interface: ActorInterface instance
            client_id: OAuth2 client ID to find the trust relationship
            client_info: Client metadata to store in trust relationship
        """
        try:
            # Find the trust relationship for this OAuth2 client
            # Look for trust relationship with this client_id as oauth_client_id
            all_trusts = actor_interface.trust.relationships
            target_trust = None

            for trust in all_trusts:
                if (
                    getattr(trust, "oauth_client_id", None) == client_id
                    or getattr(trust, "peer_identifier", "") == client_id
                ):
                    target_trust = trust
                    break

            if not target_trust:
                logger.debug(
                    f"No trust relationship found for OAuth2 client {client_id}"
                )
                return

            # Extract client metadata
            client_name = client_info.get("name", "MCP Client")
            client_version = client_info.get("version")
            client_platform = None

            # Try to extract platform from implementation
            if "implementation" in client_info:
                impl = client_info["implementation"]
                if isinstance(impl, dict):
                    client_platform = (
                        f"{impl.get('name', 'Unknown')} {impl.get('version', '')}"
                    )

            # Check if client info has actually changed before updating
            existing_name = getattr(target_trust, "client_name", None)
            existing_version = getattr(target_trust, "client_version", None)
            existing_platform = getattr(target_trust, "client_platform", None)

            # Skip update if client info hasn't changed
            if (
                existing_name == client_name
                and existing_version == client_version
                and existing_platform == client_platform
            ):
                return

            # Update the trust relationship
            from .. import actor as actor_module

            core_actor = actor_module.Actor(actor_interface.id, config=self.config)
            if core_actor.actor:
                success = core_actor.modify_trust_and_notify(
                    peerid=target_trust.peerid,
                    client_name=client_name,
                    client_version=client_version,
                    client_platform=client_platform,
                )
                if success:
                    logger.info(
                        f"Updated trust relationship {target_trust.peerid} with OAuth2 client info: {client_name}"
                    )
                else:
                    logger.warning(
                        f"Failed to update trust relationship {target_trust.peerid} with OAuth2 client info"
                    )

        except Exception as e:
            logger.debug(f"Could not update trust with OAuth2 client info: {e}")

    def _error_response(self, error: str, description: str) -> dict[str, Any]:
        """Create OAuth2 error response."""
        return {"error": error, "error_description": description}


# Global OAuth2 server instance
_oauth2_server: ActingWebOAuth2Server | None = None


def get_actingweb_oauth2_server(config: "config_class.Config") -> ActingWebOAuth2Server:
    """Get or create the global ActingWeb OAuth2 server."""
    global _oauth2_server
    if _oauth2_server is None:
        _oauth2_server = ActingWebOAuth2Server(config)
    return _oauth2_server
