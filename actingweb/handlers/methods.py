"""
Handler for ActingWeb methods endpoint.

Methods are RPC-style functions that actors can expose. They support JSON-RPC
protocol for structured method calls.
"""

import json
import logging
from typing import Any, Dict, Optional, Union

from actingweb import auth
from actingweb.handlers import base_handler


class MethodsHandler(base_handler.BaseHandler):
    """Handler for /<actor_id>/methods endpoint."""

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
            
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="methods",
            add_response=False,
            config=self.config,
        )
        if not myself or not check or (
            check.response["code"] != 200 and check.response["code"] != 401
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path="methods", subpath=name, method="GET"):
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
                    result = self.hooks.execute_method_hooks(name, actor_interface, {"method": "GET"})
        
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
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="methods",
            add_response=False,
            config=self.config,
        )
        if not myself or not check or (
            check.response["code"] != 200 and check.response["code"] != 401
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path="methods", subpath=name, method="POST"):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
            
        # Parse request body
        try:
            body: Union[str, bytes, None] = self.request.body
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
            result = self._handle_jsonrpc_request(params, name, myself)
        else:
            # Handle regular method call
            result = None
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    result = self.hooks.execute_method_hooks(name, actor_interface, params)
            
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
        (myself, check) = auth.init_actingweb(
            appreq=self, actor_id=actor_id, path="methods", config=self.config
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(path="methods", subpath=name, method="DELETE"):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
            
        # Execute method delete hook
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_method_hooks(name, actor_interface, {"method": "DELETE"})
                result = hook_result is not None
        
        if result:
            if self.response:
                self.response.set_status(204, "Deleted")
        else:
            if self.response:
                self.response.set_status(403, "Forbidden")

    def _handle_jsonrpc_request(self, params: Dict[str, Any], method_name: str, myself) -> Optional[Dict[str, Any]]:
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
                    "data": "Missing method"
                },
                "id": params.get("id")
            }
            
        # If method name is in URL, it should match the JSON-RPC method
        if method_name and method_name != params["method"]:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32600,
                    "message": "Invalid Request",
                    "data": "Method name mismatch"
                },
                "id": params.get("id")
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
                    result = self.hooks.execute_method_hooks(params["method"], actor_interface, method_params)
            
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
                    "error": {
                        "code": -32601,
                        "message": "Method not found"
                    },
                    "id": params.get("id")
                }
        except Exception as e:
            logging.error(f"Error executing method {params['method']}: {e}")
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e)
                },
                "id": params.get("id")
            }