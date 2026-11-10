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

from ..access_decision import listable_names, named_route_allows, peer_of
from ..db.exceptions import DbError
from ..permission_evaluator import PermissionType, get_permission_evaluator

logger = logging.getLogger(__name__)


class MethodsHandler(base_handler.BaseHandler):
    """Handler for /<actor_id>/methods endpoint."""

    def _check_method_permission(
        self, actor_id: str, auth_obj: Any, method_name: str, method: str = "POST"
    ) -> bool:
        """The shared access decision for a peer's ``/methods`` request
        with the request's ``method`` (3.16): a rule the grant states (even
        empty) answers, else the access table; an evaluator that cannot be
        built denies. A caller that is not a peer is answered by the access
        table, as before."""
        method = getattr(self, "_verb_override", None) or method
        # The verb the hooks this request runs are decided with (3.16).
        self._request_method = method
        return named_route_allows(
            self.config,
            actor_id,
            auth_obj,
            PermissionType.METHODS,
            method_name,
            method=method,
            get_evaluator=get_permission_evaluator,
        )

    def _listable_methods(self, actor_id: str, auth_obj: Any) -> list[Any]:
        """The methods a listing shows: all for a caller that is not a peer;
        for a peer, each decided as a call of it would be (3.16), none when
        the grant cannot be read (it showed all)."""
        assert self.hooks is not None
        entries = self.hooks.get_method_metadata_list()
        allowed = listable_names(
            self.config,
            actor_id,
            auth_obj,
            PermissionType.METHODS,
            [str(e.get("name", "")) for e in entries],
            get_evaluator=get_permission_evaluator,
        )
        if allowed is None:
            return entries
        return [e for e in entries if str(e.get("name", "")) in allowed]

    def _create_auth_context(self, auth_obj: Any) -> dict[str, Any]:
        """Create auth context for hook execution with peer information."""
        peer_id = peer_of(auth_obj)
        return {
            "peer_id": peer_id,
            "config": self.config,
            "method": getattr(self, "_request_method", None),
        }

    def get(self, actor_id: str, name: str = "") -> None:
        """
        Handle GET requests to methods endpoint.

        GET /methods - List available methods
        GET /methods/method_name - Get method info/schema
        """
        # A GET with a _method override changes state: refuse one a
        # page on another site started (see BaseHandler).
        if self._refuse_cross_site_override():
            return
        if self.request.get("_method") == "PUT":
            self.put(actor_id, name)
            return
        if self.request.get("_method") == "POST":
            self.post(actor_id, name)
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
        if not self._check_method_permission(actor_id, check, name, "GET"):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        # Execute method hook to get method info
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                if not name:
                    # Return list of available methods with metadata, filtered by permissions
                    result = {"methods": self._listable_methods(actor_id, check)}
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
        if not self._check_method_permission(actor_id, check, name, "POST"):
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
        """PUT requests are handled as POST for methods (decided as PUT)."""
        self._verb_override = "PUT"
        try:
            self.post(actor_id, name)
        finally:
            self._verb_override = None

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
        # A peer is decided by its grant as well (3.16; DELETE was the one
        # method verb the grant did not answer).
        if not self._check_method_permission(actor_id, check, name, "DELETE"):
            if self.response:
                self.response.set_status(403, "Forbidden")
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

        # On the bare /methods the URL named nothing to check: the method the
        # body names is decided before it is dispatched (3.16).
        if not method_name and not self._check_method_permission(
            str(getattr(myself, "id", "") or ""),
            auth_obj,
            str(params["method"]),
            "POST",
        ):
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": "Forbidden"},
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
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error executing method {params['method']}: {e}")
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Internal error", "data": str(e)},
                "id": params.get("id"),
            }
