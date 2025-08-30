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
import json
import re
import time

from .base_handler import BaseHandler
from ..mcp.sdk_server import get_server_manager
from .. import aw_web_request
from .. import config as config_class
from ..interface.hooks import HookRegistry
from ..interface.actor_interface import ActorInterface


logger = logging.getLogger(__name__)

# Global caches for MCP performance optimization
_token_cache: Dict[str, Dict[str, Any]] = {}  # token -> validation data
_actor_cache: Dict[str, Dict[str, Any]] = {}  # actor_id -> {actor, trust_context, last_accessed}
_trust_cache: Dict[str, Any] = {}  # actor_id -> trust_relationship
_cache_ttl = 300  # 5 minutes cache TTL

# Cache statistics for performance monitoring
_cache_stats = {
    "token_hits": 0,
    "token_misses": 0,
    "actor_hits": 0,
    "actor_misses": 0,
    "trust_hits": 0,
    "trust_misses": 0,
}


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

    def _cleanup_expired_cache_entries(self) -> None:
        """Remove expired entries from all caches."""
        current_time = time.time()

        # Clean token cache
        expired_tokens = [
            token for token, data in _token_cache.items() if current_time - data.get("cached_at", 0) > _cache_ttl
        ]
        for token in expired_tokens:
            del _token_cache[token]

        # Clean actor cache
        expired_actors = [
            actor_id
            for actor_id, data in _actor_cache.items()
            if current_time - data.get("last_accessed", 0) > _cache_ttl
        ]
        for actor_id in expired_actors:
            del _actor_cache[actor_id]
            if actor_id in _trust_cache:
                del _trust_cache[actor_id]

        if expired_tokens or expired_actors:
            logger.debug(
                f"Cleaned up {len(expired_tokens)} expired tokens and {len(expired_actors)} expired actors from MCP cache"
            )

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

            # Handle methods that don't require authentication
            if method == "initialize":
                return self._handle_initialize(request_id, params)
            elif method == "notifications/initialized":
                return self._handle_notifications_initialized(request_id, params)
            elif method == "ping":
                return self._handle_ping(request_id, params)

            # All other methods require authentication
            actor = self.authenticate_and_get_actor_cached()
            if not actor:
                return self._create_jsonrpc_error(request_id, -32002, "Authentication required for this method")

            # Get MCP server for this actor
            mcp_server = self.server_manager.get_server(actor.id, self.hooks, actor)  # type: ignore

            if method == "tools/list":
                return self._handle_tools_list(request_id, actor)
            elif method == "resources/list":
                return self._handle_resources_list(request_id, actor)
            elif method == "prompts/list":
                return self._handle_prompts_list(request_id, actor)
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
        if not self.hooks:
            return False

        # Check if any method hooks are MCP-exposed as resources
        from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata

        for method_name, hooks in self.hooks._method_hooks.items():
            for hook in hooks:
                if is_mcp_exposed(hook):
                    metadata = get_mcp_metadata(hook)
                    if metadata and metadata.get("type") == "resource":
                        return True
        return False

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

    def _handle_tools_list(self, request_id: Any, actor: Any) -> Dict[str, Any]:
        """Handle MCP tools/list request with permission filtering."""
        tools = []

        if self.hooks:
            from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata
            from ..permission_evaluator import (
                get_permission_evaluator,
                PermissionType,
                PermissionResult,
            )

            # Resolve peer_id from MCP trust context (set during auth)
            trust_context = getattr(actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None

            # Get evaluator if the permission system is initialized
            evaluator = None
            try:
                evaluator = get_permission_evaluator(self.config) if peer_id else None
            except Exception as e:
                logger.debug(f"Permission evaluator unavailable during tools/list: {e}")
                evaluator = None

            # Discover MCP tools from action hooks
            for action_name, hooks in self.hooks._action_hooks.items():
                for hook in hooks:
                    if not is_mcp_exposed(hook):
                        continue
                    metadata = get_mcp_metadata(hook)
                    if not (metadata and metadata.get("type") == "tool"):
                        continue

                    tool_name = metadata.get("name") or action_name

                    # Filter by permissions when we have context
                    if peer_id and evaluator:
                        try:
                            decision = evaluator.evaluate_permission(
                                actor.id,
                                peer_id,
                                PermissionType.TOOLS,
                                tool_name,
                                operation="use",
                            )
                            if decision != PermissionResult.ALLOWED:
                                logger.debug(
                                    f"Tool '{tool_name}' filtered out for peer {peer_id} (actor {actor.id})"
                                )
                                continue
                        except Exception as e:
                            logger.warning(f"Error evaluating tool permission for '{tool_name}': {e}")
                            # Fail-open on evaluation errors to avoid hard lockouts

                    tool_def = {
                        "name": tool_name,
                        "description": metadata.get("description")
                        or f"Execute {action_name} action",
                    }

                    # Add input schema if provided (decorator uses 'input_schema')
                    input_schema = metadata.get("input_schema")
                    if input_schema:
                        tool_def["inputSchema"] = input_schema

                    tools.append(tool_def)

        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}

    def _handle_resources_list(self, request_id: Any, actor: Any) -> Dict[str, Any]:
        """Handle MCP resources/list request with permission filtering."""
        resources = []

        if self.hooks:
            from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata
            from ..permission_evaluator import (
                get_permission_evaluator,
                PermissionType,
                PermissionResult,
            )

            trust_context = getattr(actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None

            evaluator = None
            try:
                evaluator = get_permission_evaluator(self.config) if peer_id else None
            except Exception as e:
                logger.debug(f"Permission evaluator unavailable during resources/list: {e}")
                evaluator = None

            # Discover MCP resources from method hooks
            for method_name, hooks in self.hooks._method_hooks.items():
                for hook in hooks:
                    if not is_mcp_exposed(hook):
                        continue
                    metadata = get_mcp_metadata(hook)
                    if not (metadata and metadata.get("type") == "resource"):
                        continue

                    # Decorator stores 'uri_template'; fall back to actingweb://{method_name}
                    uri_template = metadata.get("uri_template") or f"actingweb://{method_name}"

                    # Filter by permissions when available
                    if peer_id and evaluator:
                        try:
                            decision = evaluator.evaluate_permission(
                                actor.id,
                                peer_id,
                                PermissionType.RESOURCES,
                                uri_template,
                                operation="read",
                            )
                            if decision != PermissionResult.ALLOWED:
                                logger.debug(
                                    f"Resource '{uri_template}' filtered out for peer {peer_id} (actor {actor.id})"
                                )
                                continue
                        except Exception as e:
                            logger.warning(
                                f"Error evaluating resource permission for '{uri_template}': {e}"
                            )

                    resource_def = {
                        "uri": uri_template,
                        "name": metadata.get("name") or method_name.replace("_", " ").title(),
                        "description": metadata.get("description")
                        or f"Access {method_name} resource",
                        # Output key follows MCP spec; decorator uses 'mime_type'
                        "mimeType": metadata.get("mime_type", "application/json"),
                    }
                    resources.append(resource_def)

        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": resources}}

    def _handle_prompts_list(self, request_id: Any, actor: Any) -> Dict[str, Any]:
        """Handle MCP prompts/list request with permission filtering."""
        prompts = []

        if self.hooks:
            from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata
            from ..permission_evaluator import (
                get_permission_evaluator,
                PermissionType,
                PermissionResult,
            )

            trust_context = getattr(actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None

            evaluator = None
            try:
                evaluator = get_permission_evaluator(self.config) if peer_id else None
            except Exception as e:
                logger.debug(f"Permission evaluator unavailable during prompts/list: {e}")
                evaluator = None

            # Discover MCP prompts from method hooks
            for method_name, hooks in self.hooks._method_hooks.items():
                for hook in hooks:
                    if not is_mcp_exposed(hook):
                        continue
                    metadata = get_mcp_metadata(hook)
                    if not (metadata and metadata.get("type") == "prompt"):
                        continue

                    prompt_name = metadata.get("name") or method_name

                    # Filter by permissions when available
                    if peer_id and evaluator:
                        try:
                            decision = evaluator.evaluate_permission(
                                actor.id,
                                peer_id,
                                PermissionType.PROMPTS,
                                prompt_name,
                                operation="invoke",
                            )
                            if decision != PermissionResult.ALLOWED:
                                logger.debug(
                                    f"Prompt '{prompt_name}' filtered out for peer {peer_id} (actor {actor.id})"
                                )
                                continue
                        except Exception as e:
                            logger.warning(
                                f"Error evaluating prompt permission for '{prompt_name}': {e}"
                            )

                    prompt_def = {
                        "name": prompt_name,
                        "description": metadata.get("description")
                        or f"Generate prompt for {method_name}",
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

        # Check permission before finding/dispatching the hook
        try:
            from ..permission_evaluator import get_permission_evaluator, PermissionType, PermissionResult
            trust_context = getattr(actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None
            if peer_id:
                evaluator = get_permission_evaluator(self.config)
                decision = evaluator.evaluate_permission(
                    actor.id, peer_id, PermissionType.TOOLS, tool_name, operation="use"
                )
                if decision != PermissionResult.ALLOWED:
                    return self._create_jsonrpc_error(
                        request_id,
                        -32003,
                        f"Access denied: You don't have permission to use tool '{tool_name}'",
                    )
        except Exception as e:
            # Don't block execution if permission system not initialized; log and continue
            logger.debug(f"Skipping tool permission check due to error: {e}")

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
                                # Actor is already an ActorInterface from authenticate_and_get_actor_cached()
                                # No need to wrap it again

                                # Execute the action hook
                                result = hook(actor, action_name, arguments)

                                # Check if result is already properly structured MCP content
                                if isinstance(result, dict) and "content" in result:
                                    # Result is already MCP-formatted, use it directly
                                    return {
                                        "jsonrpc": "2.0",
                                        "id": request_id,
                                        "result": result,
                                    }
                                else:
                                    # Legacy handling: wrap in text item
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

        # Check permission before finding/dispatching the hook
        try:
            from ..permission_evaluator import get_permission_evaluator, PermissionType, PermissionResult
            trust_context = getattr(actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None
            if peer_id:
                evaluator = get_permission_evaluator(self.config)
                decision = evaluator.evaluate_permission(
                    actor.id, peer_id, PermissionType.PROMPTS, prompt_name, operation="invoke"
                )
                if decision != PermissionResult.ALLOWED:
                    return self._create_jsonrpc_error(
                        request_id,
                        -32003,
                        f"Access denied: You don't have permission to use prompt '{prompt_name}'",
                    )
        except Exception as e:
            logger.debug(f"Skipping prompt permission check due to error: {e}")

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
                                # Actor is already an ActorInterface from authenticate_and_get_actor_cached()
                                # No need to wrap it again

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

        if not self.hooks:
            return self._create_jsonrpc_error(request_id, -32603, "No hooks registry available")

        try:
            # Check permission before accessing resource
            try:
                from ..permission_evaluator import get_permission_evaluator, PermissionType, PermissionResult
                trust_context = getattr(actor, "_mcp_trust_context", None)
                peer_id = trust_context.get("peer_id") if trust_context else None
                if peer_id and uri:
                    evaluator = get_permission_evaluator(self.config)
                    decision = evaluator.evaluate_permission(
                        actor.id, peer_id, PermissionType.RESOURCES, uri, operation="read"
                    )
                    if decision != PermissionResult.ALLOWED:
                        return self._create_jsonrpc_error(
                            request_id,
                            -32003,
                            f"Access denied: You don't have permission to access resource '{uri}'",
                        )
            except Exception as e:
                logger.debug(f"Skipping resource permission check due to error: {e}")

            # Find the corresponding resource hook
            from ..mcp.decorators import is_mcp_exposed, get_mcp_metadata
            # Reuse URI template matching from SDK server implementation
            from ..mcp.sdk_server import _match_uri_template

            for method_name, hooks in self.hooks._method_hooks.items():
                for hook in hooks:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "resource":
                            # Prefer 'uri_template' from decorator; fall back to legacy
                            resource_uri = metadata.get("uri_template") or metadata.get("uri") or f"actingweb://{method_name}"
                            uri_pattern = metadata.get("uri_pattern")

                            # Check for template/pattern match
                            uri_matches = False
                            variables: Dict[str, str] | None = None
                            try:
                                variables = _match_uri_template(str(resource_uri), str(uri))
                            except Exception:
                                variables = None
                            if variables is not None:
                                uri_matches = True
                            elif uri_pattern:
                                try:
                                    if re.match(uri_pattern, str(uri)):
                                        uri_matches = True
                                except re.error:
                                    logger.warning(f"Invalid URI pattern in resource metadata: {uri_pattern}")

                            if uri_matches:
                                try:
                                    # Actor is already an ActorInterface from authenticate_and_get_actor()
                                    # No need to wrap it again

                                    # Execute the resource hook
                                    result = hook(actor, method_name, params)

                                    # Handle different result formats
                                    if isinstance(result, dict):
                                        if "contents" in result:
                                            # Result is already MCP-formatted
                                            return {
                                                "jsonrpc": "2.0",
                                                "id": request_id,
                                                "result": result,
                                            }
                                        else:
                                            # Convert dict to JSON content
                                            content_text = json.dumps(result, indent=2)
                                    else:
                                        # Convert other types to string
                                        content_text = str(result)

                                    return {
                                        "jsonrpc": "2.0",
                                        "id": request_id,
                                        "result": {
                                            "contents": [
                                                {
                                                    "uri": uri,
                                                    # Output key follows MCP spec; decorator uses 'mime_type'
                                                    "mimeType": metadata.get("mime_type", "application/json"),
                                                    "text": content_text,
                                                }
                                            ]
                                        },
                                    }
                                except Exception as e:
                                    logger.error(f"Error executing resource {uri}: {e}")
                                    return self._create_jsonrpc_error(
                                        request_id, -32603, f"Resource execution failed: {str(e)}"
                                    )

            return self._create_jsonrpc_error(request_id, -32601, f"Resource not found: {uri}")

        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}")
            return self._create_jsonrpc_error(request_id, -32603, f"Resource read failed: {str(e)}")

    def _handle_notifications_initialized(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP notifications/initialized request."""
        # This is a notification that the client has finished initialization
        # According to MCP spec, this is a notification (no response expected)
        # However, some clients may send it as a request, so we respond
        logger.debug("MCP client initialization completed")

        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    def _handle_ping(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP ping request."""
        # Ping is used for keepalive/connectivity testing
        # Return empty result to confirm server is alive
        logger.debug("MCP ping received")

        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    def _create_jsonrpc_error(self, request_id: Any, code: int, message: str) -> Dict[str, Any]:
        """Create a JSON-RPC error response."""
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def authenticate_and_get_actor_cached(self) -> Any:
        """
        Optimized authenticate request and get actor with caching.

        This method provides authentication with intelligent caching:
        1. Token validation results are cached for 5 minutes
        2. Actor instances are cached to avoid repeated DynamoDB loads
        3. Trust relationship lookups are cached per actor
        4. Automatic cache cleanup removes expired entries

        Cache keys are based on tokens and actor IDs, providing significant performance
        improvements for repeated requests from the same clients.
        """
        # Clean up expired cache entries periodically (every ~20th request)
        if time.time() % 20 == 0:  # Simple way to occasionally clean up
            self._cleanup_expired_cache_entries()

        auth_header = self.get_auth_header()
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.debug("No Bearer token found in Authorization header")
            return None

        bearer_token = auth_header[7:]  # Remove "Bearer " prefix
        current_time = time.time()

        # Check token cache first
        if bearer_token in _token_cache:
            cached_data = _token_cache[bearer_token]
            if current_time - cached_data.get("cached_at", 0) < _cache_ttl:
                _cache_stats["token_hits"] += 1
                actor_id = cached_data["actor_id"]
                client_id = cached_data["client_id"]
                token_data = cached_data["token_data"]

                # Check actor cache
                if actor_id in _actor_cache:
                    cached_actor_data = _actor_cache[actor_id]
                    if current_time - cached_actor_data.get("last_accessed", 0) < _cache_ttl:
                        _cache_stats["actor_hits"] += 1
                        # Update last accessed time
                        cached_actor_data["last_accessed"] = current_time
                        actor_interface = cached_actor_data["actor"]

                        # Refresh trust context from cache or lookup
                        if actor_id in _trust_cache:
                            _cache_stats["trust_hits"] += 1
                            trust_relationship = _trust_cache[actor_id]
                        else:
                            _cache_stats["trust_misses"] += 1
                            trust_relationship = self._lookup_mcp_trust_relationship(
                                actor_interface, client_id, token_data
                            )
                            _trust_cache[actor_id] = trust_relationship

                        # Update trust context using setattr to avoid Pylance issues
                        setattr(actor_interface, '_mcp_trust_context', {
                            "client_id": client_id,
                            "trust_relationship": trust_relationship,
                            "token_data": token_data,
                            "peer_id": trust_relationship.peerid if trust_relationship else None,
                        })

                        # Log cache performance periodically
                        total_requests = sum(_cache_stats.values())
                        if total_requests > 0 and total_requests % 10 == 0:  # Every 10 requests
                            logger.debug(
                                f"MCP cache stats - Token hits: {_cache_stats['token_hits']}, Actor hits: {_cache_stats['actor_hits']}, Trust hits: {_cache_stats['trust_hits']}"
                            )

                        logger.debug(f"Serving cached MCP authentication for client {client_id} -> actor {actor_id}")
                        return actor_interface
                    else:
                        _cache_stats["actor_misses"] += 1
                else:
                    _cache_stats["actor_misses"] += 1
            else:
                _cache_stats["token_misses"] += 1
        else:
            _cache_stats["token_misses"] += 1

        # Cache miss - perform full authentication flow
        try:
            from ..oauth2_server.oauth2_server import get_actingweb_oauth2_server

            oauth2_server = get_actingweb_oauth2_server(self.config)

            # Validate ActingWeb token (not Google token)
            token_validation = oauth2_server.validate_mcp_token(bearer_token)
            if not token_validation:
                logger.debug("ActingWeb token validation failed")
                return None

            actor_id, client_id, token_data = token_validation

            # Cache token validation result
            _token_cache[bearer_token] = {
                "actor_id": actor_id,
                "client_id": client_id,
                "token_data": token_data,
                "cached_at": current_time,
            }

            # Get or create actor (with caching)
            actor_interface = self._get_or_create_actor_cached(actor_id, token_data, current_time)
            if not actor_interface:
                return None

            # Lookup and cache trust relationship
            trust_relationship = self._lookup_mcp_trust_relationship(actor_interface, client_id, token_data)
            _trust_cache[actor_id] = trust_relationship

            # Store trust context for permission checking using setattr to avoid Pylance issues
            setattr(actor_interface, '_mcp_trust_context', {
                "client_id": client_id,
                "trust_relationship": trust_relationship,
                "token_data": token_data,
                "peer_id": trust_relationship.peerid if trust_relationship else None,
            })

            logger.debug(f"Successfully authenticated MCP client {client_id} -> actor {actor_id} with trust context")
            return actor_interface

        except Exception as e:
            logger.error(f"Error during ActingWeb token authentication: {e}")
            return None


    def _get_or_create_actor_cached(
        self, actor_id: str, token_data: Dict[str, Any], current_time: float
    ) -> Optional[ActorInterface]:
        """Get or create actor with caching."""
        # Check actor cache first
        if actor_id in _actor_cache:
            cached_data = _actor_cache[actor_id]
            if current_time - cached_data.get("last_accessed", 0) < _cache_ttl:
                cached_data["last_accessed"] = current_time
                return cached_data["actor"]

        # Cache miss - create/load actor
        from .. import actor as actor_module

        core_actor = actor_module.Actor(actor_id, self.config)

        # CRITICAL FIX: Check if actor actually exists in storage, not just if property store is initialized
        if core_actor.actor and len(core_actor.actor) > 0:
            logger.debug(f"Successfully loaded core actor {actor_id} from storage")
        else:
            logger.warning(
                f"Actor {actor_id} not found in ActingWeb storage - creating actor to bridge OAuth2 authentication"
            )

            # Try to create the actor if it doesn't exist
            try:
                user_email = token_data.get("email") or token_data.get(
                    "user_email", f"oauth2-user-{actor_id}@unknown.domain"
                )

                new_actor = actor_module.Actor(config=self.config)
                actor_url = f"{self.config.proto}{self.config.fqdn}/{actor_id}"
                created_actor = new_actor.create(
                    url=actor_url,
                    creator=user_email,
                    passphrase="",  # OAuth2 actors don't need passphrases
                    actor_id=actor_id,
                )

                if created_actor:
                    logger.info(f"Successfully created ActingWeb actor {actor_id} for OAuth2 user {user_email}")
                    core_actor = actor_module.Actor(actor_id, self.config)
                else:
                    logger.error(f"Failed to create ActingWeb actor {actor_id}")
                    return None

            except Exception as e:
                logger.error(f"Error creating ActingWeb actor {actor_id}: {e}")
                return None

        actor_interface = ActorInterface(core_actor=core_actor)

        # Cache the actor
        _actor_cache[actor_id] = {"actor": actor_interface, "last_accessed": current_time}

        return actor_interface


    def _lookup_mcp_trust_relationship(self, actor: ActorInterface, client_id: str, token_data: Dict[str, Any]) -> Any:
        """
        Lookup trust relationship for MCP client.

        This method finds the trust relationship that was created during OAuth2
        authentication, which links the MCP client to the actor with appropriate permissions.

        Args:
            actor: ActorInterface instance
            client_id: OAuth2 client ID
            token_data: Token validation data

        Returns:
            Trust relationship instance or None
        """
        try:
            # Debug: List all existing trust relationships
            all_trusts = actor.trust.relationships
            logger.debug(f"DEBUG: Found {len(all_trusts)} total trust relationships for actor {actor.id}")
            for trust in all_trusts:
                peer_id = getattr(trust, "peerid", "unknown")
                established_via = getattr(trust, "established_via", "unknown")
                relationship = getattr(trust, "relationship", "unknown")
                logger.debug(
                    f"DEBUG: Trust - peer_id: {peer_id}, established_via: {established_via}, relationship: {relationship}"
                )

            # Prefer direct lookup by normalized email-derived peer_id if available
            user_email = token_data.get("email") or token_data.get("user_email")
            logger.debug(f"DEBUG: Looking up MCP trust for client_id: {client_id}, user_email: {user_email}")
            if user_email:
                normalized = user_email.replace("@", "_at_").replace(".", "_dot_")
                peer_id = f"mcp:{normalized}"
                logger.debug(f"DEBUG: Attempting direct lookup with peer_id: {peer_id}")
                direct = actor.trust.get_relationship(peer_id)
                if direct:
                    logger.debug(f"Found MCP trust via peer_id: {peer_id}")
                    return direct
                else:
                    logger.debug(f"DEBUG: Direct lookup failed for peer_id: {peer_id}")

            trusts = actor.trust.relationships

            # Fallback: scan for established_via='oauth2' and matching trust_type if provided
            desired_type = token_data.get("trust_type") or "mcp_client"
            logger.debug(f"DEBUG: Token data: {token_data}")
            logger.debug(
                f"DEBUG: Scanning {len(trusts)} trusts for established_via='oauth2' with desired_type: {desired_type}"
            )
            for trust in trusts:
                via = getattr(trust, "established_via", None)
                rel = getattr(trust, "relationship", None)
                peer_ident = getattr(trust, "peer_identifier", None)
                logger.debug(
                    f"DEBUG: Checking trust - via: {via}, rel: {rel}, peer_ident: {peer_ident}, user_email: {user_email}"
                )

                # Match on established_via - any OAuth2 trust should work for MCP clients
                if via == "oauth2":
                    logger.debug(f"Found OAuth2 trust: peer={trust.peerid}, via={via}, rel={rel}")
                    return trust

                # Fallback: If established_via is None but this looks like an OAuth2 trust
                # (peer_id starts with 'oauth2:'), assume it should be 'oauth2'
                peer_id_str = str(getattr(trust, "peerid", ""))
                if via is None and peer_id_str.startswith("oauth2:"):
                    logger.warning(
                        f"Found OAuth2 trust with missing established_via - assuming valid: peer={trust.peerid}, rel={rel}"
                    )
                    logger.warning(f"Consider updating this trust relationship to include established_via='oauth2'")
                    return trust

            logger.warning(f"No trust found for MCP client {client_id}; permissions will be empty")
            logger.debug(
                f"DEBUG: Trust lookup failed - no matching trust found with established_via='oauth2' and desired_type: {desired_type}"
            )
            return None

        except Exception as e:
            logger.error(f"Error looking up MCP trust relationship: {e}")
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
