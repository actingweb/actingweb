from typing import Any, Dict, Optional

from actingweb import auth
from actingweb.handlers import base_handler


class WwwHandler(base_handler.BaseHandler):

    def get(self, actor_id, path):
        (myself, check) = auth.init_actingweb(
            appreq=self, actor_id=actor_id, path="www", subpath=path, config=self.config
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not self.config.ui:
            if self.response:
                self.response.set_status(404, "Web interface is not enabled")
            return
        if not check.check_authorisation(path="www", subpath=path, method="GET"):
            self.response.write("")
            self.response.set_status(403)
            return

        if not path or path == "":
            self.response.template_values = {
                "url": self.request.url,
                "id": actor_id,
                "creator": myself.creator,
                "passphrase": myself.passphrase,
            }
            return

        if path == "init":
            self.response.template_values = {
                "id": myself.id,
            }
            return
        if path == "properties":
            properties = myself.get_properties()
            # Execute property hook for web interface
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    hook_result = self.hooks.execute_property_hooks("*", "get", actor_interface, properties, [])
                    if hook_result is not None:
                        properties = hook_result
            self.response.template_values = {
                "id": myself.id,
                "properties": properties,
            }
            return
        if path == "property":
            prop_name = self.request.get("name")
            lookup = myself.property[prop_name] if prop_name and myself.property else None
            # Execute property hook for specific property
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    prop_path = [prop_name] if prop_name else []
                    hook_result = self.hooks.execute_property_hooks(prop_name or "*", "get", actor_interface, lookup or {}, prop_path)
                    if hook_result is not None:
                        lookup = hook_result
            if lookup:
                self.response.template_values = {
                    "id": myself.id,
                    "property": self.request.get("name"),
                    "value": lookup,
                    "qual": "",
                }
            else:
                self.response.template_values = {
                    "id": myself.id,
                    "property": self.request.get("name"),
                    "value": "Not set",
                    "qual": "no",
                }
            return
        if path == "trust":
            relationships = myself.get_trust_relationships()
            if not relationships or len(relationships) == 0:
                self.response.set_status(404, "Not found")
                return
            for t in relationships:
                t["approveuri"] = (
                    self.config.root
                    + (myself.id or "")
                    + "/trust/"
                    + (t.relationship or "")
                    + "/"
                    + (t.peerid or "")
                )
                self.response.template_values = {
                    "id": myself.id,
                    "trusts": relationships,
                }
            return
        # Execute callback hook for custom web paths
        output = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_callback_hooks(f"www_{path}", actor_interface, {"path": path, "method": "GET"})
                if hook_result is not None:
                    output = str(hook_result) if not isinstance(hook_result, str) else hook_result
        if output:
            self.response.write(output)
        else:
            self.response.set_status(404, "Not found")
        return
