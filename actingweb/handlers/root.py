import json

from actingweb.handlers import base_handler


class RootHandler(base_handler.BaseHandler):
    def get(self, actor_id):
        if self.request.get("_method") == "DELETE":
            self.delete(actor_id)
            return
        # Authenticate and authorize separately like DELETE method
        auth_result = self.authenticate_actor(actor_id, "")
        if not auth_result.success:
            return  # Response already set
        if not auth_result.authorize("GET", "/"):
            return  # Response already set
        myself = auth_result.actor
        pair = {
            "id": myself.id,
            "creator": myself.creator,
            "passphrase": myself.passphrase,
        }
        trustee_root = myself.store.trustee_root if myself.store else None
        if trustee_root and len(trustee_root) > 0:
            pair["trustee_root"] = trustee_root
        out = json.dumps(pair)
        if self.response:
            self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(200)

    def delete(self, actor_id):
        # Alternative: more control with AuthResult
        auth_result = self.authenticate_actor(actor_id, "")
        if not auth_result.success:
            return  # Response already set
        if not auth_result.authorize("DELETE", "/"):
            return  # Response already set
        myself = auth_result.actor
        # Execute actor deletion lifecycle hook
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                self.hooks.execute_lifecycle_hooks("actor_deleted", actor_interface)

        myself.delete()
        self.response.set_status(204)
        return
