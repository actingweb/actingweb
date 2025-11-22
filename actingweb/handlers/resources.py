# Fixed imports after removing init_actingweb
import json

from actingweb.handlers import base_handler


class ResourcesHandler(base_handler.BaseHandler):
    def get(self, actor_id, name):
        auth_result = self._authenticate_dual_context(
            actor_id, "resources", "resources", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not auth_result.authorize("GET", "resources", name):
            return
        # Execute callback hook for resource GET
        pair = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                pair = self.hooks.execute_callback_hooks(
                    f"resource_{name}", actor_interface, {"method": "GET"}
                )
        if pair:
            out = json.dumps(pair)
            if self.response:
                self.response.write(out)
                self.response.headers["Content-Type"] = "application/json"
                self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def delete(self, actor_id, name):
        auth_result = self._authenticate_dual_context(
            actor_id, "resources", "resources", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not auth_result.authorize("DELETE", "resources", name):
            return
        # Execute callback hook for resource DELETE
        pair = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                pair = self.hooks.execute_callback_hooks(
                    f"resource_{name}", actor_interface, {"method": "DELETE"}
                )
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if pair:
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def put(self, actor_id, name):
        auth_result = self._authenticate_dual_context(
            actor_id, "resources", "resources", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not auth_result.authorize("PUT", "resources", name):
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
            if self.response:
                self.response.set_status(400, "Error in json body")
            return

        # Execute callback hook for resource PUT
        pair = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                data = params.copy()
                data["method"] = "PUT"
                pair = self.hooks.execute_callback_hooks(
                    f"resource_{name}", actor_interface, data
                )
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if pair:
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(200)
        else:
            if self.response:
                self.response.set_status(404)

    def post(self, actor_id, name):
        auth_result = self._authenticate_dual_context(
            actor_id, "resources", "resources", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        if not auth_result.authorize("POST", "resources", name):
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
            if self.response:
                self.response.set_status(400, "Error in json body")
            return

        # Execute callback hook for resource POST
        pair = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                data = params.copy()
                data["method"] = "POST"
                pair = self.hooks.execute_callback_hooks(
                    f"resource_{name}", actor_interface, data
                )
        if pair:
            if isinstance(pair, int) and 100 <= pair <= 999:
                return
            if pair:
                out = json.dumps(pair)
                if self.response:
                    self.response.write(out)
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(201, "Created")
        else:
            if self.response:
                self.response.set_status(404)
