"""
MCP handler for ActingWeb.

This handler provides the /mcp endpoint that serves MCP functionality for ActingWeb actors,
enabling AI language models to interact with actor functionality through the
Model Context Protocol.

The /mcp endpoint is exposed at the root level (like /bot) and uses authentication
to determine the actor context. MCP is a server-wide feature - either the entire
ActingWeb server supports MCP (and thus all actors can be accessed via MCP), or
MCP is not available at all.
"""

from typing import Optional, Dict, Any
import logging

from .base_handler import BaseHandler
from ..mcp.server import get_server_manager
from .. import aw_web_request
from .. import config as config_class
from ..interface.hooks import HookRegistry


logger = logging.getLogger(__name__)


class MCPHandler(BaseHandler):
    """
    Handler for the /mcp endpoint.

    This handler:
    1. Authenticates the request to determine the actor
    2. Loads the appropriate actor instance based on auth context
    3. Creates or retrieves the MCP server for that actor
    4. Delegates the request to the FastMCP server
    """

    def __init__(
        self,
        webobj: aw_web_request.AWWebObj = aw_web_request.AWWebObj(),
        config: config_class.Config = config_class.Config(),
        hooks: Optional[HookRegistry] = None,
    ) -> None:
        super().__init__(webobj, config, hooks)
        self.server_manager = get_server_manager()

    def get(self) -> Dict[str, Any]:
        """
        Handle GET requests to /mcp endpoint.

        For Phase 1, this returns basic information about the MCP server.
        In later phases, this will handle WebSocket upgrades.
        """
        try:
            # Authenticate and get actor from auth context
            actor = self.authenticate_and_get_actor()
            if not actor:
                return self.error_response(401, "Authentication required")

            # Get or create MCP server for this actor
            mcp_server = self.server_manager.get_server(actor.id, self.hooks, actor)  # type: ignore

            # Return basic server information
            return {
                "version": "1.0.0",
                "actor_id": actor.id,
                "capabilities": {
                    "tools": self._has_mcp_tools(),
                    "resources": self._has_mcp_resources(),
                    "prompts": self._has_mcp_prompts(),
                },
                "transport": {"type": "websocket", "endpoint": "/mcp"},
            }

        except Exception as e:
            logger.error(f"Error handling MCP GET request: {e}")
            return self.error_response(500, f"Internal server error: {str(e)}")

    def post(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle POST requests to /mcp endpoint.

        For Phase 1, this provides a simple JSON-RPC interface.
        In later phases, WebSocket will be the primary transport.
        """
        try:
            # Authenticate and get actor from auth context
            actor = self.authenticate_and_get_actor()
            if not actor:
                return self.error_response(401, "Authentication required")

            # Get MCP server for this actor
            mcp_server = self.server_manager.get_server(actor.id, self.hooks, actor)  # type: ignore

            # For Phase 1, we'll implement basic JSON-RPC handling
            # This is a simplified implementation - full MCP protocol handling
            # will be implemented in Phase 2

            method = data.get("method")
            params = data.get("params", {})
            request_id = data.get("id")

            if method == "initialize":
                return self._handle_initialize(request_id, params)
            elif method == "tools/list":
                return self._handle_tools_list(request_id, actor.id)
            elif method == "resources/list":
                return self._handle_resources_list(request_id, actor.id)
            elif method == "prompts/list":
                return self._handle_prompts_list(request_id, actor.id)
            else:
                return self._create_jsonrpc_error(request_id, -32601, f"Method not found: {method}")

        except Exception as e:
            logger.error(f"Error handling MCP POST request: {e}")
            return self._create_jsonrpc_error(data.get("id"), -32603, f"Internal error: {str(e)}")

    def _has_mcp_tools(self) -> bool:
        """Check if server has any MCP-exposed tools."""
        # For Phase 1, simplified check
        # In Phase 2, this will check the hook registry for MCP-decorated action hooks
        return True

    def _has_mcp_resources(self) -> bool:
        """Check if server has any MCP-exposed resources."""
        # For Phase 1, simplified check
        # In Phase 2, this will check the hook registry for MCP-decorated resource hooks
        return True

    def _has_mcp_prompts(self) -> bool:
        """Check if server has any MCP-exposed prompts."""
        # For Phase 1, simplified check
        # In Phase 2, this will check the hook registry for MCP-decorated method hooks
        return True

    def _handle_initialize(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "ActingWeb MCP Server", "version": "1.0.0"},
            },
        }

    def _handle_tools_list(self, request_id: Any, actor_id: str) -> Dict[str, Any]:
        """Handle MCP tools/list request."""
        # For Phase 1, return empty list
        # Phase 2 will implement proper tool discovery from hook registry
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": []}}

    def _handle_resources_list(self, request_id: Any, actor_id: str) -> Dict[str, Any]:
        """Handle MCP resources/list request."""
        # For Phase 1, return empty list
        # Phase 2 will implement proper resource discovery from hook registry
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}

    def _handle_prompts_list(self, request_id: Any, actor_id: str) -> Dict[str, Any]:
        """Handle MCP prompts/list request."""
        # For Phase 1, return empty list
        # Phase 2 will implement proper prompt discovery from hook registry
        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}

    def _create_jsonrpc_error(self, request_id: Any, code: int, message: str) -> Dict[str, Any]:
        """Create a JSON-RPC error response."""
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def authenticate_and_get_actor(self) -> Any:
        """
        Authenticate request and get actor from OAuth2 Bearer token.

        This method implements OAuth2 authentication flow:
        1. Extracts Bearer token from Authorization header
        2. If no token, initiates OAuth2 redirect to Google
        3. Validates token with Google API
        4. Retrieves email from Google user info API
        5. Looks up actor by email address
        6. Returns the actor instance or None if not found/authenticated
        """
        # For Phase 1, we'll create a mock implementation
        # In Phase 3, this will implement full OAuth2 flow

        # Real implementation will:
        # 1. Check for Authorization: Bearer <token> header
        # 2. If missing, return OAuth2 redirect response to Google
        # 3. Validate Bearer token with Google OAuth2 API
        # 4. Call Google UserInfo API to get email from token
        # 5. Look up ActingWeb actor by email
        # 6. Return actor instance

        # Mock OAuth2 flow - Phase 1 placeholder
        auth_header = self.get_auth_header()  # Will be implemented

        if not auth_header or not auth_header.startswith("Bearer "):
            # In real implementation, return OAuth2 redirect
            return None

        # Mock token validation and email retrieval
        # Real implementation will call Google APIs
        bearer_token = auth_header[7:]  # Remove "Bearer " prefix

        class MockActor:
            def __init__(self) -> None:
                self.id = "oauth_actor_123"
                self.email = "user@gmail.com"  # From Google UserInfo API
                self.properties: Dict[str, Any] = {}
                self.oauth_provider = "google"
                self.oauth_token = bearer_token

        return MockActor()

    def get_auth_header(self) -> str:
        """Get Authorization header from request (placeholder for Phase 1)."""
        # This will be implemented in Phase 3 to extract from actual request
        return "Bearer mock_google_oauth_token_123"

    def initiate_oauth2_redirect(self) -> Dict[str, Any]:
        """
        Initiate OAuth2 redirect to Google (placeholder for Phase 3).

        Returns OAuth2 authorization URL for Google that the client should redirect to.
        After user consent, Google will redirect back with authorization code.
        """
        # This will be implemented in Phase 3
        google_oauth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        client_id = "your-google-client-id"  # From config
        redirect_uri = "https://your-domain.com/mcp/oauth/callback"
        scope = "openid email profile"

        auth_url = (
            f"{google_oauth_url}?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"scope={scope}&"
            f"response_type=code&"
            f"access_type=offline"
        )

        return {
            "error": "authentication_required",
            "auth_url": auth_url,
            "message": "Please authenticate with Google to access MCP",
        }

    def validate_google_token(self, bearer_token: str) -> Optional[str]:
        """
        Validate Google OAuth2 token and return email (placeholder for Phase 3).

        Args:
            bearer_token: OAuth2 access token from Google

        Returns:
            Email address from Google UserInfo API or None if invalid
        """
        # This will be implemented in Phase 3 to:
        # 1. Call Google TokenInfo API to validate token
        # 2. Call Google UserInfo API to get user email
        # 3. Return email address

        # Mock implementation
        if bearer_token.startswith("mock_google_oauth_token"):
            return "user@gmail.com"
        return None

    def error_response(self, status_code: int, message: str) -> Dict[str, Any]:
        """Create an error response."""
        return {"error": True, "status_code": status_code, "message": message}
