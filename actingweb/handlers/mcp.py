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

import json
import logging
import re
import time
from typing import Any

# Global cache for MCP client info during session establishment
_mcp_client_info_cache: dict[str, dict[str, Any]] = {}

# Imports after MCP availability check
from .. import aw_web_request  # noqa: E402
from .. import config as config_class  # noqa: E402
from ..interface.actor_interface import ActorInterface  # noqa: E402
from ..interface.hooks import HookRegistry  # noqa: E402
from ..mcp.sdk_server import get_server_manager  # noqa: E402
from ..runtime_context import RuntimeContext  # noqa: E402
from .base_handler import BaseHandler  # noqa: E402

logger = logging.getLogger(__name__)

# Global caches for MCP performance optimization
_token_cache: dict[str, dict[str, Any]] = {}  # token -> validation data
_actor_cache: dict[
    str, dict[str, Any]
] = {}  # actor_id -> {actor, trust_context, last_accessed}
_trust_cache: dict[str, Any] = {}  # actor_id -> trust_relationship
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
        hooks: HookRegistry | None = None,
    ) -> None:
        super().__init__(webobj, config, hooks)
        self.server_manager = get_server_manager()

    def _cleanup_expired_cache_entries(self) -> None:
        """Remove expired entries from all caches."""
        current_time = time.time()

        # Clean token cache
        expired_tokens = [
            token
            for token, data in _token_cache.items()
            if current_time - data.get("cached_at", 0) > _cache_ttl
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

    def get(self) -> dict[str, Any]:
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
                "transport": {
                    "type": "http",
                    "endpoint": "/mcp",
                    "supported_versions": ["2024-11-05"],
                },
                "authentication": {
                    "required": True,
                    "type": "oauth2",
                    "discovery_url": f"{self.config.proto}{self.config.fqdn}/.well-known/oauth-protected-resource",
                },
            }

        except Exception as e:
            logger.error(f"Error handling MCP GET request: {e}")
            return self.error_response(500, f"Internal server error: {str(e)}")

    def post(self, data: dict[str, Any]) -> dict[str, Any]:
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
                # Set proper HTTP 401 response headers for framework-agnostic handling
                base_url = f"{self.config.proto}{self.config.fqdn}"
                # Include error="invalid_token" to force OAuth2 clients to invalidate cached tokens
                # Per RFC 6750 Section 3.1: https://tools.ietf.org/html/rfc6750#section-3.1
                www_auth = f'Bearer realm="ActingWeb MCP", error="invalid_token", error_description="Authentication required", authorization_uri="{base_url}/oauth/authorize"'

                # Set response headers for authentication challenge
                self.response.headers["WWW-Authenticate"] = www_auth
                self.response.set_status(401, "Unauthorized")

                return self._create_jsonrpc_error(
                    request_id, -32002, "Authentication required for MCP access"
                )

            # Extract and update client info if provided in the request
            # MCP clients send clientInfo with many requests, not just initialize
            self._update_actor_client_info(actor, data)

            # MCP access is controlled granularly through individual permission types
            # (tools, resources, prompts) - no need for separate MCP access check

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
                return self._create_jsonrpc_error(
                    request_id, -32601, f"Method not found: {method}"
                )

        except Exception as e:
            logger.error(f"Error handling MCP POST request: {e}")
            return self._create_jsonrpc_error(
                data.get("id"), -32603, f"Internal error: {str(e)}"
            )

    def _has_mcp_tools(self) -> bool:
        """Check if server has any MCP-exposed tools."""
        if not self.hooks:
            return False

        # Check if any action hooks are MCP-exposed
        from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed

        for _action_name, hooks in self.hooks._action_hooks.items():
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
        from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed

        for _method_name, hooks in self.hooks._method_hooks.items():
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
        from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed

        for _method_name, hooks in self.hooks._method_hooks.items():
            for hook in hooks:
                if is_mcp_exposed(hook):
                    metadata = get_mcp_metadata(hook)
                    if metadata and metadata.get("type") == "prompt":
                        return True
        return False

    def _handle_initialize(
        self, request_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle MCP initialize request."""
        # Store client info for later use during OAuth2 authentication
        client_info = params.get("clientInfo", {})
        if client_info:
            # Store in a global cache keyed by IP or other identifier
            # This will be retrieved during OAuth2 flow to store permanently
            self._store_mcp_client_info_temporarily(client_info)
            logging.debug(f"Stored MCP client info: {client_info}")

            # ALSO try to store immediately if we have an authenticated actor
            try:
                # Check if this is an authenticated request (for re-initialization)
                actor = self.authenticate_and_get_actor_cached()
                if actor:
                    logger.debug(
                        "Found authenticated actor during initialize, storing client info in trust relationship"
                    )
                    self._update_trust_with_client_info(actor, client_info)
            except Exception:
                pass

        # Build capabilities based on what's actually available
        capabilities: dict[str, Any] = {}

        # Tools capability
        if self._has_mcp_tools():
            capabilities["tools"] = {
                "listChanged": True
            }  # Indicates tools can be dynamically discovered

        # Resources capability
        if self._has_mcp_resources():
            capabilities["resources"] = {
                "subscribe": False,  # We don't support resource subscriptions yet
                "listChanged": True,  # Resources can be dynamically discovered
            }

        # Prompts capability
        if self._has_mcp_prompts():
            capabilities["prompts"] = {
                "listChanged": True
            }  # Prompts can be dynamically discovered

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": capabilities,
                "serverInfo": {"name": "ActingWeb MCP Server", "version": "1.0.0"},
            },
        }

    def _handle_tools_list(self, request_id: Any, actor: Any) -> dict[str, Any]:
        """Handle MCP tools/list request with permission filtering and client filtering."""
        global _mcp_client_info_cache
        tools = []

        if self.hooks:
            from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed
            from ..permission_evaluator import (
                PermissionResult,
                PermissionType,
                get_permission_evaluator,
            )

            # Resolve peer_id from runtime context (set during auth)
            runtime_context = RuntimeContext(actor)
            mcp_context = runtime_context.get_mcp_context()
            peer_id = mcp_context.peer_id if mcp_context else None

            # Get evaluator if the permission system is initialized
            evaluator = None
            try:
                evaluator = get_permission_evaluator(self.config) if peer_id else None
            except Exception as e:
                logger.debug(f"Permission evaluator unavailable during tools/list: {e}")
                evaluator = None

            # Detect client type for filtering
            client_type = None
            try:
                from ..runtime_context import get_client_info_from_context

                client_info = get_client_info_from_context(actor)
                if client_info and client_info.get("name"):
                    client_name = client_info["name"].lower()
                    # Classify client type based on name patterns
                    if any(
                        pattern in client_name
                        for pattern in ["openai", "chatgpt", "gpt"]
                    ):
                        client_type = "chatgpt"
                    elif any(
                        pattern in client_name for pattern in ["claude", "anthropic"]
                    ):
                        client_type = "claude"
                    elif "cursor" in client_name:
                        client_type = "cursor"
                    elif "mcp-inspector" in client_name:
                        client_type = "mcp_inspector"
                    else:
                        client_type = "universal"
                    # Client type detected (no logging needed for routine operation)
                else:
                    # Fallback: Check global client info cache like the other handler does
                    session_key = self._get_session_key()
                    if session_key in _mcp_client_info_cache:
                        cached_info = _mcp_client_info_cache[session_key]
                        if cached_info and "client_info" in cached_info:
                            fallback_client_info = cached_info["client_info"]
                            if fallback_client_info.get("name"):
                                client_name = fallback_client_info["name"].lower()
                                if any(
                                    pattern in client_name
                                    for pattern in ["openai", "chatgpt", "gpt"]
                                ):
                                    client_type = "chatgpt"
                                elif any(
                                    pattern in client_name
                                    for pattern in ["claude", "anthropic"]
                                ):
                                    client_type = "claude"
                                elif "cursor" in client_name:
                                    client_type = "cursor"
                                elif "mcp-inspector" in client_name:
                                    client_type = "mcp_inspector"
                                else:
                                    client_type = "universal"
                                # Client type detected (no logging needed for routine operation)

                    if not client_type:
                        client_type = "universal"
            except Exception as e:
                logger.debug(f"Could not detect client type for tools filtering: {e}")
                client_type = "universal"

            # Discover MCP tools from action hooks
            for action_name, hooks in self.hooks._action_hooks.items():
                for hook in hooks:
                    if not is_mcp_exposed(hook):
                        continue
                    metadata = get_mcp_metadata(hook)
                    if not (metadata and metadata.get("type") == "tool"):
                        continue

                    tool_name = metadata.get("name") or action_name

                    # Filter by client restrictions
                    allowed_clients = metadata.get("allowed_clients")
                    if allowed_clients and client_type:
                        if client_type not in allowed_clients:
                            logger.debug(
                                f"Tool '{tool_name}' filtered out for client type '{client_type}' (allowed: {allowed_clients})"
                            )
                            continue

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
                            logger.warning(
                                f"Error evaluating tool permission for '{tool_name}': {e}"
                            )
                            # Fail-open on evaluation errors to avoid hard lockouts

                    # Use client-specific description if available
                    client_descriptions = metadata.get("client_descriptions", {})
                    if client_type and client_type in client_descriptions:
                        description = client_descriptions[client_type]
                    else:
                        description = (
                            metadata.get("description")
                            or f"Execute {action_name} action"
                        )

                    tool_def = {
                        "name": tool_name,
                        "description": description,
                    }

                    input_schema = metadata.get("input_schema")
                    if input_schema:
                        tool_def["inputSchema"] = input_schema

                    # Add annotations if present (for ChatGPT safety evaluation)
                    annotations = metadata.get("annotations")
                    if annotations:
                        tool_def["annotations"] = annotations

                    tools.append(tool_def)

        # Apply client-specific formatting for tools/list response
        tools_result = {"tools": tools}

        # Get client info from trust relationship to determine formatting
        try:
            from ..runtime_context import get_client_info_from_context

            client_info = get_client_info_from_context(actor)

            # Fallback: Check global client info cache if trust relationship doesn't have client info yet
            if not client_info:
                session_key = self._get_session_key()
                if session_key in _mcp_client_info_cache:
                    cached_info = _mcp_client_info_cache[session_key]
                    if cached_info and "client_info" in cached_info:
                        fallback_client_info = cached_info["client_info"]
                        if fallback_client_info.get("name"):
                            client_info = {
                                "name": fallback_client_info["name"],
                                "version": fallback_client_info.get("version", ""),
                                "platform": "",
                                "type": "mcp",
                            }
                            logger.debug(
                                f"Using fallback client info from cache: {client_info}"
                            )

            if client_info and client_info.get("name"):
                client_name = client_info["name"].lower()

                # Apply ChatGPT-specific formatting if needed
                if any(
                    pattern in client_name for pattern in ["openai", "chatgpt", "gpt"]
                ):
                    # ChatGPT MCP specification requires direct JSON structure for tools/list (not JSON-encoded text)
                    logger.debug(
                        f"Applying ChatGPT formatting for tools/list: {len(tools)} tools (client: {client_name})"
                    )
                    return {"jsonrpc": "2.0", "id": request_id, "result": tools_result}
        except Exception as e:
            logger.debug(
                f"Could not apply client-specific formatting for tools/list: {e}"
            )
            # Fall back to standard formatting

        return {"jsonrpc": "2.0", "id": request_id, "result": tools_result}

    def _handle_resources_list(self, request_id: Any, actor: Any) -> dict[str, Any]:
        """Handle MCP resources/list request with permission filtering."""
        resources = []

        if self.hooks:
            from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed
            from ..permission_evaluator import (
                PermissionResult,
                PermissionType,
                get_permission_evaluator,
            )

            runtime_context = RuntimeContext(actor)
            mcp_context = runtime_context.get_mcp_context()
            peer_id = mcp_context.peer_id if mcp_context else None

            evaluator = None
            try:
                evaluator = get_permission_evaluator(self.config) if peer_id else None
            except Exception as e:
                logger.debug(
                    f"Permission evaluator unavailable during resources/list: {e}"
                )
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
                    uri_template = (
                        metadata.get("uri_template") or f"actingweb://{method_name}"
                    )

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
                        "name": metadata.get("name")
                        or method_name.replace("_", " ").title(),
                        "description": metadata.get("description")
                        or f"Access {method_name} resource",
                        # Output key follows MCP spec; decorator uses 'mime_type'
                        "mimeType": metadata.get("mime_type", "application/json"),
                    }
                    resources.append(resource_def)

        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": resources}}

    def _handle_prompts_list(self, request_id: Any, actor: Any) -> dict[str, Any]:
        """Handle MCP prompts/list request with permission filtering."""
        prompts = []

        if self.hooks:
            from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed
            from ..permission_evaluator import (
                PermissionResult,
                PermissionType,
                get_permission_evaluator,
            )

            runtime_context = RuntimeContext(actor)
            mcp_context = runtime_context.get_mcp_context()
            peer_id = mcp_context.peer_id if mcp_context else None

            evaluator = None
            try:
                evaluator = get_permission_evaluator(self.config) if peer_id else None
            except Exception as e:
                logger.debug(
                    f"Permission evaluator unavailable during prompts/list: {e}"
                )
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

    def _handle_tool_call(
        self, request_id: Any, params: dict[str, Any], actor: Any
    ) -> dict[str, Any]:
        """Handle MCP tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            return self._create_jsonrpc_error(request_id, -32602, "Missing tool name")

        if not self.hooks:
            return self._create_jsonrpc_error(
                request_id, -32603, "No hooks registry available"
            )

        # Check permission before finding/dispatching the hook
        try:
            from ..permission_evaluator import (
                PermissionResult,
                PermissionType,
                get_permission_evaluator,
            )

            runtime_context = RuntimeContext(actor)
            mcp_context = runtime_context.get_mcp_context()
            peer_id = mcp_context.peer_id if mcp_context else None
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
        from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed

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
                                        "result": {
                                            "content": [
                                                {"type": "text", "text": str(result)}
                                            ]
                                        },
                                    }
                            except Exception as e:
                                logger.error(f"Error executing tool {tool_name}: {e}")
                                return self._create_jsonrpc_error(
                                    request_id,
                                    -32603,
                                    f"Tool execution failed: {str(e)}",
                                )

        return self._create_jsonrpc_error(
            request_id, -32601, f"Tool not found: {tool_name}"
        )

    def _handle_prompt_get(
        self, request_id: Any, params: dict[str, Any], actor: Any
    ) -> dict[str, Any]:
        """Handle MCP prompts/get request."""
        prompt_name = params.get("name")
        arguments = params.get("arguments", {})

        if not prompt_name:
            return self._create_jsonrpc_error(request_id, -32602, "Missing prompt name")

        if not self.hooks:
            return self._create_jsonrpc_error(
                request_id, -32603, "No hooks registry available"
            )

        # Check permission before finding/dispatching the hook
        try:
            from ..permission_evaluator import (
                PermissionResult,
                PermissionType,
                get_permission_evaluator,
            )

            runtime_context = RuntimeContext(actor)
            mcp_context = runtime_context.get_mcp_context()
            peer_id = mcp_context.peer_id if mcp_context else None
            if peer_id:
                evaluator = get_permission_evaluator(self.config)
                decision = evaluator.evaluate_permission(
                    actor.id,
                    peer_id,
                    PermissionType.PROMPTS,
                    prompt_name,
                    operation="invoke",
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
        from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed

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
                                            "description",
                                            f"Generated prompt for {method_name}",
                                        ),
                                        "messages": [
                                            {
                                                "role": "user",
                                                "content": {
                                                    "type": "text",
                                                    "text": prompt_text,
                                                },
                                            }
                                        ],
                                    },
                                }
                            except Exception as e:
                                logger.error(
                                    f"Error generating prompt {prompt_name}: {e}"
                                )
                                return self._create_jsonrpc_error(
                                    request_id,
                                    -32603,
                                    f"Prompt generation failed: {str(e)}",
                                )

        return self._create_jsonrpc_error(
            request_id, -32601, f"Prompt not found: {prompt_name}"
        )

    def _handle_resource_read(
        self, request_id: Any, params: dict[str, Any], actor: Any
    ) -> dict[str, Any]:
        """Handle MCP resources/read request."""
        uri = params.get("uri")

        if not uri:
            return self._create_jsonrpc_error(
                request_id, -32602, "Missing resource URI"
            )

        if not self.hooks:
            return self._create_jsonrpc_error(
                request_id, -32603, "No hooks registry available"
            )

        try:
            # Check permission before accessing resource
            try:
                from ..permission_evaluator import (
                    PermissionResult,
                    PermissionType,
                    get_permission_evaluator,
                )

                trust_context = getattr(actor, "_mcp_trust_context", None)
                peer_id = trust_context.get("peer_id") if trust_context else None
                if peer_id and uri:
                    evaluator = get_permission_evaluator(self.config)
                    decision = evaluator.evaluate_permission(
                        actor.id,
                        peer_id,
                        PermissionType.RESOURCES,
                        uri,
                        operation="read",
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
            from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed

            # Reuse URI template matching from SDK server implementation
            from ..mcp.sdk_server import _match_uri_template

            for method_name, hooks in self.hooks._method_hooks.items():
                for hook in hooks:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "resource":
                            # Prefer 'uri_template' from decorator; fall back to legacy
                            resource_uri = (
                                metadata.get("uri_template")
                                or metadata.get("uri")
                                or f"actingweb://{method_name}"
                            )
                            uri_pattern = metadata.get("uri_pattern")

                            # Check for template/pattern match
                            uri_matches = False
                            variables: dict[str, str] | None = None
                            try:
                                variables = _match_uri_template(
                                    str(resource_uri), str(uri)
                                )
                            except Exception:
                                variables = None
                            if variables is not None:
                                uri_matches = True
                            elif uri_pattern:
                                try:
                                    if re.match(uri_pattern, str(uri)):
                                        uri_matches = True
                                except re.error:
                                    logger.warning(
                                        f"Invalid URI pattern in resource metadata: {uri_pattern}"
                                    )

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
                                                    "mimeType": metadata.get(
                                                        "mime_type", "application/json"
                                                    ),
                                                    "text": content_text,
                                                }
                                            ]
                                        },
                                    }
                                except Exception as e:
                                    logger.error(f"Error executing resource {uri}: {e}")
                                    return self._create_jsonrpc_error(
                                        request_id,
                                        -32603,
                                        f"Resource execution failed: {str(e)}",
                                    )

            return self._create_jsonrpc_error(
                request_id, -32601, f"Resource not found: {uri}"
            )

        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}")
            return self._create_jsonrpc_error(
                request_id, -32603, f"Resource read failed: {str(e)}"
            )

    def _handle_notifications_initialized(
        self, request_id: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle MCP notifications/initialized request."""
        # This is a notification that the client has finished initialization
        # According to MCP spec, this is a notification (no response expected)
        # However, some clients may send it as a request, so we respond
        logger.debug("MCP client initialization completed")

        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    def _handle_ping(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Handle MCP ping request."""
        # Ping is used for keepalive/connectivity testing
        # Return empty result to confirm server is alive
        logger.debug("MCP ping received")

        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    def _create_jsonrpc_error(
        self, request_id: Any, code: int, message: str
    ) -> dict[str, Any]:
        """Create a JSON-RPC error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

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
                    if (
                        current_time - cached_actor_data.get("last_accessed", 0)
                        < _cache_ttl
                    ):
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

                        # Update runtime context with MCP authentication info
                        runtime_context = RuntimeContext(actor_interface)
                        runtime_context.set_mcp_context(
                            client_id=client_id,
                            trust_relationship=trust_relationship,
                            peer_id=trust_relationship.peerid
                            if trust_relationship
                            else "",
                            token_data=token_data,
                        )

                        # Log cache performance periodically
                        total_requests = sum(_cache_stats.values())
                        if (
                            total_requests > 0 and total_requests % 10 == 0
                        ):  # Every 10 requests
                            logger.debug(
                                f"MCP cache stats - Token hits: {_cache_stats['token_hits']}, Actor hits: {_cache_stats['actor_hits']}, Trust hits: {_cache_stats['trust_hits']}"
                            )

                        # Serving cached MCP authentication (no logging needed for routine operation)
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
            actor_interface = self._get_or_create_actor_cached(
                actor_id, token_data, current_time
            )
            if not actor_interface:
                return None

            # Lookup and cache trust relationship
            trust_relationship = self._lookup_mcp_trust_relationship(
                actor_interface, client_id, token_data
            )
            _trust_cache[actor_id] = trust_relationship

            # Mark client as peer_approved on successful authentication (if not already)
            self._mark_client_peer_approved(
                actor_interface, client_id, trust_relationship
            )

            # Store runtime context for permission checking and client identification
            runtime_context = RuntimeContext(actor_interface)
            runtime_context.set_mcp_context(
                client_id=client_id,
                trust_relationship=trust_relationship,
                peer_id=trust_relationship.peerid if trust_relationship else "",
                token_data=token_data,
            )

            logger.debug(
                f"Successfully authenticated MCP client {client_id} -> actor {actor_id} with trust context"
            )
            return actor_interface

        except Exception as e:
            logger.error(f"Error during ActingWeb token authentication: {e}")
            return None

    def _get_or_create_actor_cached(
        self, actor_id: str, token_data: dict[str, Any], current_time: float
    ) -> ActorInterface | None:
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
                    logger.info(
                        f"Successfully created ActingWeb actor {actor_id} for OAuth2 user {user_email}"
                    )
                    core_actor = actor_module.Actor(actor_id, self.config)
                else:
                    logger.error(f"Failed to create ActingWeb actor {actor_id}")
                    return None

            except Exception as e:
                logger.error(f"Error creating ActingWeb actor {actor_id}: {e}")
                return None

        registry = getattr(self.config, "service_registry", None)
        actor_interface = ActorInterface(
            core_actor=core_actor, service_registry=registry
        )

        # Cache the actor
        _actor_cache[actor_id] = {
            "actor": actor_interface,
            "last_accessed": current_time,
        }

        return actor_interface

    def _lookup_mcp_trust_relationship(
        self, actor: ActorInterface, client_id: str, token_data: dict[str, Any]
    ) -> Any:
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
            # Prefer direct lookup by normalized email-derived peer_id if available
            user_email = token_data.get("email") or token_data.get("user_email")
            if user_email:
                normalized_email = user_email.replace("@", "_at_").replace(".", "_dot_")

                normalized_client = (
                    client_id.replace("@", "_at_")
                    .replace(".", "_dot_")
                    .replace(":", "_colon_")
                )
                peer_id_unique = f"oauth2:{normalized_email}:{normalized_client}"
                direct = actor.trust.get_relationship(peer_id_unique)
                if direct:
                    logger.debug(f"Found MCP trust for client {client_id}")
                    return direct

            trusts = actor.trust.relationships

            # Fallback: scan for established_via='oauth2' or 'oauth2_client' and matching trust_type if provided
            for trust in trusts:
                via = getattr(trust, "established_via", None)
                rel = getattr(trust, "relationship", None)

                # Match on established_via AND client_id to ensure correct client
                if via == "oauth2":
                    # Check if this trust is for the specific client_id
                    peer_id_str = str(getattr(trust, "peerid", ""))
                    if client_id in peer_id_str:
                        logger.debug(f"Found MCP trust for client {client_id}")
                        return trust

                # Handle oauth2_client established trusts (client credentials flow)
                elif via == "oauth2_client":
                    # Check if this trust is for the specific client_id
                    peer_id_str = str(getattr(trust, "peerid", ""))
                    if client_id in peer_id_str:
                        logger.debug(f"Found MCP trust for client {client_id}")
                        return trust

                # Fallback: If established_via is None but this looks like an OAuth2 trust
                # (peer_id starts with 'oauth2:' or 'oauth2_client:'), assume it should be valid
                peer_id_str = str(getattr(trust, "peerid", ""))
                if via is None and (
                    peer_id_str.startswith("oauth2:")
                    or peer_id_str.startswith("oauth2_client:")
                ):
                    # Check if this trust is for the specific client_id
                    if client_id in peer_id_str:
                        trust_type = (
                            "oauth2_client"
                            if peer_id_str.startswith("oauth2_client:")
                            else "oauth2"
                        )
                        logger.warning(
                            f"Found {trust_type} trust with missing established_via - assuming valid: peer={trust.peerid}, rel={rel}"
                        )
                        logger.warning(
                            f"Consider updating this trust relationship to include established_via='{trust_type}'"
                        )
                        return trust

            logger.warning(
                f"No trust found for MCP client {client_id}; permissions will be empty"
            )
            return None

        except Exception as e:
            logger.error(f"Error looking up MCP trust relationship: {e}")
            return None

    def get_auth_header(self) -> str | None:
        """Get Authorization header from request."""
        if (
            hasattr(self, "request")
            and self.request
            and hasattr(self.request, "headers")
            and self.request.headers
        ):
            auth_header = self.request.headers.get(
                "Authorization"
            ) or self.request.headers.get("authorization")
            return str(auth_header) if auth_header is not None else None
        return None

    def initiate_oauth2_redirect(self) -> dict[str, Any]:
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

    def validate_google_token_and_check_actor_email(
        self, bearer_token: str, expected_actor_id: str
    ) -> bool:
        """
        Validate Google OAuth2 token and verify it matches the expected actor's email.

        This prevents identity confusion attacks where a Google token for one email
        is used to authenticate as an actor created with a different email.

        Args:
            bearer_token: OAuth2 access token from Google
            expected_actor_id: Actor ID to check email against

        Returns:
            True if token is valid and matches actor's email, False otherwise
        """
        if not bearer_token or not expected_actor_id:
            return False

        try:
            import requests

            # Use Google TokenInfo API to validate token and get email
            tokeninfo_url = f"https://www.googleapis.com/oauth2/v1/tokeninfo?access_token={bearer_token}"

            response = requests.get(url=tokeninfo_url, timeout=(5, 10))

            if response.status_code != 200:
                logger.debug(
                    f"Google tokeninfo validation failed: {response.status_code}"
                )
                return False

            token_info = response.json()

            # Check if token is valid (has required fields)
            if "email" not in token_info:
                logger.debug("Google token does not contain email scope")
                return False

            # Verify token is not expired (tokeninfo returns this)
            if "expires_in" in token_info:
                expires_in = int(token_info.get("expires_in", 0))
                if expires_in <= 0:
                    logger.debug("Google token has expired")
                    return False

            authenticated_email = token_info.get("email", "").lower()
            verified_email = token_info.get("verified_email")

            # Ensure email is verified
            if verified_email == "false" or verified_email is False:
                logger.warning(f"Google email {authenticated_email} is not verified")
                return False

            # Load the actor and check if the email matches
            from .. import actor as actor_module

            actor_instance = actor_module.Actor(expected_actor_id, config=self.config)
            if not actor_instance.actor:
                logger.error(
                    f"Actor {expected_actor_id} not found for email validation"
                )
                return False

            # Get the actor's creator (usually email) or check email property
            actor_email = actor_instance.creator
            try:
                # Prefer the email property if set
                if actor_instance.property:
                    email_prop = actor_instance.property.get("email")
                    if email_prop:
                        actor_email = email_prop
            except (AttributeError, KeyError):
                # Property access failed, use creator as fallback
                pass

            if not actor_email:
                logger.warning(
                    f"Actor {expected_actor_id} has no email to validate against"
                )
                return False

            actor_email = actor_email.lower()

            # Check if authenticated email matches actor's email
            if authenticated_email != actor_email:
                logger.error(
                    f"Email mismatch: Google token for {authenticated_email} "
                    f"but actor {expected_actor_id} has email {actor_email}"
                )
                return False

            logger.debug(
                f"Successfully validated Google token for {authenticated_email} matches actor {expected_actor_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Error validating Google token against actor email: {e}")
            return False

    def _update_actor_client_info(self, actor, request_data: dict[str, Any]) -> None:
        """
        Extract and update client info from MCP request data.

        MCP clients send clientInfo with many requests, not just initialize.
        This method ensures we always have the latest client information stored.
        """
        try:
            # Check for clientInfo in request params (common in tools/call, etc.)
            client_info = None

            # Look for clientInfo in request params
            params = request_data.get("params", {})
            if isinstance(params, dict) and "clientInfo" in params:
                client_info = params["clientInfo"]

            # Look for clientInfo at top level (sometimes sent this way)
            elif "clientInfo" in request_data:
                client_info = request_data["clientInfo"]

            if client_info and isinstance(client_info, dict):
                self._update_trust_with_client_info(actor, client_info)

        except Exception as e:
            logger.debug(f"Could not update client info from request: {e}")
            # Non-critical, don't raise exception

    def _update_trust_with_client_info(
        self, actor, client_info: dict[str, Any]
    ) -> None:
        """
        Update trust relationship with MCP client metadata instead of storing in actor properties.

        This replaces the old actor-level storage with proper trust relationship attributes.

        Args:
            actor: ActorInterface instance
            client_info: Client information dictionary from MCP initialize
        """
        try:
            # Try to find the current trust relationship for this actor
            runtime_context = RuntimeContext(actor)
            mcp_context = runtime_context.get_mcp_context()

            if not mcp_context or not mcp_context.peer_id:
                logger.debug(
                    "No MCP context or peer_id in runtime context, cannot update trust with client info"
                )
                return

            peer_id = mcp_context.peer_id

            # Extract client metadata from client_info
            client_name = client_info.get("name", "MCP Client")
            client_version = client_info.get("version")

            # Get platform info from User-Agent or client info
            client_platform = None
            if hasattr(self.request, "headers") and self.request.headers:
                client_platform = self.request.headers.get("User-Agent")
            if not client_platform and "implementation" in client_info:
                impl = client_info["implementation"]
                if isinstance(impl, dict):
                    client_platform = (
                        f"{impl.get('name', 'Unknown')} {impl.get('version', '')}"
                    )

            # Check if client info has actually changed before updating
            trust_rel = mcp_context.trust_relationship
            existing_name = (
                getattr(trust_rel, "client_name", None) if trust_rel else None
            )
            existing_version = (
                getattr(trust_rel, "client_version", None) if trust_rel else None
            )
            existing_platform = (
                getattr(trust_rel, "client_platform", None) if trust_rel else None
            )

            # Skip update if client info hasn't changed
            if (
                existing_name == client_name
                and existing_version == client_version
                and existing_platform == client_platform
            ):
                return

            # Update the trust relationship with client metadata and connection timestamp
            from datetime import datetime

            from .. import actor as actor_module
            from ..trust import canonical_connection_method

            core_actor = actor_module.Actor(actor.id, config=self.config)
            if core_actor.actor:
                # Get the relationship type from the trust relationship
                relationship = getattr(
                    mcp_context.trust_relationship, "relationship", "mcp_client"
                )
                established_via = getattr(
                    mcp_context.trust_relationship, "established_via", "oauth2_client"
                )

                # Update last connection timestamp
                now_iso = datetime.utcnow().isoformat()

                success = core_actor.modify_trust_and_notify(
                    relationship=relationship,
                    peerid=peer_id,
                    client_name=client_name,
                    client_version=client_version,
                    client_platform=client_platform,
                    last_accessed=now_iso,
                    last_connected_via=canonical_connection_method(established_via),
                )
                if success:
                    logger.info(
                        f"Updated trust relationship {peer_id} with client info: {client_name}"
                    )
                else:
                    logger.warning(
                        f"Failed to update trust relationship {peer_id} with client info"
                    )
            else:
                logger.error(
                    f"Could not load actor {actor.id} to update trust with client info"
                )

        except Exception as e:
            logger.error(f"Could not update trust with client info: {e}")
            # Non-critical, don't raise exception

    def _store_mcp_client_info_temporarily(self, client_info: dict[str, Any]) -> None:
        """Store MCP client info temporarily until OAuth2 authentication completes."""
        global _mcp_client_info_cache

        # Use client IP and user agent as session key
        session_key = self._get_session_key()
        _mcp_client_info_cache[session_key] = {
            "client_info": client_info,
            "timestamp": time.time(),
        }

        # Clean up old entries (older than 10 minutes)
        current_time = time.time()
        expired_keys = [
            key
            for key, data in _mcp_client_info_cache.items()
            if current_time - data["timestamp"] > 600
        ]
        for key in expired_keys:
            del _mcp_client_info_cache[key]

    def _get_session_key(self) -> str:
        """Generate a session key based on request characteristics."""
        # Use client IP as primary identifier
        client_ip = getattr(self.request, "remote_addr", "unknown")
        # Add user agent for additional uniqueness
        user_agent = getattr(self.request, "headers", {}).get("User-Agent", "")[:50]
        return f"{client_ip}:{hash(user_agent)}"

    @classmethod
    def get_stored_client_info(cls, session_key: str) -> dict[str, Any] | None:
        """Retrieve stored client info for a session key."""
        global _mcp_client_info_cache
        if session_key in _mcp_client_info_cache:
            data = _mcp_client_info_cache[session_key]
            if time.time() - data["timestamp"] < 600:  # 10 minutes
                return data["client_info"]
            else:
                del _mcp_client_info_cache[session_key]
        return None

    @classmethod
    def clear_token_from_cache(cls, token: str) -> bool:
        """
        Clear a specific token from the MCP authentication cache.

        This should be called during logout to ensure revoked tokens are immediately
        invalidated in the cache, preventing authentication via cached token data.

        Args:
            token: The token to remove from cache

        Returns:
            True if token was found and removed, False if not found in cache
        """
        global _token_cache, _actor_cache, _trust_cache

        token_found = False

        # Remove token from cache
        if token in _token_cache:
            # Get actor_id before removing token data to clean associated caches
            cached_data = _token_cache[token]
            actor_id = cached_data.get("actor_id")

            del _token_cache[token]
            token_found = True

            # Also clear associated actor and trust caches to force re-authentication
            if actor_id:
                if actor_id in _actor_cache:
                    del _actor_cache[actor_id]

                if actor_id in _trust_cache:
                    del _trust_cache[actor_id]

        return token_found

    def _mark_client_peer_approved(
        self, actor_interface, client_id: str, trust_relationship
    ) -> None:
        """
        Mark OAuth2 client as peer_approved on successful authentication.

        This sets peer_approved=True for OAuth2 clients that have successfully
        authenticated with correct credentials, completing the bilateral trust.

        Args:
            actor_interface: ActorInterface instance
            client_id: OAuth2 client ID that authenticated successfully
            trust_relationship: Found trust relationship (may be None)
        """
        try:
            if not trust_relationship:
                logger.debug(
                    f"No trust relationship found to mark as peer_approved for client {client_id}"
                )
                return

            # Check if this is an OAuth2 client trust that needs peer approval
            peer_id = getattr(trust_relationship, "peerid", "")
            established_via = getattr(trust_relationship, "established_via", "")

            logger.debug(
                f"Checking peer approval for client {client_id}: peer_id={peer_id}, established_via={established_via}"
            )

            if established_via != "oauth2_client":
                # Not an OAuth2 client trust - no need to update peer_approved
                logger.debug(
                    f"Trust relationship established_via='{established_via}' is not 'oauth2_client', skipping peer approval"
                )
                return

            # Check current peer_approved status
            current_peer_approved = getattr(trust_relationship, "peer_approved", False)
            logger.debug(
                f"Current peer_approved status for client {client_id}: {current_peer_approved}"
            )

            if current_peer_approved:
                # Already marked as peer_approved
                logger.debug(f"OAuth2 client {client_id} already peer_approved")
                return

            # Mark as peer_approved since authentication was successful
            from .. import actor as actor_module

            core_actor = actor_module.Actor(actor_interface.id, config=self.config)
            if core_actor.actor:
                success = core_actor.modify_trust_and_notify(
                    peerid=peer_id,
                    relationship=getattr(
                        trust_relationship, "relationship", "mcp_client"
                    ),
                    peer_approved=True,
                )
                if success:
                    logger.info(
                        f"Marked OAuth2 client {client_id} as peer_approved after successful authentication"
                    )
                else:
                    logger.warning(
                        f"Failed to mark OAuth2 client {client_id} as peer_approved"
                    )
            else:
                logger.error(
                    f"Could not load actor {actor_interface.id} to mark client peer_approved"
                )

        except Exception as e:
            logger.error(f"Error marking client {client_id} as peer_approved: {e}")
            # Non-critical - client can still access with existing permissions

    def error_response(self, status_code: int, message: str) -> dict[str, Any]:
        """Create an error response."""
        if status_code == 401:
            # Add WWW-Authenticate header for ActingWeb OAuth2 server
            # Include error="invalid_token" to force OAuth2 clients to invalidate cached tokens
            # Per RFC 6750 Section 3.1: https://tools.ietf.org/html/rfc6750#section-3.1
            try:
                base_url = f"{self.config.proto}{self.config.fqdn}"
                www_auth = f'Bearer realm="ActingWeb MCP", error="invalid_token", error_description="Authentication required", authorization_uri="{base_url}/oauth/authorize"'
                if hasattr(self, "response") and self.response:
                    self.response.headers["WWW-Authenticate"] = www_auth
            except Exception as e:
                logger.error(f"Error adding WWW-Authenticate header: {e}")
                if hasattr(self, "response") and self.response:
                    self.response.headers["WWW-Authenticate"] = (
                        'Bearer realm="ActingWeb MCP", error="invalid_token"'
                    )

        return {"error": True, "status_code": status_code, "message": message}
