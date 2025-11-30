"""
Handler for ActingWeb actions endpoint.

Actions are trigger-based functions that execute external events or operations.
GET returns action status, PUT/POST executes the action.
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


class ActionsHandler(base_handler.BaseHandler):
    """Handler for /<actor_id>/actions endpoint."""

    def _check_action_permission(
        self, actor_id: str, auth_obj, action_name: str
    ) -> bool:
        """
        Check action permission using the unified access control system.

        Args:
            actor_id: The actor ID
            auth_obj: Auth object from authentication
            action_name: Action name to check access for

        Returns:
            True if access is allowed, False otherwise
        """
        # Get peer ID from auth object (if authenticated via trust relationship)
        # Note: auth_obj.acl is a dict, not an object, so we use .get()
        peer_id = auth_obj.acl.get("peerid", "") if hasattr(auth_obj, "acl") else ""

        if not peer_id:
            # No peer relationship - fall back to legacy authorization for basic/oauth auth
            return auth_obj.check_authorisation(
                path="actions", subpath=action_name, method="GET"
            )

        # Use permission evaluator for peer-based access
        try:
            evaluator = get_permission_evaluator(self.config)
            result = evaluator.evaluate_action_access(actor_id, peer_id, action_name)

            if result == PermissionResult.ALLOWED:
                return True
            elif result == PermissionResult.DENIED:
                logging.info(
                    f"Action access denied: {actor_id} -> {peer_id} -> {action_name}"
                )
                return False
            else:  # NOT_FOUND
                # No specific permission rule - fall back to legacy for backward compatibility
                return auth_obj.check_authorisation(
                    path="actions", subpath=action_name, method="GET"
                )

        except Exception as e:
            logging.error(
                f"Error in action permission evaluation for {actor_id}:{peer_id}:{action_name}: {e}"
            )
            # Fall back to legacy authorization on errors
            return auth_obj.check_authorisation(
                path="actions", subpath=action_name, method="GET"
            )

    def _create_auth_context(self, auth_obj) -> dict[str, Any]:
        """Create auth context for hook execution with peer information."""
        # Note: auth_obj.acl is a dict, not an object, so we use .get()
        peer_id = auth_obj.acl.get("peerid", "") if hasattr(auth_obj, "acl") else ""
        return {"peer_id": peer_id, "config": self.config}

    def get(self, actor_id: str, name: str = "") -> None:
        """
        Handle GET requests to actions endpoint.

        GET /actions - List available actions
        GET /actions/action_name - Get action status
        """
        if self.request.get("_method") == "PUT":
            self.put(actor_id, name)
            return
        if self.request.get("_method") == "POST":
            self.post(actor_id, name)
            return

        auth_result = self.authenticate_actor(
            actor_id, "actions", subpath=name, add_response=False
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
        if not self._check_action_permission(actor_id, check, name):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        # Execute action hook to get action info/status
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                if not name:
                    # Return list of available actions
                    result = {"actions": list(self.hooks._action_hooks.keys())}
                else:
                    auth_context = self._create_auth_context(check)
                    result = self.hooks.execute_action_hooks(
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
        Handle POST requests to actions endpoint.

        POST /actions/action_name - Execute action
        """
        auth_result = self.authenticate_actor(
            actor_id, "actions", subpath=name, add_response=False
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
        if not self._check_action_permission(actor_id, check, name):
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

        # Execute action hook
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                auth_context = self._create_auth_context(check)
                result = self.hooks.execute_action_hooks(
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
        """
        Handle PUT requests to actions endpoint.

        PUT /actions/action_name - Execute action (same as POST)
        """
        auth_result = self.authenticate_actor(
            actor_id, "actions", subpath=name, add_response=False
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
        if not self._check_action_permission(actor_id, check, name):
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

        # Execute action hook (PUT treated same as POST)
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                auth_context = self._create_auth_context(check)
                result = self.hooks.execute_action_hooks(
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

    def delete(self, actor_id: str, name: str = "") -> None:
        """
        Handle DELETE requests to actions endpoint.

        DELETE /actions/action_name - Remove action (if supported)
        """
        auth_result = self.authenticate_actor(actor_id, "actions", name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        # Use unified access control system for permission checking
        if not self._check_action_permission(actor_id, check, name):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        # Execute action deletion hook
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                auth_context = self._create_auth_context(check)
                hook_result = self.hooks.execute_action_hooks(
                    name, actor_interface, {"method": "DELETE"}, auth_context
                )
                result = bool(hook_result)

        if result:
            if self.response:
                self.response.set_status(204, "Deleted")
        else:
            if self.response:
                self.response.set_status(403, "Forbidden")
