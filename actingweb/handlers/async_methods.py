"""
Async-capable handler for ActingWeb methods endpoint.

This handler provides async versions of HTTP methods for optimal performance
with FastAPI and other async frameworks. It properly awaits async hooks
without thread pool overhead.
"""

import json
import logging
from typing import Any

from actingweb import auth
from actingweb.handlers.methods import MethodsHandler

logger = logging.getLogger(__name__)


class AsyncMethodsHandler(MethodsHandler):
    """Async-capable methods handler for FastAPI integration.

    Provides async versions of HTTP methods that properly await async hooks.
    Use this handler with FastAPI for optimal async performance.

    Inherits all synchronous methods from MethodsHandler for backward compatibility.
    """

    async def get_async(self, actor_id: str, name: str = "") -> None:
        """
        Handle GET requests to methods endpoint asynchronously.

        GET /methods - List available methods
        GET /methods/method_name - Get method info/schema
        """
        if self.request.get("_method") == "PUT":
            await self.put_async(actor_id, name)
            return
        if self.request.get("_method") == "POST":
            await self.post_async(actor_id, name)
            return

        # Use dual-context auth to support both web UI (OAuth cookie) and API (basic auth)
        auth_result = self._authenticate_dual_context(
            actor_id, "methods", "methods", name=name, add_response=False
        )
        if (
            not auth_result.actor
            or not auth_result.auth_obj
            or (
                auth_result.auth_obj.response["code"] != 200
                and auth_result.auth_obj.response["code"] != 401
            )
        ):
            auth.add_auth_response(appreq=self, auth_obj=auth_result.auth_obj)
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        # Use unified access control system for permission checking
        if not self._check_method_permission(actor_id, check, name):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        # Execute method hook to get method info
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                if not name:
                    # Return list of available methods with metadata
                    result = {"methods": self.hooks.get_method_metadata_list()}
                else:
                    auth_context = self._create_auth_context(check)
                    # Use async hook execution
                    result = await self.hooks.execute_method_hooks_async(
                        name, actor_interface, {"method": "GET"}, auth_context
                    )

        if result is not None:
            if self.response:
                self.response.set_status(200, "OK")
                self.response.headers["Content-Type"] = "application/json"
                self.response.write(json.dumps(result))
        else:
            if self.response:
                self.response.set_status(404, "Not found")

    async def post_async(self, actor_id: str, name: str = "") -> None:
        """
        Handle POST requests to methods endpoint asynchronously.

        POST /methods/method_name - Execute method with JSON-RPC support
        """
        # Use dual-context auth to support both web UI (OAuth cookie) and API (basic auth)
        auth_result = self._authenticate_dual_context(
            actor_id, "methods", "methods", name=name, add_response=False
        )
        if (
            not auth_result.actor
            or not auth_result.auth_obj
            or (
                auth_result.auth_obj.response["code"] != 200
                and auth_result.auth_obj.response["code"] != 401
            )
        ):
            auth.add_auth_response(appreq=self, auth_obj=auth_result.auth_obj)
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        # Use unified access control system for permission checking
        if not self._check_method_permission(actor_id, check, name):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        # Parse request body
        try:
            body: str | bytes | None = self.request.body
            if body is None:
                body_str = "{}"
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = body
            params = json.loads(body_str)
        except (TypeError, ValueError, KeyError):
            if self.response:
                self.response.set_status(400, "Error in json body")
            return

        # Check if this is a JSON-RPC request
        is_jsonrpc = "jsonrpc" in params and params["jsonrpc"] == "2.0"

        if is_jsonrpc:
            # Handle JSON-RPC request asynchronously
            result = await self._handle_jsonrpc_request_async(
                params, name, myself, check
            )
        else:
            # Handle regular method call asynchronously
            result = None
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    auth_context = self._create_auth_context(check)
                    # Use async hook execution
                    result = await self.hooks.execute_method_hooks_async(
                        name, actor_interface, params, auth_context
                    )

        if result is not None:
            if self.response:
                self.response.set_status(200, "OK")
                self.response.headers["Content-Type"] = "application/json"
                self.response.write(json.dumps(result))
        else:
            if self.response:
                self.response.set_status(400, "Processing error")

    async def put_async(self, actor_id: str, name: str = "") -> None:
        """PUT requests are handled as POST for methods (async variant)."""
        await self.post_async(actor_id, name)

    async def delete_async(self, actor_id: str, name: str = "") -> None:
        """
        Handle DELETE requests to methods endpoint asynchronously.

        DELETE /methods/method_name - Remove method (if supported)
        """
        auth_result = self.authenticate_actor(actor_id, "methods", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        if not auth_result.authorize("DELETE", "methods", name):
            return

        # Execute method delete hook asynchronously
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                auth_context = self._create_auth_context(check)
                hook_result = await self.hooks.execute_method_hooks_async(
                    name, actor_interface, {"method": "DELETE"}, auth_context
                )
                result = hook_result is not None

        if result:
            if self.response:
                self.response.set_status(204, "Deleted")
        else:
            if self.response:
                self.response.set_status(403, "Forbidden")

    async def _handle_jsonrpc_request_async(
        self, params: dict[str, Any], method_name: str, myself: Any, auth_obj: Any
    ) -> dict[str, Any] | None:
        """
        Handle JSON-RPC 2.0 request asynchronously.

        Args:
            params: Parsed JSON-RPC request
            method_name: Method name from URL path
            myself: Actor instance
            auth_obj: Authentication object

        Returns:
            JSON-RPC response or None on error
        """
        # Validate JSON-RPC request
        if "method" not in params:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32600,
                    "message": "Invalid Request",
                    "data": "Missing method",
                },
                "id": params.get("id"),
            }

        # If method name is in URL, it should match the JSON-RPC method
        if method_name and method_name != params["method"]:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32600,
                    "message": "Invalid Request",
                    "data": "Method name mismatch",
                },
                "id": params.get("id"),
            }

        # Extract method parameters
        method_params = params.get("params", {})

        # Call the method hook asynchronously
        try:
            # Execute method hook
            result = None
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    auth_context = self._create_auth_context(auth_obj)
                    # Use async hook execution
                    result = await self.hooks.execute_method_hooks_async(
                        params["method"], actor_interface, method_params, auth_context
                    )

            if result is not None:
                # Success response
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                }
                if "id" in params:
                    response["id"] = params["id"]
                return response
            else:
                # Method not found or error
                return {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": "Method not found"},
                    "id": params.get("id"),
                }
        except Exception as e:
            logger.error(f"Error executing method {params['method']}: {e}")
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Internal error", "data": str(e)},
                "id": params.get("id"),
            }
