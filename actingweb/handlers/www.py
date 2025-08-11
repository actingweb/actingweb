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
        elif "properties/" in path:
            prop_name = path.split("/")[1]
            lookup = myself.property[prop_name] if prop_name and myself.property else None
            method_override = self.request.params.get("_method", None) if self.request.params else None
            if method_override and method_override.upper() == "DELETE":
                # Delete property
                if lookup and myself.property:
                    myself.property[prop_name] = None
                    # Execute property delete hook
                    if self.hooks:
                        actor_interface = self._get_actor_interface(myself)
                        if actor_interface:
                            self.hooks.execute_property_hooks(prop_name, "delete", actor_interface, None, [prop_name])

                    # Redirect back to properties page
                    self.response.set_status(302, "Found")
                    self.response.set_redirect(f"/{actor_id}/www/properties")
                    return
                else:
                    self.response.set_status(404, "Property not found")
                    return

            # Execute property hook for specific property
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    prop_path = [prop_name] if prop_name else []
                    hook_result = self.hooks.execute_property_hooks(
                        prop_name or "*", "get", actor_interface, lookup or {}, prop_path
                    )
                    if hook_result is not None:
                        lookup = hook_result
            if lookup:
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": lookup,
                    "qual": "a",
                    "url": f"/{actor_id}/",
                }
            else:
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": "",
                    "qual": "n",
                    "url": f"/{actor_id}/",
                }
            return
        if path == "trust":
            relationships = myself.get_trust_relationships()
            if not relationships:
                relationships = []
            for t in relationships:
                t["approveuri"] = (
                    self.config.root + (myself.id or "") + "/trust/" + (t.relationship or "") + "/" + (t.peerid or "")
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
                hook_result = self.hooks.execute_callback_hooks(
                    f"www_{path}", actor_interface, {"path": path, "method": "GET"}
                )
                if hook_result is not None:
                    output = str(hook_result) if not isinstance(hook_result, str) else hook_result
        if output:
            self.response.write(output)
        else:
            self.response.set_status(404, "Not found")
        return

    def post(self, actor_id, path):
        """Handle POST requests for web UI property operations."""
        (myself, check) = auth.init_actingweb(
            appreq=self, actor_id=actor_id, path="www", subpath=path, config=self.config
        )
        if not myself or not check or check.response["code"] != 200:
            return
        if not self.config.ui:
            if self.response:
                self.response.set_status(404, "Web interface is not enabled")
            return
        if not check.check_authorisation(path="www", subpath=path, method="POST"):
            self.response.write("")
            self.response.set_status(403)
            return

        if path == "properties":
            # Get form parameters
            property_name = self.request.get("property_name") or self.request.get("property")
            property_value = self.request.get("property_value") or self.request.get("value")

        elif "properties/" in path:
            property_name = path.split("/")[1]
            property_value = self.request.get("property_value") or self.request.get("value")
        else:
            property_name = None
            property_value = None
        # Handle property operations
        if property_name:
            try:
                # Handle different operations
                if property_value is not None:
                    # Create or update property
                    old_value = myself.property[property_name] if myself.property else None
                    is_new_property = old_value is None

                    # Set the property
                    if not myself.property:
                        self.response.set_status(500, "PropertyStore is not initialized")
                        return
                    myself.property[property_name] = property_value

                    # Execute property hooks
                    if self.hooks:
                        actor_interface = self._get_actor_interface(myself)
                        if actor_interface:
                            hook_action = "create" if is_new_property else "update"
                            self.hooks.execute_property_hooks(
                                property_name, hook_action, actor_interface, property_value, [property_name]
                            )

                    # Redirect back to properties page or init page
                    self.response.set_status(302, "Found")
                    redirect_path = self.request.get("redirect_to") or f"/{actor_id}/www/properties"
                    self.response.set_redirect(redirect_path)
                    return
                else:
                    self.response.set_status(400, "Property value is required")
                    return

            except Exception as e:
                self.response.set_status(500, f"Error processing property: {str(e)}")
                return

        # Handle other POST operations or custom web paths
        output = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_callback_hooks(
                    f"www_{path}", actor_interface, {"path": path, "method": "POST"}
                )
                if hook_result is not None:
                    output = str(hook_result) if not isinstance(hook_result, str) else hook_result

        if output:
            self.response.write(output)
        else:
            self.response.set_status(404, "Not found")
        return
