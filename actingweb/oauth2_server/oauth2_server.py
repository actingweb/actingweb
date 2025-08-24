"""
OAuth2 Authorization Server implementation for ActingWeb MCP clients.

This module implements ActingWeb as a full OAuth2 authorization server that
can issue its own tokens to MCP clients while proxying user authentication
to Google OAuth2.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING
from urllib.parse import urlencode, urlparse, parse_qs

from .client_registry import get_mcp_client_registry
from .token_manager import get_actingweb_token_manager
from .state_manager import get_oauth2_state_manager
from ..oauth2 import create_oauth2_authenticator
from ..constants import OAUTH2_SYSTEM_ACTOR

if TYPE_CHECKING:
    from .. import config as config_class

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

        # Google OAuth2 authenticator for user authentication
        self.google_authenticator = create_oauth2_authenticator(config)

        if not self.google_authenticator.is_enabled():
            logger.warning("Google OAuth2 not configured - MCP OAuth2 server will not work properly")

    def handle_client_registration(
        self, registration_data: Dict[str, Any], actor_id: Optional[str] = None
    ) -> Dict[str, Any]:
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
                actor_id = self._get_or_create_system_actor()

            # Register the client
            response = self.client_registry.register_client(actor_id, registration_data)

            logger.debug(f"Registered MCP client {response['client_id']} for actor {actor_id}")
            return response

        except ValueError as e:
            raise ValueError(f"Client registration failed: {str(e)}")
        except Exception as e:
            logger.error(f"Client registration error: {e}")
            raise ValueError("Internal server error during client registration")

    def handle_authorization_request(self, params: Dict[str, Any], method: str = "GET") -> Dict[str, Any]:
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
            scope = params.get("scope", "")
            state = params.get("state", "")
            code_challenge = params.get("code_challenge")
            code_challenge_method = params.get("code_challenge_method", "plain")

            # Validate required parameters
            if not client_id:
                return self._error_response("invalid_request", "client_id is required")

            if not redirect_uri:
                return self._error_response("invalid_request", "redirect_uri is required")

            if response_type != "code":
                return self._error_response("unsupported_response_type", "Only 'code' response type is supported")

            # Validate client and redirect URI
            client_data = self.client_registry.validate_client(client_id)
            if not client_data:
                return self._error_response("invalid_client", "Invalid client_id")

            if not self.client_registry.validate_redirect_uri(client_id, redirect_uri):
                return self._error_response("invalid_request", "Invalid redirect_uri")

            # PKCE validation
            if code_challenge:
                if code_challenge_method not in ["plain", "S256"]:
                    return self._error_response("invalid_request", "Unsupported code_challenge_method")
                if code_challenge_method == "S256" and len(code_challenge) < 43:
                    return self._error_response("invalid_request", "code_challenge too short for S256")
            elif client_data.get("token_endpoint_auth_method") == "none":
                # For public clients (auth method "none"), PKCE is required
                return self._error_response("invalid_request", "code_challenge required for public clients")

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
                # Process email and redirect to Google
                email = params.get("email", "").strip()
                if not email:
                    return self._error_response("invalid_request", "Email is required")
                
                # Get trust type from form submission
                trust_type = params.get("trust_type", "mcp_client").strip()

                # Create state with MCP context including PKCE parameters and trust type
                logger.debug(f"Creating MCP state for client_id={client_id}, redirect_uri={redirect_uri}, state={state}, email={email}, trust_type={trust_type}")
                mcp_state = self.state_manager.create_mcp_state(
                    client_id=client_id, 
                    original_state=state, 
                    redirect_uri=redirect_uri, 
                    email_hint=email,
                    trust_type=trust_type,  # Add trust type to state
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method
                )
                logger.debug(f"Created MCP state: {mcp_state[:50]}... (truncated)")

                # Create Google OAuth2 authorization URL
                # For MCP flows, we need to use a special method that preserves the encrypted state
                logger.debug(f"Creating Google OAuth2 URL with MCP state and email hint")
                google_auth_url = self._create_google_oauth_url_for_mcp(mcp_state, email)
                logger.debug(f"Google OAuth2 URL created: {google_auth_url}")

                if not google_auth_url:
                    logger.error("Failed to create MCP Google OAuth2 URL, falling back to standard method")
                    # Fallback to standard method
                    google_auth_url = self.google_authenticator.create_authorization_url(
                        state=mcp_state, redirect_after_auth="", email_hint=email
                    )
                    logger.debug(f"Fallback Google OAuth2 URL created: {google_auth_url}")

                if not google_auth_url:
                    return self._error_response("server_error", "Failed to create authorization URL")

                return {"action": "redirect", "url": google_auth_url}

            else:
                return self._error_response("invalid_request", "Method not allowed")

        except Exception as e:
            logger.error(f"Authorization request error: {e}")
            return self._error_response("server_error", "Internal server error")

    def handle_oauth_callback(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                return self._error_response("access_denied", f"Google OAuth2 error: {error}")

            if not code or not state:
                return self._error_response("invalid_request", "Missing code or state parameter")

            # Debug: log the received state parameter
            logger.debug(f"OAuth2 callback received state parameter: {state[:50]}... (truncated)")
            
            # Extract MCP context from state
            mcp_context = self.state_manager.extract_mcp_context(state)
            logger.debug(f"Extracted MCP context: {mcp_context}")
            if not mcp_context:
                logger.warning(f"Failed to extract MCP context from state: {state}")
                return self._error_response("invalid_request", "Invalid or expired state parameter")

            client_id = mcp_context.get("client_id")
            redirect_uri = mcp_context.get("redirect_uri")
            original_state = mcp_context.get("original_state")
            code_challenge = mcp_context.get("code_challenge")
            code_challenge_method = mcp_context.get("code_challenge_method")

            if not client_id or not redirect_uri:
                return self._error_response("invalid_request", "Invalid MCP context in state")

            # Exchange Google authorization code for tokens
            google_token_data = self.google_authenticator.exchange_code_for_token(code, "")
            if not google_token_data:
                return self._error_response("invalid_grant", "Failed to exchange Google authorization code")

            # Get user info from Google
            access_token = google_token_data.get("access_token", "")
            user_info = self.google_authenticator.validate_token_and_get_user_info(access_token)
            if not user_info:
                return self._error_response("invalid_grant", "Failed to get user information from Google")

            email = user_info.get("email")
            if not email:
                return self._error_response("invalid_grant", "No email address from Google")

            # Get or create actor for this user
            actor_obj = self._get_or_create_actor_for_email(email)
            if not actor_obj:
                return self._error_response("server_error", "Failed to create or retrieve user actor")

            # Extract trust_type from MCP context if present
            trust_type = mcp_context.get("trust_type", "mcp_client")

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

            logger.debug(f"Completed OAuth2 authorization for MCP client {client_id}, user {email}")

            return {"action": "redirect", "url": callback_url}

        except Exception as e:
            logger.error(f"OAuth2 callback error: {e}")
            return self._error_response("server_error", "Internal server error")

    def handle_token_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
            else:
                return self._error_response("unsupported_grant_type", f"Grant type '{grant_type}' not supported")

        except Exception as e:
            logger.error(f"Token request error: {e}")
            return self._error_response("server_error", "Internal server error")

    def _handle_authorization_code_grant(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle authorization_code grant type."""
        # Debug: log all received parameters
        logger.debug(f"Token request parameters: {list(params.keys())}")
        logger.debug(f"Token request values: {params}")
        
        code = params.get("code")
        client_id = params.get("client_id")
        client_secret = params.get("client_secret")
        redirect_uri = params.get("redirect_uri")  # Must match authorization request
        code_verifier = params.get("code_verifier")

        if not code:
            return self._error_response("invalid_request", "code is required")
        if not client_id:
            logger.warning(f"Missing client_id in token request. Available params: {list(params.keys())}")
            return self._error_response("invalid_request", "client_id is required")
        if not redirect_uri:
            return self._error_response("invalid_request", "redirect_uri is required")

        # Validate client credentials (allow both secret-based and PKCE-based auth)
        client_data = self.client_registry.validate_client(client_id, client_secret)
        if not client_data:
            # For PKCE clients, allow validation without client_secret
            client_data = self.client_registry.validate_client(client_id)
            if not client_data or client_data.get("token_endpoint_auth_method") != "none":
                return self._error_response("invalid_client", "Invalid client credentials")

        # PKCE validation for public clients
        if client_data.get("token_endpoint_auth_method") == "none":
            if not code_verifier:
                return self._error_response("invalid_request", "code_verifier required for public clients")

        # Exchange authorization code for ActingWeb token
        token_response = self.token_manager.exchange_authorization_code(
            code=code, client_id=client_id, client_secret=client_secret, code_verifier=code_verifier
        )

        if not token_response:
            return self._error_response("invalid_grant", "Invalid or expired authorization code")

        # Create or refresh MCP trust at token issuance
        try:
            actor_id = token_response.get("actor_id")
            email = token_response.get("email")
            # Prefer trust_type from state if carried through token manager
            trust_type = token_response.get("trust_type", "mcp_client")
            if actor_id and email:
                from .. import actor as actor_module
                from ..interface.actor_interface import ActorInterface
                from ..interface.trust_manager import TrustManager
                actor_obj = actor_module.Actor(actor_id, self.config)
                if actor_obj and actor_obj.id:
                    actor_interface = ActorInterface(actor_obj)
                    tm = TrustManager(actor_interface.core_actor)
                    tm.create_or_update_oauth_trust(
                        email=email,
                        trust_type=trust_type,
                        oauth_tokens=None,
                        established_via="mcp",
                    )
        except Exception as e:
            logger.warning(f"Failed to create MCP trust at token issuance: {e}")

        logger.debug(f"Issued ActingWeb access token for client {client_id}")
        return token_response

    def _handle_refresh_token_grant(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
            refresh_token=refresh_token, client_id=client_id, client_secret=client_secret
        )

        if not token_response:
            return self._error_response("invalid_grant", "Invalid or expired refresh token")

        logger.debug(f"Refreshed ActingWeb access token for client {client_id}")
        return token_response

    def handle_discovery_request(self) -> Dict[str, Any]:
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
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
            "code_challenge_methods_supported": ["S256"],
            "service_documentation": f"{base_url}/mcp/info",
            "mcp_resource": f"{base_url}/mcp",
        }

    def validate_mcp_token(self, token: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """
        Validate ActingWeb token for MCP endpoints.

        Args:
            token: ActingWeb access token

        Returns:
            Tuple of (actor_id, client_id, token_data) or None if invalid
        """
        return self.token_manager.validate_access_token(token)

    def _get_or_create_system_actor(self) -> str:
        """Get or create a system actor for MCP clients."""
        # For now, use a fixed system actor ID
        # In production, you might want per-client actors or other strategies
        return OAUTH2_SYSTEM_ACTOR

    def _get_or_create_actor_for_email(self, email: str) -> Optional[Any]:
        """Get or create actor for email address."""
        try:
            from .. import actor as actor_module
            from ..interface.actor_interface import ActorInterface

            # First check if actor already exists with this email as creator
            if self.config.unique_creator:
                from ..db_dynamodb.db_actor import DbActor
                db_actor = DbActor()
                existing = db_actor.get_by_creator(creator=email)
                if existing:
                    # Handle both single dict and list of dicts return types
                    if isinstance(existing, dict):
                        # Single actor found
                        actor_id = existing["id"]
                        logger.debug(f"Found existing actor {actor_id} for email {email}")
                        actor_obj = actor_module.Actor(actor_id, self.config)
                        # Load the actor data
                        actor_obj.get(actor_id)
                        return actor_obj
                    elif isinstance(existing, list) and len(existing) > 0:
                        # Multiple actors found, use the first one
                        actor_id = existing[0]["id"]
                        logger.debug(f"Found existing actor {actor_id} for email {email}")
                        actor_obj = actor_module.Actor(actor_id, self.config)
                        # Load the actor data
                        actor_obj.get(actor_id)
                        return actor_obj

            # Create new actor using ActorInterface for proper lifecycle hook execution
            try:
                passphrase = self.config.new_token() if self.config else ""
                actor_interface = ActorInterface.create(
                    creator=email,
                    config=self.config,
                    passphrase=passphrase,
                    hooks=getattr(self.config, '_hooks', None)  # Pass hooks if available for lifecycle events
                )
                
                # Get the core actor for backward compatibility
                actor_obj = actor_interface.core_actor
                
                # The actor should now have its ID set from the create() method
                if not actor_obj.id:
                    logger.error(f"Actor creation succeeded but ID is not set")
                    return None
                    
            except Exception as create_error:
                logger.error(f"Failed to create actor for email {email}: {create_error}")
                return None
                
            logger.debug(f"Successfully created actor {actor_obj.id} for email {email}")
            
            # Verify the actor has the necessary components
            if not actor_obj.property:
                logger.error(f"Actor {actor_obj.id} does not have property object set after creation")
                return None

            logger.debug(f"Successfully created/retrieved actor {actor_obj.id} with property object")
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
            logger.debug(f"Attempting to create MCP Google OAuth2 URL...")
            logger.debug(f"Authenticator enabled: {self.google_authenticator.is_enabled()}")
            logger.debug(f"Client exists: {self.google_authenticator.client is not None}")
            
            if not self.google_authenticator.is_enabled():
                logger.error("Google authenticator is not enabled")
                return ""
                
            if not self.google_authenticator.client:
                logger.error("Google authenticator client is None")
                return ""
                
            # Get the provider config
            provider = self.google_authenticator.provider
            logger.debug(f"Provider auth URI: {provider.auth_uri}")
            logger.debug(f"Provider redirect URI: {provider.redirect_uri}")
            logger.debug(f"Provider scope: {provider.scope}")
            
            # Prepare Google OAuth2 parameters
            extra_params = {
                "access_type": "offline",  # For Google to get refresh token
                "prompt": "consent",  # Force consent to get refresh token
            }
            
            # Add email hint for Google OAuth2
            if email_hint:
                extra_params["login_hint"] = email_hint
                logger.debug(f"Adding login_hint for MCP OAuth2: {email_hint}")
            
            # Use oauthlib directly to generate the authorization URL with the encrypted state
            logger.debug(f"Calling prepare_request_uri with state: {mcp_state[:50]}...")
            authorization_url = self.google_authenticator.client.prepare_request_uri(
                provider.auth_uri,
                redirect_uri=provider.redirect_uri,
                scope=provider.scope.split(),
                state=mcp_state,  # Use the encrypted MCP state directly
                **extra_params,
            )
            
            logger.debug(f"Created MCP Google OAuth2 URL with encrypted state: {mcp_state[:50]}...")
            logger.debug(f"Authorization URL: {authorization_url[:200]}...")
            return str(authorization_url)
            
        except Exception as e:
            logger.error(f"Error creating Google OAuth2 URL for MCP: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return ""

    def _error_response(self, error: str, description: str) -> Dict[str, Any]:
        """Create OAuth2 error response."""
        return {"error": error, "error_description": description}


# Global OAuth2 server instance
_oauth2_server: Optional[ActingWebOAuth2Server] = None


def get_actingweb_oauth2_server(config: "config_class.Config") -> ActingWebOAuth2Server:
    """Get or create the global ActingWeb OAuth2 server."""
    global _oauth2_server
    if _oauth2_server is None:
        _oauth2_server = ActingWebOAuth2Server(config)
    return _oauth2_server
