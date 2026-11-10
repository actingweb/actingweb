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

from ..access_decision import listable_names, named_route_allows, peer_of
from ..permission_evaluator import PermissionType, get_permission_evaluator

logger = logging.getLogger(__name__)


class ActionsHandler(base_handler.BaseHandler):
    """Handler for /<actor_id>/actions endpoint."""

    def _check_action_permission(
        self, actor_id: str, auth_obj: Any, action_name: str, method: str = "POST"
    ) -> bool:
        """The shared access decision for a peer's ``/actions`` request
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
            PermissionType.ACTIONS,
            action_name,
            method=method,
            get_evaluator=get_permission_evaluator,
        )

    def _listable_actions(self, actor_id: str, auth_obj: Any) -> list[Any]:
        """The actions a listing shows: all for a caller that is not a peer;
        for a peer, each decided as a call of it would be (3.16), none when
        the grant cannot be read (it showed all)."""
        assert self.hooks is not None
        entries = self.hooks.get_action_metadata_list()
        allowed = listable_names(
            self.config,
            actor_id,
            auth_obj,
            PermissionType.ACTIONS,
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
        Handle GET requests to actions endpoint.

        GET /actions - List available actions
        GET /actions/action_name - Get action status
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
            actor_id, "actions", "actions", name=name, add_response=False
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
        if not self._check_action_permission(actor_id, check, name, "GET"):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        # Execute action hook to get action info/status
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                if not name:
                    # Return list of available actions with metadata, filtered by permissions
                    result = {"actions": self._listable_actions(actor_id, check)}
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
        # Use dual-context auth to support both web UI (OAuth cookie) and API (basic auth)
        auth_result = self._authenticate_dual_context(
            actor_id, "actions", "actions", name=name, add_response=False
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
        if not self._check_action_permission(actor_id, check, name, "POST"):
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
        # Use dual-context auth to support both web UI (OAuth cookie) and API (basic auth)
        auth_result = self._authenticate_dual_context(
            actor_id, "actions", "actions", name=name, add_response=False
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
        if not self._check_action_permission(actor_id, check, name, "PUT"):
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
        if not self._check_action_permission(actor_id, check, name, "DELETE"):
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
