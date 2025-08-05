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
from ..mcp.sdk_server import get_server_manager
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

        For initial discovery, this returns basic information about the MCP server.
        Authentication will be handled during the MCP protocol negotiation.
        """
        try:
            # For initial discovery, don't require authentication
            # Return basic server information that MCP clients can use
            return {
                "version": "2024-11-05",
                "server_name": "actingweb-mcp",
                "capabilities": {
                    "tools": True,  # We support tools
                    "resources": True,  # We support resources
                    "prompts": True,  # We support prompts
                },
                "transport": {"type": "http", "endpoint": "/mcp", "supported_versions": ["2024-11-05"]},
                "authentication": {
                    "required": True,
                    "type": "oauth2",
                    "discovery_url": f"{self.config.proto}{self.config.fqdn}/.well-known/oauth-protected-resource",
                },
            }

        except Exception as e:
            logger.error(f"Error handling MCP GET request: {e}")
            return self.error_response(500, f"Internal server error: {str(e)}")

    def post(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle POST requests to /mcp endpoint.

        Handles MCP JSON-RPC protocol. The initialize method doesn't require authentication,
        but all other methods do.
        """
        try:
            method = data.get("method")
            params = data.get("params", {})
            request_id = data.get("id")

            # Handle initialize method without authentication (part of MCP handshake)
            if method == "initialize":
                return self._handle_initialize(request_id, params)
            elif method == "notifications/initialized":
                return self._handle_notifications_initialized(request_id, params)

            # All other methods require authentication
            actor = self.authenticate_and_get_actor()
            if not actor:
                return self._create_jsonrpc_error(request_id, -32002, "Authentication required for this method")

            # Get MCP server for this actor
            mcp_server = self.server_manager.get_server(actor.id, self.hooks, actor)  # type: ignore

            if method == "tools/list":
                return self._handle_tools_list(request_id, actor.id)
            elif method == "resources/list":
                return self._handle_resources_list(request_id, actor.id)
            elif method == "prompts/list":
                return self._handle_prompts_list(request_id, actor.id)
            elif method == "tools/call":
                return self._handle_tool_call(request_id, params, actor)
            elif method == "prompts/get":
                return self._handle_prompt_get(request_id, params, actor)
            elif method == "resources/read":
                return self._handle_resource_read(request_id, params, actor)
            else:
                return self._create_jsonrpc_error(request_id, -32601, f"Method not found: {method}")

        except Exception as e:
            logger.error(f"Error handling MCP POST request: {e}")
            return self._create_jsonrpc_error(data.get("id"), -32603, f"Internal error: {str(e)}")

    def _has_mcp_tools(self) -> bool:
        """Check if server has any MCP-exposed tools."""
        if not self.hooks:
            return False

        # Check if any action hooks are MCP-exposed
        from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata

        for action_name, hooks in self.hooks._action_hooks.items():
            for hook in hooks:
                if is_mcp_exposed(hook):
                    metadata = get_mcp_metadata(hook)
                    if metadata and metadata.get("type") == "tool":
                        return True
        return False

    def _has_mcp_resources(self) -> bool:
        """Check if server has any MCP-exposed resources."""
        # For now, we'll return True since we implement some basic resources
        # In a full implementation, this would check decorated resource functions
        return True

    def _has_mcp_prompts(self) -> bool:
        """Check if server has any MCP-exposed prompts."""
        if not self.hooks:
            return False

        # Check if any method hooks are MCP-exposed
        from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata

        for method_name, hooks in self.hooks._method_hooks.items():
            for hook in hooks:
                if is_mcp_exposed(hook):
                    metadata = get_mcp_metadata(hook)
                    if metadata and metadata.get("type") == "prompt":
                        return True
        return False

    def _handle_initialize(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        # Build capabilities based on what's actually available
        capabilities: Dict[str, Any] = {}

        # Tools capability
        if self._has_mcp_tools():
            capabilities["tools"] = {"listChanged": True}  # Indicates tools can be dynamically discovered

        # Resources capability
        if self._has_mcp_resources():
            capabilities["resources"] = {
                "subscribe": False,  # We don't support resource subscriptions yet
                "listChanged": True,  # Resources can be dynamically discovered
            }

        # Prompts capability
        if self._has_mcp_prompts():
            capabilities["prompts"] = {"listChanged": True}  # Prompts can be dynamically discovered

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": capabilities,
                "serverInfo": {"name": "ActingWeb MCP Server", "version": "1.0.0"},
            },
        }

    def _handle_tools_list(self, request_id: Any, actor_id: str) -> Dict[str, Any]:
        """Handle MCP tools/list request."""
        tools = []

        if self.hooks:
            from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata

            # Discover MCP tools from action hooks
            for action_name, hooks in self.hooks._action_hooks.items():
                for hook in hooks:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "tool":
                            tool_def = {
                                "name": metadata.get("name") or action_name,
                                "description": metadata.get("description") or f"Execute {action_name} action",
                            }

                            # Add input schema if provided
                            input_schema = metadata.get("input_schema")
                            if input_schema:
                                tool_def["inputSchema"] = input_schema

                            tools.append(tool_def)

        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}

    def _handle_resources_list(self, request_id: Any, actor_id: str) -> Dict[str, Any]:
        """Handle MCP resources/list request."""
        # Define static resources that are useful for ChatGPT integration
        resources = [
            {
                "uri": "actingweb://notes/all",
                "name": "All Notes",
                "description": "Access all stored notes for the current user",
                "mimeType": "application/json",
            },
            {
                "uri": "actingweb://reminders/pending",
                "name": "Pending Reminders",
                "description": "List of all pending/incomplete reminders",
                "mimeType": "application/json",
            },
            {
                "uri": "actingweb://usage/stats",
                "name": "Usage Statistics",
                "description": "Statistics about MCP tool usage and activity",
                "mimeType": "application/json",
            },
        ]

        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": resources}}

    def _handle_prompts_list(self, request_id: Any, actor_id: str) -> Dict[str, Any]:
        """Handle MCP prompts/list request."""
        prompts = []

        if self.hooks:
            from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata

            # Discover MCP prompts from method hooks
            for method_name, hooks in self.hooks._method_hooks.items():
                for hook in hooks:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "prompt":
                            prompt_def = {
                                "name": metadata.get("name") or method_name,
                                "description": metadata.get("description") or f"Generate prompt for {method_name}",
                            }

                            # Add arguments if provided
                            arguments = metadata.get("arguments")
                            if arguments:
                                prompt_def["arguments"] = arguments

                            prompts.append(prompt_def)

        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": prompts}}

    def _handle_tool_call(self, request_id: Any, params: Dict[str, Any], actor: Any) -> Dict[str, Any]:
        """Handle MCP tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            return self._create_jsonrpc_error(request_id, -32602, "Missing tool name")

        if not self.hooks:
            return self._create_jsonrpc_error(request_id, -32603, "No hooks registry available")

        # Find the corresponding action hook
        from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata

        for action_name, hooks in self.hooks._action_hooks.items():
            for hook in hooks:
                if is_mcp_exposed(hook):
                    metadata = get_mcp_metadata(hook)
                    if metadata and metadata.get("type") == "tool":
                        mcp_tool_name = metadata.get("name") or action_name
                        if mcp_tool_name == tool_name:
                            try:
                                # Execute the action hook
                                result = hook(actor, action_name, arguments)

                                # Ensure result is JSON serializable
                                if not isinstance(result, dict):
                                    result = {"result": result}

                                return {
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "result": {"content": [{"type": "text", "text": str(result)}]},
                                }
                            except Exception as e:
                                logger.error(f"Error executing tool {tool_name}: {e}")
                                return self._create_jsonrpc_error(
                                    request_id, -32603, f"Tool execution failed: {str(e)}"
                                )

        return self._create_jsonrpc_error(request_id, -32601, f"Tool not found: {tool_name}")

    def _handle_prompt_get(self, request_id: Any, params: Dict[str, Any], actor: Any) -> Dict[str, Any]:
        """Handle MCP prompts/get request."""
        prompt_name = params.get("name")
        arguments = params.get("arguments", {})

        if not prompt_name:
            return self._create_jsonrpc_error(request_id, -32602, "Missing prompt name")

        if not self.hooks:
            return self._create_jsonrpc_error(request_id, -32603, "No hooks registry available")

        # Find the corresponding method hook
        from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata

        for method_name, hooks in self.hooks._method_hooks.items():
            for hook in hooks:
                if is_mcp_exposed(hook):
                    metadata = get_mcp_metadata(hook)
                    if metadata and metadata.get("type") == "prompt":
                        mcp_prompt_name = metadata.get("name") or method_name
                        if mcp_prompt_name == prompt_name:
                            try:
                                # Execute the method hook
                                result = hook(actor, method_name, arguments)

                                # Convert result to string for prompt
                                if isinstance(result, dict):
                                    if "prompt" in result:
                                        prompt_text = str(result["prompt"])
                                    else:
                                        prompt_text = str(result)
                                else:
                                    prompt_text = str(result)

                                return {
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "result": {
                                        "description": metadata.get(
                                            "description", f"Generated prompt for {method_name}"
                                        ),
                                        "messages": [
                                            {"role": "user", "content": {"type": "text", "text": prompt_text}}
                                        ],
                                    },
                                }
                            except Exception as e:
                                logger.error(f"Error generating prompt {prompt_name}: {e}")
                                return self._create_jsonrpc_error(
                                    request_id, -32603, f"Prompt generation failed: {str(e)}"
                                )

        return self._create_jsonrpc_error(request_id, -32601, f"Prompt not found: {prompt_name}")

    def _handle_resource_read(self, request_id: Any, params: Dict[str, Any], actor: Any) -> Dict[str, Any]:
        """Handle MCP resources/read request."""
        uri = params.get("uri")

        if not uri:
            return self._create_jsonrpc_error(request_id, -32602, "Missing resource URI")

        try:
            # Handle different resource types
            if uri == "actingweb://notes/all":
                notes = actor.properties.get("notes", [])
                content = {"total_notes": len(notes), "notes": notes}
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": str(content)}]},
                }

            elif uri == "actingweb://reminders/pending":
                reminders = actor.properties.get("reminders", [])
                pending_reminders = [r for r in reminders if not r.get("completed", False)]
                content = {"total_pending": len(pending_reminders), "reminders": pending_reminders}
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": str(content)}]},
                }

            elif uri == "actingweb://usage/stats":
                notes = actor.properties.get("notes", [])
                reminders = actor.properties.get("reminders", [])
                mcp_usage = actor.properties.get("mcp_usage_count", 0)

                # Calculate tag usage
                tag_counts: Dict[str, int] = {}
                for note in notes:
                    for tag in note.get("tags", []):
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

                content = {
                    "mcp_usage_count": mcp_usage,
                    "total_notes": len(notes),
                    "total_reminders": len(reminders),
                    "pending_reminders": len([r for r in reminders if not r.get("completed", False)]),
                    "most_used_tags": dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]),
                    "created_at": actor.properties.get("created_at", "unknown"),
                }
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": str(content)}]},
                }

            else:
                return self._create_jsonrpc_error(request_id, -32601, f"Resource not found: {uri}")

        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}")
            return self._create_jsonrpc_error(request_id, -32603, f"Resource read failed: {str(e)}")

    def _handle_notifications_initialized(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP notifications/initialized request."""
        # This is a notification that the client has finished initialization
        # According to MCP spec, this is a notification (no response expected)
        # However, some clients may send it as a request, so we respond
        logger.info("MCP client initialization completed")

        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    def _create_jsonrpc_error(self, request_id: Any, code: int, message: str) -> Dict[str, Any]:
        """Create a JSON-RPC error response."""
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def authenticate_and_get_actor(self) -> Any:
        """
        Authenticate request and get actor from ActingWeb Bearer token.

        This method validates ActingWeb tokens issued by our OAuth2 server:
        1. Extracts Bearer token from Authorization header
        2. Validates token using ActingWeb OAuth2 server
        3. Returns the associated actor instance
        """
        auth_header = self.get_auth_header()

        if not auth_header or not auth_header.startswith("Bearer "):
            logger.debug("No Bearer token found in Authorization header")
            return None

        bearer_token = auth_header[7:]  # Remove "Bearer " prefix

        try:
            from ..oauth2_server.oauth2_server import get_actingweb_oauth2_server

            oauth2_server = get_actingweb_oauth2_server(self.config)

            # Validate ActingWeb token (not Google token)
            token_validation = oauth2_server.validate_mcp_token(bearer_token)
            if not token_validation:
                logger.debug("ActingWeb token validation failed")
                return None

            actor_id, client_id, token_data = token_validation

            # Get actor instance
            from .. import actor as actor_module
            actor_instance = actor_module.Actor(actor_id, self.config)

            logger.info(f"Successfully authenticated MCP client {client_id} -> actor {actor_id}")
            return actor_instance

        except Exception as e:
            logger.error(f"Error during ActingWeb token authentication: {e}")
            return None

    def get_auth_header(self) -> Optional[str]:
        """Get Authorization header from request."""
        if hasattr(self, "request") and self.request and hasattr(self.request, "headers") and self.request.headers:
            auth_header = self.request.headers.get("Authorization") or self.request.headers.get("authorization")
            return str(auth_header) if auth_header is not None else None
        return None

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
        if status_code == 401:
            # Add WWW-Authenticate header for ActingWeb OAuth2 server
            try:
                base_url = f"{self.config.proto}{self.config.fqdn}"
                www_auth = f'Bearer realm="ActingWeb MCP", authorization_uri="{base_url}/oauth/authorize"'
                if hasattr(self, "response") and self.response:
                    self.response.headers["WWW-Authenticate"] = www_auth
            except Exception as e:
                logger.error(f"Error adding WWW-Authenticate header: {e}")
                if hasattr(self, "response") and self.response:
                    self.response.headers["WWW-Authenticate"] = 'Bearer realm="ActingWeb MCP"'

        return {"error": True, "status_code": status_code, "message": message}
