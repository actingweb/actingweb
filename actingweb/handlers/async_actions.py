"""
Async-capable handler for ActingWeb actions endpoint.

This handler provides async versions of HTTP methods for optimal performance
with FastAPI and other async frameworks. It properly awaits async hooks
without thread pool overhead.
"""

import json
import logging

from actingweb import auth
from actingweb.handlers.actions import ActionsHandler

logger = logging.getLogger(__name__)


class AsyncActionsHandler(ActionsHandler):
    """Async-capable actions handler for FastAPI integration.

    Provides async versions of HTTP methods that properly await async hooks.
    Use this handler with FastAPI for optimal async performance.

    Inherits all synchronous methods from ActionsHandler for backward compatibility.
    """

    async def get_async(self, actor_id: str, name: str = "") -> None:
        """
        Handle GET requests to actions endpoint asynchronously.

        GET /actions - List available actions
        GET /actions/action_name - Get action status
        """
        if self.request.get("_method") == "PUT":
            await self.put_async(actor_id, name)
            return
        if self.request.get("_method") == "POST":
            await self.post_async(actor_id, name)
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
                    # Return list of available actions with metadata
                    result = {"actions": self.hooks.get_action_metadata_list()}
                else:
                    auth_context = self._create_auth_context(check)
                    # Use async hook execution
                    result = await self.hooks.execute_action_hooks_async(
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
        Handle POST requests to actions endpoint asynchronously.

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

        # Execute action hook asynchronously
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                auth_context = self._create_auth_context(check)
                # Use async hook execution
                result = await self.hooks.execute_action_hooks_async(
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
        """
        Handle PUT requests to actions endpoint asynchronously.

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

        # Execute action hook asynchronously (PUT treated same as POST)
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                auth_context = self._create_auth_context(check)
                # Use async hook execution
                result = await self.hooks.execute_action_hooks_async(
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

    async def delete_async(self, actor_id: str, name: str = "") -> None:
        """
        Handle DELETE requests to actions endpoint asynchronously.

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

        # Execute action deletion hook asynchronously
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                auth_context = self._create_auth_context(check)
                hook_result = await self.hooks.execute_action_hooks_async(
                    name, actor_interface, {"method": "DELETE"}, auth_context
                )
                result = bool(hook_result)

        if result:
            if self.response:
                self.response.set_status(204, "Deleted")
        else:
            if self.response:
                self.response.set_status(403, "Forbidden")
