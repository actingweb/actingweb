"""
OAuth2 endpoints handler for ActingWeb.

This handler provides standard OAuth2 endpoints for ActingWeb's OAuth2 authorization server:
- /oauth/register - Dynamic client registration (RFC 7591) for MCP clients
- /oauth/authorize - OAuth2 authorization endpoint (email form → Google → MCP client)
- /oauth/token - OAuth2 token endpoint (issues ActingWeb tokens)
- /oauth/callback - OAuth2 callback from Google (completes MCP flow)

ActingWeb acts as an OAuth2 authorization server for MCP clients while
proxying user authentication to Google OAuth2.
"""

import json
import logging
from typing import Dict, Any, Optional, TYPE_CHECKING, Union
from urllib.parse import urlencode, urlparse

from .base_handler import BaseHandler

if TYPE_CHECKING:
    from ..interface.hooks import HookRegistry
    from .. import aw_web_request
    from .. import config as config_class

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

    def post(self, path: str = "") -> Dict[str, Any]:
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
        else:
            return self.error_response(404, f"Unknown OAuth2 endpoint: {path}")

    def options(self, path: str = "") -> Dict[str, Any]:
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
        self.response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        self.response.headers["Access-Control-Max-Age"] = "86400"  # 24 hours

        return {"status": "ok"}

    def get(self, path: str = "") -> Dict[str, Any]:
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
        elif path == ".well-known/oauth-authorization-server":
            return self._handle_authorization_server_discovery()
        else:
            return self.error_response(404, f"Unknown OAuth2 endpoint: {path}")

    def _handle_client_registration(self) -> Dict[str, Any]:
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
            body: Union[str, bytes, None] = self.request.body
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
                client_response = self.oauth2_server.handle_client_registration(registration_data)
                logger.info(f"Registered MCP client: {client_response['client_id']}")
                return client_response

            except ValueError as e:
                return self.error_response(400, str(e))
            except Exception as e:
                logger.error(f"Client registration failed: {e}")
                return self.error_response(500, "Client registration failed")

        except Exception as e:
            logger.error(f"Error in client registration: {e}")
            return self.error_response(500, "Internal server error")

    def _handle_authorization_request(self, method: str = "GET") -> Dict[str, Any]:
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
                body: Union[str, bytes, None] = self.request.body
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
                }

            # Debug logging for MCP OAuth2 flow
            logger.info(f"OAuth2 authorization {method} request with params: {dict(params)}")

            # Handle using OAuth2 server
            server_response = self.oauth2_server.handle_authorization_request(params, method)

            logger.info(f"OAuth2 server response: {server_response}")

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

    def _handle_token_request(self) -> Dict[str, Any]:
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
            body: Union[str, bytes, None] = self.request.body
            if body is None:
                body_str = ""
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = str(body)

            # Parse form data
            from urllib.parse import parse_qs

            form_data = parse_qs(body_str)

            # Extract parameters (parse_qs returns lists)
            params = {
                "grant_type": form_data.get("grant_type", [""])[0],
                "code": form_data.get("code", [""])[0],
                "refresh_token": form_data.get("refresh_token", [""])[0],
                "redirect_uri": form_data.get("redirect_uri", [""])[0],
                "client_id": form_data.get("client_id", [""])[0],
                "client_secret": form_data.get("client_secret", [""])[0],
            }

            # Handle using OAuth2 server
            token_response = self.oauth2_server.handle_token_request(params)

            if "error" in token_response:
                error = token_response.get("error", "server_error")
                description = token_response.get("error_description", "Unknown error")

                # Map to appropriate HTTP status codes
                if error in ["invalid_client"]:
                    status = 401
                elif error in ["invalid_request", "invalid_grant", "unsupported_grant_type"]:
                    status = 400
                else:
                    status = 500

                return self.error_response(status, f"{error}: {description}")

            logger.info(f"Token request successful for client {params.get('client_id', 'unknown')}")
            return token_response

        except Exception as e:
            logger.error(f"Error in token request: {e}")
            return self.error_response(500, "Internal server error")

    def _handle_authorization_server_discovery(self) -> Dict[str, Any]:
        """
        Handle OAuth2 Authorization Server Discovery (RFC 8414).

        Returns:
            ActingWeb OAuth2 authorization server metadata
        """
        return self.oauth2_server.handle_discovery_request()

    def _handle_oauth_callback(self) -> Dict[str, Any]:
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
                    return self.error_response(500, "Failed to create callback redirect URL")
            else:
                # Error response
                error = callback_response.get("error", "server_error")
                description = callback_response.get("error_description", "OAuth2 callback failed")
                return self.error_response(400, f"{error}: {description}")

        except Exception as e:
            logger.error(f"Error in OAuth2 callback: {e}")
            return self.error_response(500, "Internal server error")

    def _render_authorization_form(self, form_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Render authorization form (same UX as GET /).

        Args:
            form_data: Form data from OAuth2 server

        Returns:
            Form response or None if template values were set
        """
        # For OAuth2 authorization forms, always try to render HTML template if UI is enabled
        # The form is meant for human interaction, so default to HTML unless explicitly requesting JSON
        is_browser_request = (
            self.config.ui
            and self.request
            and self.request.headers
            and self.request.headers.get("Accept", "").find("application/json") == -1
        )

        if is_browser_request:
            # Set template values for HTML rendering (like factory handler does)
            self.response.template_values = {
                "client_id": form_data.get("client_id", ""),
                "redirect_uri": form_data.get("redirect_uri", ""),
                "state": form_data.get("state", ""),
                "client_name": form_data.get("client_name", "MCP Client"),
                "form_action": "/oauth/authorize",
                "form_method": "POST",
                "message": f"Authorize {form_data.get('client_name', 'MCP Client')} to access your ActingWeb data",
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

    def error_response(self, status_code: int, message: str) -> Dict[str, Any]:
        """Create OAuth2 error response."""
        self.response.set_status(status_code)

        # OAuth2 error format
        if status_code == 400:
            return {"error": "invalid_request", "error_description": message}
        elif status_code == 401:
            return {"error": "invalid_client", "error_description": message}
        else:
            return {"error": "server_error", "error_description": message}
