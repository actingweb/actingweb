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
            # Extract base path from request URL to handle base paths like /mcp-server
            # The request URL might be like: https://domain.com/mcp-server/actor_id/www
            # We want the base URL up to and including /www: /mcp-server/actor_id/www
            if hasattr(self.request, 'url') and self.request.url:
                # Parse the URL to extract the path part
                from urllib.parse import urlparse
                parsed = urlparse(self.request.url)
                base_path = parsed.path  # This gives us /mcp-server/actor_id/www
            else:
                # Fallback if no request URL available
                base_path = f"/{actor_id}/www"

            self.response.template_values = {
                "url": base_path,
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

            # Execute property hooks for each individual property to filter hidden ones
            # and determine which are read-only (protected from editing)
            read_only_properties = set()
            if self.hooks and properties:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    filtered_properties = {}
                    for prop_name, prop_value in properties.items():
                        # Check GET access
                        hook_result = self.hooks.execute_property_hooks(
                            prop_name, "get", actor_interface, prop_value, [prop_name]
                        )
                        if hook_result is not None:
                            # Property is visible, now check if it's read-only
                            filtered_properties[prop_name] = hook_result
                            
                            # Test if property allows PUT operations (editing)
                            put_test = self.hooks.execute_property_hooks(
                                prop_name, "put", actor_interface, prop_value, [prop_name]
                            )
                            if put_test is None:
                                # PUT operation is blocked, so this property is read-only
                                read_only_properties.add(prop_name)
                    properties = filtered_properties
                    
            self.response.template_values = {
                "id": myself.id,
                "properties": properties,
                "read_only_properties": read_only_properties,
            }
            return
        elif "properties/" in path:
            prop_name = path.split("/")[1]
            lookup = myself.property[prop_name] if prop_name and myself.property else None
            method_override = self.request.params.get("_method", None) if self.request.params else None
            if method_override and method_override.upper() == "DELETE":
                # Execute property delete hook first to check if deletion is allowed
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        hook_result = self.hooks.execute_property_hooks(
                            prop_name, "delete", actor_interface, lookup or {}, [prop_name]
                        )
                        if hook_result is None:
                            # Hook rejected the deletion - return 403 Forbidden
                            self.response.set_status(403, "Property deletion not allowed")
                            return

                # Delete property if hooks allow it
                if lookup and myself.property:
                    myself.property[prop_name] = None

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
                    if hook_result is None:
                        # Hook indicates property should not be accessible (hidden)
                        self.response.set_status(404, "Property not found")
                        return
                    else:
                        lookup = hook_result
            # Extract actor base path from request URL to handle base paths like /mcp-server
            # Request URL is like: https://domain.com/mcp-server/actor_id/www/properties/prop_name
            # We want: /mcp-server/actor_id
            if hasattr(self.request, 'url') and self.request.url:
                from urllib.parse import urlparse
                parsed = urlparse(self.request.url)
                # Remove /www/properties/prop_name to get /mcp-server/actor_id
                path_parts = parsed.path.strip('/').split('/')
                try:
                    actor_index = path_parts.index(actor_id)
                    actor_base_path = '/' + '/'.join(path_parts[:actor_index + 1])
                except (ValueError, IndexError):
                    actor_base_path = f"/{actor_id}"
            else:
                actor_base_path = f"/{actor_id}"

            # Check if this property is read-only (protected from editing)
            is_read_only = False
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    # Test if property allows PUT operations (editing)
                    put_test = self.hooks.execute_property_hooks(
                        prop_name, "put", actor_interface, lookup or {}, [prop_name]
                    )
                    if put_test is None:
                        is_read_only = True

            if lookup:
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": lookup,
                    "qual": "a",
                    "url": actor_base_path,
                    "is_read_only": is_read_only,
                }
            else:
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": "",
                    "qual": "n",
                    "url": actor_base_path,
                    "is_read_only": is_read_only,
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
                    "www", actor_interface, {"path": path, "method": "GET"}
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

                    # Execute property hooks before setting the property
                    final_value = property_value
                    if self.hooks:
                        actor_interface = self._get_actor_interface(myself)
                        if actor_interface:
                            hook_action = "post" if is_new_property else "put"
                            hook_result = self.hooks.execute_property_hooks(
                                property_name, hook_action, actor_interface, property_value, [property_name]
                            )
                            if hook_result is None:
                                self.response.set_status(403, "Property value not accepted by hooks")
                                return
                            final_value = hook_result

                    # Set the property with the potentially transformed value
                    if not myself.property:
                        self.response.set_status(500, "PropertyStore is not initialized")
                        return
                    myself.property[property_name] = final_value

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
                    "www", actor_interface, {"path": path, "method": "POST"}
                )
                if hook_result is not None:
                    output = str(hook_result) if not isinstance(hook_result, str) else hook_result

        if output:
            self.response.write(output)
        else:
            self.response.set_status(404, "Not found")
        return
