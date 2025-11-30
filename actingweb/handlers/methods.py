"""
Handler for ActingWeb methods endpoint.

Methods are RPC-style functions that actors can expose. They support JSON-RPC
protocol for structured method calls.
"""

import json
import logging
from typing import Any

from actingweb import auth
from actingweb.handlers import base_handler

from ..permission_evaluator import (
    PermissionResult,
    get_permission_evaluator,
)


class MethodsHandler(base_handler.BaseHandler):
    """Handler for /<actor_id>/methods endpoint."""

    def _check_method_permission(
        self, actor_id: str, auth_obj, method_name: str
    ) -> bool:
        """
        Check method permission using the unified access control system.

        Args:
            actor_id: The actor ID
            auth_obj: Auth object from authentication
            method_name: Method name to check access for

        Returns:
            True if access is allowed, False otherwise
        """
        # Get peer ID from auth object (if authenticated via trust relationship)
        # Note: auth_obj.acl is a dict, not an object, so we use .get()
        peer_id = auth_obj.acl.get("peerid", "") if hasattr(auth_obj, "acl") else ""

        if not peer_id:
            # No peer relationship - fall back to legacy authorization for basic/oauth auth
            return auth_obj.check_authorisation(
                path="methods", subpath=method_name, method="GET"
            )

        # Use permission evaluator for peer-based access
        try:
            evaluator = get_permission_evaluator(self.config)
            result = evaluator.evaluate_method_access(actor_id, peer_id, method_name)

            if result == PermissionResult.ALLOWED:
                return True
            elif result == PermissionResult.DENIED:
                logging.info(
                    f"Method access denied: {actor_id} -> {peer_id} -> {method_name}"
                )
                return False
            else:  # NOT_FOUND
                # No specific permission rule - fall back to legacy for backward compatibility
                return auth_obj.check_authorisation(
                    path="methods", subpath=method_name, method="GET"
                )

        except Exception as e:
            logging.error(
                f"Error in method permission evaluation for {actor_id}:{peer_id}:{method_name}: {e}"
            )
            # Fall back to legacy authorization on errors
            return auth_obj.check_authorisation(
                path="methods", subpath=method_name, method="GET"
            )

    def _create_auth_context(self, auth_obj) -> dict[str, Any]:
        """Create auth context for hook execution with peer information."""
        # Note: auth_obj.acl is a dict, not an object, so we use .get()
        peer_id = auth_obj.acl.get("peerid", "") if hasattr(auth_obj, "acl") else ""
        return {"peer_id": peer_id, "config": self.config}

    def get(self, actor_id: str, name: str = "") -> None:
        """
        Handle GET requests to methods endpoint.

        GET /methods - List available methods
        GET /methods/method_name - Get method info/schema
        """
        if self.request.get("_method") == "PUT":
            self.put(actor_id, name)
            return
        if self.request.get("_method") == "POST":
            self.post(actor_id, name)
            return

        auth_result = self.authenticate_actor(
            actor_id, "methods", subpath=name, add_response=False
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
                    # Return list of available methods
                    result = {"methods": list(self.hooks._method_hooks.keys())}
                else:
                    auth_context = self._create_auth_context(check)
                    result = self.hooks.execute_method_hooks(
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

    def post(self, actor_id: str, name: str = "") -> None:
        """
        Handle POST requests to methods endpoint.

        POST /methods/method_name - Execute method with JSON-RPC support
        """
        auth_result = self.authenticate_actor(
            actor_id, "methods", subpath=name, add_response=False
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
            # Handle JSON-RPC request
            result = self._handle_jsonrpc_request(params, name, myself, check)
        else:
            # Handle regular method call
            result = None
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    auth_context = self._create_auth_context(check)
                    result = self.hooks.execute_method_hooks(
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

    def put(self, actor_id: str, name: str = "") -> None:
        """PUT requests are handled as POST for methods."""
        self.post(actor_id, name)

    def delete(self, actor_id: str, name: str = "") -> None:
        """
        Handle DELETE requests to methods endpoint.

        DELETE /methods/method_name - Remove method (if supported)
        """
        auth_result = self.authenticate_actor(actor_id, "methods", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        if not auth_result.authorize("DELETE", "methods", name):
            return

        # Execute method delete hook
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                auth_context = self._create_auth_context(check)
                hook_result = self.hooks.execute_method_hooks(
                    name, actor_interface, {"method": "DELETE"}, auth_context
                )
                result = hook_result is not None

        if result:
            if self.response:
                self.response.set_status(204, "Deleted")
        else:
            if self.response:
                self.response.set_status(403, "Forbidden")

    def _handle_jsonrpc_request(
        self, params: dict[str, Any], method_name: str, myself, auth_obj
    ) -> dict[str, Any] | None:
        """
        Handle JSON-RPC 2.0 request.

        Args:
            params: Parsed JSON-RPC request
            method_name: Method name from URL path

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

        # Call the method hook
        try:
            # Execute method hook
            result = None
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    auth_context = self._create_auth_context(auth_obj)
                    result = self.hooks.execute_method_hooks(
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
            logging.error(f"Error executing method {params['method']}: {e}")
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Internal error", "data": str(e)},
                "id": params.get("id"),
            }
