import json
import logging

from actingweb import auth
from actingweb.handlers import base_handler


class CallbacksHandler(base_handler.BaseHandler):
    def get(self, actor_id, name):
        """Handles GETs to callbacks"""
        if self.request.get("_method") == "PUT":
            self.put(actor_id, name)
        if self.request.get("_method") == "POST":
            self.post(actor_id, name)
        auth_result = self._authenticate_dual_context(
            actor_id, "callbacks", "callbacks", name, add_response=False
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
        if not auth_result.authorize("GET", "callbacks", name):
            return
        # Execute callback hook for GET
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_callback_hooks(
                    name, actor_interface, {"method": "GET"}
                )
                result = bool(hook_result) if hook_result is not None else False

        if not result:
            self.response.set_status(403, "Forbidden")

    def put(self, actor_id, name):
        """PUT requests are handled as POST for callbacks"""
        self.post(actor_id, name)

    def delete(self, actor_id, name):
        """Handles deletion of callbacks, like subscriptions"""
        auth_result = self._authenticate_dual_context(
            actor_id, "callbacks", "callbacks", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
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

            # Use developer API to delete callback subscription
            actor_interface = self._get_actor_interface(myself)
            if not actor_interface:
                if self.response:
                    self.response.set_status(500, "Internal error")
                return

            if actor_interface.subscriptions.delete_callback_subscription(
                peer_id=peerid, subscription_id=subid
            ):
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
                hook_result = self.hooks.execute_callback_hooks(
                    name, actor_interface, {"method": "DELETE"}
                )
                result = bool(hook_result) if hook_result is not None else False

        if not result:
            self.response.set_status(403, "Forbidden")

    def post(self, actor_id, name):
        """Handles POST callbacks"""
        auth_result = self._authenticate_dual_context(
            actor_id, "callbacks", "callbacks", name, add_response=False
        )
        myself = auth_result.actor
        check = auth_result.auth_obj
        # Allow unauthenticated requests to /callbacks/subscriptions, so
        # do the auth check further below
        path = name.split("/")
        if path[0] == "subscriptions":
            peerid = path[1]
            subid = path[2]

            # Use developer API to get callback subscription
            actor_interface = self._get_actor_interface(myself) if myself else None
            if not actor_interface:
                self.response.set_status(404, "Not found")
                return

            sub_info = actor_interface.subscriptions.get_callback_subscription(
                peer_id=peerid, subscription_id=subid
            )
            if sub_info:
                # Convert to dict for hook compatibility
                sub = sub_info.to_dict()
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
                    body: str | bytes | None = self.request.body
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
                    hook_data = params.copy()
                    hook_data.update({"subscription": sub, "peerid": peerid})
                    hook_result = self.hooks.execute_callback_hooks(
                        "subscription", actor_interface, hook_data
                    )
                    result = bool(hook_result) if hook_result is not None else False

                if result:
                    self.response.set_status(204, "Found")
                else:
                    self.response.set_status(400, "Processing error")
                return
            self.response.set_status(404, "Not found")
            return
        if (
            not myself
            or not check
            or (check.response["code"] != 200 and check.response["code"] != 401)
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not auth_result.authorize("POST", "callbacks", name):
            return
        # Execute callback hook for POST
        result = False
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                # Parse request body for hook data
                try:
                    body: str | bytes | None = self.request.body
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
                hook_result = self.hooks.execute_callback_hooks(
                    name, actor_interface, hook_data
                )
                result = bool(hook_result) if hook_result is not None else False

        if not result:
            self.response.set_status(403, "Forbidden")
