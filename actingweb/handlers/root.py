import json
from typing import Any, Optional

from actingweb import auth
from actingweb.handlers import base_handler


class RootHandler(base_handler.BaseHandler):

    def get(self, actor_id):
        if self.request.get("_method") == "DELETE":
            self.delete(actor_id)
            return
        (myself, check) = auth.init_actingweb(
            appreq=self, actor_id=actor_id, path="", subpath="", config=self.config
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(path="/", method="GET"):
            if self.response:
                self.response.set_status(403)
            return
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
        (myself, check) = auth.init_actingweb(
            appreq=self, actor_id=actor_id, path="", subpath="", config=self.config
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not check.check_authorisation(path="/", method="DELETE"):
            if self.response:
                self.response.set_status(403)
            return
        # Execute actor deletion lifecycle hook
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                self.hooks.execute_lifecycle_hooks("actor_deleted", actor_interface)
                
        myself.delete()
        self.response.set_status(204)
        return
