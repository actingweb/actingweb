import json
import logging
from builtins import str

from actingweb import actor
from actingweb.handlers import base_handler


class RootFactoryHandler(base_handler.BaseHandler):

    def get(self):
        if self.request.get("_method") == "POST":
            self.post()
            return
        if self.config.ui:
            self.response.template_values = {}
        else:
            self.response.set_status(404)

    def post(self):
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = "{}"
            params = json.loads(body)
            is_json = True
            if "creator" in params:
                creator = params["creator"]
            else:
                creator = ""
            if "trustee_root" in params:
                trustee_root = params["trustee_root"]
            else:
                trustee_root = ""
            if "passphrase" in params:
                passphrase = params["passphrase"]
            else:
                passphrase = ""
        except ValueError:
            is_json = False
            creator = self.request.get("creator")
            trustee_root = self.request.get("trustee_root")
            passphrase = self.request.get("passphrase")
            
        # Create actor using direct method
        myself = actor.Actor(config=self.config)
        if not myself.create(
            url=self.request.url or "", creator=creator, passphrase=passphrase
        ):
            self.response.set_status(400, "Not created")
            logging.warning(
                "Was not able to create new Actor("
                + str(self.request.url)
                + " "
                + str(creator)
                + ")"
            )
            return
        
        # Execute actor_created lifecycle hook if hooks are available
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                self.hooks.execute_lifecycle_hooks("actor_created", actor_interface)
        
        if len(trustee_root) > 0 and myself.store:
            myself.store.trustee_root = trustee_root
        self.response.headers["Location"] = str(self.config.root + (myself.id or ""))
        if self.config.www_auth == "oauth" and not is_json:
            self.response.set_redirect(self.config.root + (myself.id or "") + "/www")
            return
        pair = {
            "id": myself.id,
            "creator": myself.creator,
            "passphrase": str(myself.passphrase),
        }
        if len(trustee_root) > 0:
            pair["trustee_root"] = trustee_root
        if self.config.ui and not is_json:
            self.response.template_values = pair
            return
        out = json.dumps(pair)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        self.response.set_status(201, "Created")
