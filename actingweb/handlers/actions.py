"""
Handler for ActingWeb actions endpoint.

Actions are trigger-based functions that execute external events or operations.
GET returns action status, PUT/POST executes the action.
"""

import json
import logging
from typing import Any, Dict, Optional, Union

from actingweb import auth
from actingweb.handlers import base_handler


class ActionsHandler(base_handler.BaseHandler):
    """Handler for /<actor_id>/actions endpoint."""

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
            
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="actions",
            add_response=False,
            config=self.config,
        )
        if not myself or not check or (
            check.response["code"] != 200 and check.response["code"] != 401
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path="actions", subpath=name, method="GET"):
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
                    result = self.hooks.execute_action_hooks(name, actor_interface, {"method": "GET"})
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
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="actions",
            add_response=False,
            config=self.config,
        )
        if not myself or not check or (
            check.response["code"] != 200 and check.response["code"] != 401
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path="actions", subpath=name, method="POST"):
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
            
        # Execute action hook
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                result = self.hooks.execute_action_hooks(name, actor_interface, params)
        
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
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="actions",
            add_response=False,
            config=self.config,
        )
        if not myself or not check or (
            check.response["code"] != 200 and check.response["code"] != 401
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path="actions", subpath=name, method="PUT"):
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
            
        # Execute action hook (PUT treated same as POST)
        result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                result = self.hooks.execute_action_hooks(name, actor_interface, params)
        
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
        (myself, check) = auth.init_actingweb(
            appreq=self, actor_id=actor_id, path="actions", config=self.config
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(path="actions", subpath=name, method="DELETE"):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
            
        # Execute action deletion hook
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_action_hooks(name, actor_interface, {"method": "DELETE"})
                result = bool(hook_result)
        
        if result:
            if self.response:
                self.response.set_status(204, "Deleted")
        else:
            if self.response:
                self.response.set_status(403, "Forbidden")