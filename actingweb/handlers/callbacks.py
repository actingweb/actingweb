import json
import logging
from builtins import str
from typing import Any, Dict, Optional, Union

from actingweb import auth
from actingweb.handlers import base_handler


class CallbacksHandler(base_handler.BaseHandler):

    def get(self, actor_id, name):
        """Handles GETs to callbacks"""
        if self.request.get("_method") == "PUT":
            self.put(actor_id, name)
        if self.request.get("_method") == "POST":
            self.post(actor_id, name)
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="callbacks",
            add_response=False,
            config=self.config,
        )
        if not myself or not check or (
            check.response["code"] != 200 and check.response["code"] != 401
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path="callbacks", subpath=name, method="GET"):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
        # Execute callback hook for GET
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_callback_hooks(name, actor_interface, {"method": "GET"})
                result = bool(hook_result) if hook_result is not None else False
                
        if not result:
            self.response.set_status(403, "Forbidden")

    def put(self, actor_id, name):
        """PUT requests are handled as POST for callbacks"""
        self.post(actor_id, name)

    def delete(self, actor_id, name):
        """Handles deletion of callbacks, like subscriptions"""
        (myself, check) = auth.init_actingweb(
            appreq=self, actor_id=actor_id, path="callbacks", config=self.config
        )
        if not myself or not check or check.response["code"] != 200:
            return
        path = name.split("/")
        if path[0] == "subscriptions":
            peerid = path[1]
            subid = path[2]
            if not check.check_authorisation(
                path="callbacks",
                subpath="subscriptions",
                method="DELETE",
                peerid=peerid,
            ):
                if self.response:
                    self.response.set_status(403, "Forbidden")
                return
            sub = myself.get_subscription_obj(peerid=peerid, subid=subid, callback=True)
            if sub:
                sub.delete()
                self.response.set_status(204, "Deleted")
                return
            self.response.set_status(404, "Not found")
            return
        if not check.check_authorisation(
            path="callbacks", subpath=name, method="DELETE"
        ):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
        # Execute callback hook for DELETE
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_callback_hooks(name, actor_interface, {"method": "DELETE"})
                result = bool(hook_result) if hook_result is not None else False
                
        if not result:
            self.response.set_status(403, "Forbidden")

    def post(self, actor_id, name):
        """Handles POST callbacks"""
        (myself, check) = auth.init_actingweb(
            appreq=self,
            actor_id=actor_id,
            path="callbacks",
            add_response=False,
            config=self.config,
        )
        # Allow unauthenticated requests to /callbacks/subscriptions, so
        # do the auth check further below
        path = name.split("/")
        if path[0] == "subscriptions":
            peerid = path[1]
            subid = path[2]
            sub = myself.get_subscription(peerid=peerid, subid=subid, callback=True) if myself else None
            if sub and len(sub) > 0:
                logging.debug("Found subscription (" + str(sub) + ")")
                if not check or not check.check_authorisation(
                    path="callbacks",
                    subpath="subscriptions",
                    method="POST",
                    peerid=peerid,
                ):
                    if self.response:
                        self.response.set_status(403, "Forbidden")
                    return
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
                    self.response.set_status(400, "Error in json body")
                    return
                    
                # Execute subscription callback hook
                result = False
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        hook_data = params.copy()
                        hook_data.update({"subscription": sub, "peerid": peerid})
                        hook_result = self.hooks.execute_callback_hooks("subscription", actor_interface, hook_data)
                        result = bool(hook_result) if hook_result is not None else False
                        
                if result:
                    self.response.set_status(204, "Found")
                else:
                    self.response.set_status(400, "Processing error")
                return
            self.response.set_status(404, "Not found")
            return
        if not myself or not check or (
            check.response["code"] != 200 and check.response["code"] != 401
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not check.check_authorisation(path="callbacks", subpath=name, method="POST"):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
        # Execute callback hook for POST
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                # Parse request body for hook data
                try:
                    body: Union[str, bytes, None] = self.request.body
                    if body is None:
                        body_str = "{}"
                    elif isinstance(body, bytes):
                        body_str = body.decode("utf-8", "ignore")
                    else:
                        body_str = body
                    hook_data = json.loads(body_str)
                except (TypeError, ValueError, KeyError):
                    hook_data = {}
                    
                hook_data["method"] = "POST"
                hook_result = self.hooks.execute_callback_hooks(name, actor_interface, hook_data)
                result = bool(hook_result) if hook_result is not None else False
                
        if not result:
            self.response.set_status(403, "Forbidden")
