"""
Async-capable handler for ActingWeb MCP endpoint.

This handler provides async versions of HTTP methods for optimal performance
with FastAPI and other async frameworks. It properly awaits async hooks
without thread pool overhead.
"""

import inspect
import logging
from typing import Any

from actingweb.handlers.mcp import MCPHandler

logger = logging.getLogger(__name__)


class AsyncMCPHandler(MCPHandler):
    """Async-capable MCP handler for FastAPI integration.

    Provides async versions of HTTP methods that properly await async hooks.
    Use this handler with FastAPI for optimal async performance.

    Inherits all synchronous methods from MCPHandler for backward compatibility.
    """

    async def get_async(self) -> dict[str, Any]:
        """
        Handle GET requests to /mcp endpoint asynchronously.

        For initial discovery, this returns basic information about the MCP server.
        Authentication will be handled during the MCP protocol negotiation.

        The GET method doesn't involve hook execution, so we can delegate to
        the parent's synchronous implementation.
        """
        # Reuse parent's get() - it doesn't call hooks, just returns metadata
        return self.get()

    async def post_async(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Handle POST requests to /mcp endpoint asynchronously.

        Handles MCP JSON-RPC protocol. The initialize method doesn't require authentication,
        but all other methods do.

        Uses async hook execution for optimal performance with FastAPI.
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
                return await self._handle_tool_call_async(request_id, params, actor)
            elif method == "prompts/get":
                return await self._handle_prompt_get_async(request_id, params, actor)
            elif method == "resources/read":
                return await self._handle_resource_read_async(request_id, params, actor)
            else:
                return self._create_jsonrpc_error(
                    request_id, -32601, f"Method not found: {method}"
                )

        except Exception as e:
            logger.error(f"Error handling MCP POST request: {e}")
            return self._create_jsonrpc_error(
                data.get("id"), -32603, f"Internal error: {str(e)}"
            )

    async def _handle_tool_call_async(
        self, request_id: Any, params: dict[str, Any], actor: Any
    ) -> dict[str, Any]:
        """Handle MCP tools/call request asynchronously."""
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
            from ..runtime_context import RuntimeContext

            runtime_context = RuntimeContext(actor)
            mcp_context = runtime_context.get_mcp_context()
            peer_id = mcp_context.peer_id if mcp_context else None
            if peer_id:
                evaluator = get_permission_evaluator(self.config)
                decision = evaluator.evaluate_permission(
                    actor.id,
                    peer_id,
                    PermissionType.TOOLS,
                    tool_name,
                    operation="invoke",
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
                                # Execute the action hook - check if it's async
                                if inspect.iscoroutinefunction(hook):
                                    result = await hook(actor, action_name, arguments)
                                else:
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

    async def _handle_prompt_get_async(
        self, request_id: Any, params: dict[str, Any], actor: Any
    ) -> dict[str, Any]:
        """Handle MCP prompts/get request asynchronously."""
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
            from ..runtime_context import RuntimeContext

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
                                # Execute the method hook - check if it's async
                                if inspect.iscoroutinefunction(hook):
                                    result = await hook(actor, method_name, arguments)
                                else:
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
                                logger.error(f"Error executing prompt {prompt_name}: {e}")
                                return self._create_jsonrpc_error(
                                    request_id,
                                    -32603,
                                    f"Prompt execution failed: {str(e)}",
                                )

        return self._create_jsonrpc_error(
            request_id, -32601, f"Prompt not found: {prompt_name}"
        )

    async def _handle_resource_read_async(
        self, request_id: Any, params: dict[str, Any], actor: Any
    ) -> dict[str, Any]:
        """Handle MCP resources/read request asynchronously."""
        uri = params.get("uri")

        if not uri:
            return self._create_jsonrpc_error(request_id, -32602, "Missing resource URI")

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
            from ..runtime_context import RuntimeContext

            runtime_context = RuntimeContext(actor)
            mcp_context = runtime_context.get_mcp_context()
            peer_id = mcp_context.peer_id if mcp_context else None
            if peer_id:
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
                        f"Access denied: You don't have permission to read resource '{uri}'",
                    )
        except Exception as e:
            logger.debug(f"Skipping resource permission check due to error: {e}")

        # Find the corresponding method hook and extract URI template variables
        from ..mcp.decorators import get_mcp_metadata, is_mcp_exposed

        # Import URI template matching logic
        try:
            # Reuse URI template matching from SDK server implementation
            from ..mcp.sdk_server import _match_uri_template

            for method_name, hooks in self.hooks._method_hooks.items():
                for hook in hooks:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "resource":
                            uri_template = metadata.get("uri")
                            if uri_template:
                                match_result = _match_uri_template(uri, uri_template)
                                if match_result:
                                    try:
                                        # Extract variables from URI
                                        uri_variables = match_result

                                        # Merge URI variables into arguments
                                        arguments = {**uri_variables}

                                        # Execute the method hook - check if it's async
                                        if inspect.iscoroutinefunction(hook):
                                            result = await hook(
                                                actor, method_name, arguments
                                            )
                                        else:
                                            result = hook(actor, method_name, arguments)

                                        # Check if result is already properly structured MCP content
                                        if isinstance(result, dict) and "contents" in result:
                                            # Result is already MCP-formatted, use it directly
                                            return {
                                                "jsonrpc": "2.0",
                                                "id": request_id,
                                                "result": result,
                                            }
                                        else:
                                            # Legacy handling: wrap in text content
                                            if isinstance(result, str):
                                                content_text = result
                                            elif isinstance(result, dict):
                                                content_text = str(
                                                    result.get("content", result)
                                                )
                                            else:
                                                content_text = str(result)

                                            return {
                                                "jsonrpc": "2.0",
                                                "id": request_id,
                                                "result": {
                                                    "contents": [
                                                        {
                                                            "uri": uri,
                                                            "mimeType": metadata.get(
                                                                "mimeType", "text/plain"
                                                            ),
                                                            "text": content_text,
                                                        }
                                                    ]
                                                },
                                            }
                                    except Exception as e:
                                        logger.error(
                                            f"Error executing resource read for {uri}: {e}"
                                        )
                                        return self._create_jsonrpc_error(
                                            request_id,
                                            -32603,
                                            f"Resource read failed: {str(e)}",
                                        )

        except ImportError:
            logger.warning("Failed to import URI template matching from SDK server")

        return self._create_jsonrpc_error(
            request_id, -32601, f"Resource not found: {uri}"
        )
