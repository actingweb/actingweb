import copy
import json
import logging
from typing import Any

from actingweb.handlers import base_handler

from ..permission_evaluator import PermissionResult, get_permission_evaluator


def merge_dict(d1, d2):
    """Modifies d1 in-place to contain values from d2.

    If any value in d1 is a dictionary (or dict-like), *and* the corresponding
    value in d2 is also a dictionary, then merge them in-place.
    Thanks to Edward Loper on stackoverflow.com
    """
    for k, v2 in list(d2.items()):
        v1 = d1.get(k)  # returns None if v1 has no value for this key
        if isinstance(v1, dict) and isinstance(v2, dict):
            merge_dict(v1, v2)
        else:
            d1[k] = v2


def delete_dict(d1, path):
    """Deletes path (an array of strings) in d1 dict.

    d1 is modified to no longer contain the attr/value pair
    or dict that is specified by path.
    """
    if not d1:
        # logging.debug('Path not found')
        return False
    # logging.debug('d1: ' + json.dumps(d1))
    # logging.debug('path: ' + str(path))
    if len(path) > 1 and path[1] and len(path[1]) > 0:
        return delete_dict(d1.get(path[0]), path[1:])
    if len(path) == 1 and path[0] and path[0] in d1:
        # logging.debug('Deleting d1[' + path[0] + ']')
        try:
            del d1[path[0]]
            return True
        except KeyError:
            return False
    return False


class PropertiesHandler(base_handler.BaseHandler):
    def _check_property_permission(
        self, actor_id: str, auth_obj, property_path: str, operation: str
    ) -> bool:
        """
        Check property permission using the unified access control system.

        This replaces the legacy auth.check_authorisation() with the new permission evaluator
        that supports granular trust type-based permissions.

        Args:
            actor_id: The actor ID
            auth_obj: Auth object from authentication
            property_path: Property path (e.g., "email", "notes/work")
            operation: Operation type ("read", "write", "delete")

        Returns:
            True if access is allowed, False otherwise
        """
        # Get peer ID from auth object (if authenticated via trust relationship)
        # Note: auth_obj.acl is a dict, not an object, so we use .get()
        peer_id = auth_obj.acl.get("peerid", "") if hasattr(auth_obj, "acl") else ""

        if not peer_id:
            # No peer relationship - fall back to legacy authorization for basic/oauth auth
            legacy_subpath = property_path.split("/")[0] if property_path else ""
            method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
            return auth_obj.check_authorisation(
                path="properties",
                subpath=legacy_subpath,
                method=method_map.get(operation, "GET"),
            )

        # Use permission evaluator for peer-based access
        try:
            evaluator = get_permission_evaluator(self.config)
            result = evaluator.evaluate_property_access(
                actor_id, peer_id, property_path, operation
            )

            if result == PermissionResult.ALLOWED:
                return True
            elif result == PermissionResult.DENIED:
                logging.info(
                    f"Property access denied: {actor_id} -> {peer_id} -> {property_path} ({operation})"
                )
                return False
            else:  # NOT_FOUND
                # No specific permission rule - fall back to legacy for backward compatibility
                legacy_subpath = property_path.split("/")[0] if property_path else ""
                method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
                return auth_obj.check_authorisation(
                    path="properties",
                    subpath=legacy_subpath,
                    method=method_map.get(operation, "GET"),
                )

        except Exception as e:
            logging.error(
                f"Error in permission evaluation for {actor_id}:{peer_id}:{property_path}: {e}"
            )
            # Fall back to legacy authorization on errors
            legacy_subpath = property_path.split("/")[0] if property_path else ""
            method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
            return auth_obj.check_authorisation(
                path="properties",
                subpath=legacy_subpath,
                method=method_map.get(operation, "GET"),
            )

    def _create_auth_context(self, auth_obj, operation: str = "read") -> dict[str, Any]:
        """Create auth context for hook execution with peer information."""
        # Note: auth_obj.acl is a dict, not an object, so we use .get()
        peer_id = auth_obj.acl.get("peerid", "") if hasattr(auth_obj, "acl") else ""
        return {"peer_id": peer_id, "config": self.config, "operation": operation}

    def get(self, actor_id, name):
        if self.request.get("_method") == "PUT":
            self.put(actor_id, name)
            return
        if self.request.get("_method") == "DELETE":
            self.delete(actor_id, name)
            return
        auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        if not name:
            path = []
        else:
            path = name.split("/")
            name = path[0]
        # Use unified access control system for permission checking
        property_path = "/".join(path) if path else ""
        if not self._check_property_permission(actor_id, check, property_path, "read"):
            if self.response:
                self.response.set_status(403)
            return
        # if name is not set, this request URI was the properties root
        if not name:
            self.listall(myself, check)
            return

        # Check if this is a list property first
        if (
            myself
            and hasattr(myself, "property_lists")
            and myself.property_lists is not None
            and myself.property_lists.exists(name)
        ):
            # This is a list property - handle index parameter
            index_param = self.request.get("index")
            try:
                list_prop = getattr(myself.property_lists, name)

                if index_param is not None:
                    # Get specific item by index
                    try:
                        index = int(index_param)
                        item = list_prop[index]

                        # Execute property hook if available
                        if self.hooks:
                            actor_interface = self._get_actor_interface(myself)
                            if actor_interface:
                                hook_path = [name, str(index)]
                                auth_context = self._create_auth_context(check, "read")
                                transformed = self.hooks.execute_property_hooks(
                                    name,
                                    "get",
                                    actor_interface,
                                    item,
                                    hook_path,
                                    auth_context,
                                )
                                if transformed is not None:
                                    item = transformed
                                else:
                                    if self.response:
                                        self.response.set_status(404)
                                    return

                        out = json.dumps(item)
                    except (IndexError, ValueError):
                        if self.response:
                            self.response.set_status(404, "List item not found")
                        return
                else:
                    # Get all items
                    all_items = list_prop.to_list()

                    # Execute property hook if available
                    if self.hooks:
                        actor_interface = self._get_actor_interface(myself)
                        if actor_interface:
                            hook_path = [name]
                            auth_context = self._create_auth_context(check, "read")
                            transformed = self.hooks.execute_property_hooks(
                                name,
                                "get",
                                actor_interface,
                                all_items,
                                hook_path,
                                auth_context,
                            )
                            if transformed is not None:
                                all_items = transformed
                            else:
                                if self.response:
                                    self.response.set_status(404)
                                return

                    out = json.dumps(all_items)

                if self.response:
                    self.response.set_status(200, "Ok")
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.write(out)
                return

            except Exception as e:
                logging.error(f"Error accessing list property '{name}': {e}")
                if self.response:
                    self.response.set_status(500, "Error accessing list property")
                return

        # Regular property handling
        lookup = myself.property[name] if myself and myself.property else None
        if not lookup:
            if self.response:
                self.response.set_status(404, "Property not found")
            return
        try:
            jsonblob = json.loads(lookup)
            try:
                out = jsonblob
                if len(path) > 1:
                    del path[0]
                    for p in path:
                        out = out[p]
                # Execute property hook if available
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        # Use the original name for the hook, not the modified path
                        hook_path = name.split("/") if name else []
                        auth_context = self._create_auth_context(check, "read")
                        transformed = self.hooks.execute_property_hooks(
                            name or "*",
                            "get",
                            actor_interface,
                            out,
                            hook_path,
                            auth_context,
                        )
                        if transformed is not None:
                            out = transformed
                        elif (
                            name
                        ):  # If hook returns None for specific property, it means 404
                            if self.response:
                                self.response.set_status(404)
                            return
                out = json.dumps(out)
            except (TypeError, ValueError, KeyError):
                if self.response:
                    self.response.set_status(404)
                return
            # Keep as string for response.write()
        except (TypeError, ValueError, KeyError):
            out = lookup
        if self.response:
            self.response.set_status(200, "Ok")
            self.response.headers["Content-Type"] = "application/json"
            self.response.write(out)

    def listall(self, myself, check):
        # Get actor interface for property access
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            if self.response:
                self.response.set_status(500, "Internal error")
            return

        properties = actor_interface.properties.to_dict()
        # Check if metadata is requested via query parameter
        include_metadata = self.request.get("metadata") == "true"

        # Return empty object with 200 OK when no properties exist (SPA-friendly, spec v1.2)
        if not properties or len(properties) == 0:
            out = json.dumps({})
            self.response.write(out)
            self.response.headers["Content-Type"] = "application/json"
            return

        pair = {}
        for name, value in list(properties.items()):
            try:
                js = json.loads(value)
                pair[name] = js
            except ValueError:
                pair[name] = value

        # Filter properties based on peer permissions
        peer_id = check.acl.get("peerid", "") if hasattr(check, "acl") else ""
        if peer_id and actor_interface and actor_interface.id:
            try:
                evaluator = get_permission_evaluator(self.config)
                filtered_pair = {}
                for prop_name, prop_value in pair.items():
                    result = evaluator.evaluate_property_access(
                        actor_interface.id, peer_id, prop_name, "read"
                    )
                    if result == PermissionResult.ALLOWED:
                        filtered_pair[prop_name] = prop_value
                    elif result == PermissionResult.NOT_FOUND:
                        # No specific rule - include for backward compatibility
                        filtered_pair[prop_name] = prop_value
                    # DENIED properties are excluded
                pair = filtered_pair
            except Exception as e:
                logging.error(f"Error filtering properties by permission: {e}")
                # On error, return empty for security (fail closed)
                pair = {}

        # Execute property hooks for all properties if available
        if self.hooks:
            if actor_interface:
                auth_context = self._create_auth_context(check, "read")
                result = {}
                for key, value in pair.items():
                    transformed = self.hooks.execute_property_hooks(
                        key, "get", actor_interface, value, [], auth_context
                    )
                    if transformed is not None:
                        result[key] = transformed
                pair = result

        # Note: Don't return early if pair is empty - we still need to add list properties below
        # The final output will be handled at the end of the function

        # Add list property metadata if requested
        if include_metadata:
            list_names = set()
            # Use actor_interface for consistent property list access
            if actor_interface and hasattr(actor_interface, "property_lists") and actor_interface.property_lists is not None:
                all_list_names = set(actor_interface.property_lists.list_all() or [])
                logging.debug(f"Found {len(all_list_names)} list properties: {all_list_names}")

                # Filter list properties based on peer permissions
                if peer_id and actor_interface and actor_interface.id:
                    try:
                        evaluator = get_permission_evaluator(self.config)
                        for list_name in all_list_names:
                            result = evaluator.evaluate_property_access(
                                actor_interface.id, peer_id, list_name, "read"
                            )
                            if result == PermissionResult.ALLOWED or result == PermissionResult.NOT_FOUND:
                                list_names.add(list_name)
                            # DENIED list properties are excluded
                    except Exception as e:
                        logging.error(f"Error filtering list properties by permission: {e}")
                        # On error, exclude all list properties for security
                        list_names = set()
                else:
                    # No peer - include all (owner access)
                    list_names = all_list_names

                # Add metadata for permitted list properties
                for list_name in list_names:
                    list_prop = getattr(actor_interface.property_lists, list_name)
                    pair[list_name] = {
                        "is_list": True,
                        "item_count": len(list_prop),
                        "description": list_prop.get_description(),
                        "explanation": list_prop.get_explanation(),
                    }

            # Wrap non-list properties with is_list: false
            for name in list(pair.keys()):
                if name not in list_names:
                    current_value = pair[name]
                    if isinstance(current_value, dict) and "is_list" in current_value:
                        continue  # Already wrapped
                    pair[name] = {
                        "value": current_value,
                        "is_list": False,
                    }

        out = json.dumps(pair)
        self.response.write(out)
        self.response.headers["Content-Type"] = "application/json"
        return

    def put(self, actor_id, name):
        auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        resource = None
        if not name:
            path = []
        else:
            path = name.split("/")
            name = path[0]
            if len(path) >= 2 and len(path[1]) > 0:
                resource = path[1]
        # Use unified access control system for permission checking
        property_path = "/".join(path) if path else ""
        if not check or not self._check_property_permission(
            actor_id, check, property_path, "write"
        ):
            if self.response:
                self.response.set_status(403)
            return
        body = self.request.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", "ignore")
        elif body is None:
            body = ""
        if len(path) == 1:
            old = myself.property[name] if myself and myself.property else None
            try:
                old = json.loads(old or "{}")
            except (TypeError, ValueError, KeyError):
                old = {}
            try:
                new_body = json.loads(body)
                is_json = True
            except (TypeError, ValueError, KeyError):
                new_body = body
                is_json = False
            # Execute property put hook if available
            new = new_body
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface and path:
                    property_name = path[0] if path else "*"
                    auth_context = self._create_auth_context(check, "write")
                    transformed = self.hooks.execute_property_hooks(
                        property_name,
                        "put",
                        actor_interface,
                        new_body,
                        path[1:],  # Exclude property name from path (already in property_name)
                        auth_context,
                    )
                    if transformed is not None:
                        new = transformed
                    else:
                        self.response.set_status(400, "Payload is not accepted")
                        return
            if is_json:
                if myself and myself.property:
                    myself.property[name] = json.dumps(new)
            else:
                if myself and myself.property:
                    myself.property[name] = new
            myself.register_diffs(target="properties", subtarget=name, blob=body)
            self.response.set_status(204)
            return
        # Keep text blob for later diff registration
        blob = body
        # Make store var to be merged with original struct
        try:
            body = json.loads(body)
        except (TypeError, ValueError, KeyError):
            pass
        store = {path[len(path) - 1]: body}
        # logging.debug('store with body:' + json.dumps(store))
        # Make store to be at same level as orig value
        i = len(path) - 2
        while i > 0:
            c = copy.copy(store)
            store = {path[i]: c}
            # logging.debug('store with i=' + str(i) + ' (' + json.dumps(store) + ')')
            i -= 1
        # logging.debug('Snippet to store(' + json.dumps(store) + ')')
        orig = myself.property[name] if myself and myself.property else None
        logging.debug("Original value(" + (orig or "") + ")")
        try:
            orig = json.loads(orig or "{}")
            merge_dict(orig, store)
            res = orig
        except (TypeError, ValueError, KeyError):
            res = store
        # Execute property put hook if available
        final_res = res
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface and path:
                property_name = path[0] if path else "*"
                auth_context = self._create_auth_context(check, "write")
                transformed = self.hooks.execute_property_hooks(
                    property_name, "put", actor_interface, res, path[1:], auth_context
                )
                if transformed is not None:
                    final_res = transformed
                else:
                    self.response.set_status(400, "Payload is not accepted")
                    return
        res = final_res
        res = json.dumps(res)
        logging.debug("Result to store( " + res + ") in /properties/" + name)
        if myself and myself.property:
            myself.property[name] = res
        myself.register_diffs(
            target="properties", subtarget=name, resource=resource, blob=blob
        )
        self.response.set_status(204)

    def post(self, actor_id, name):
        auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        if not auth_result.authorize("POST", "properties", name):
            return
        if len(name) > 0:
            if self.response:
                self.response.set_status(400)
        pair = {}
        # Handle the form with property type support
        if self.request.get("property"):
            prop_name = self.request.get("property")
            prop_type = (
                self.request.get("property_type") or "simple"
            )  # Default to simple

            # Handle list property creation
            if prop_type == "list":
                # Create empty list property
                if myself and hasattr(myself, "property_lists"):
                    # Create empty list by accessing it (this initializes the ListProperty)
                    list_prop = getattr(myself.property_lists, prop_name)
                    # The ListProperty is now created with metadata, but no items

                    # Set description and explanation if provided
                    description = self.request.get("description") or ""
                    explanation = self.request.get("explanation") or ""

                    if description:
                        list_prop.set_description(description)
                    if explanation:
                        list_prop.set_explanation(explanation)

                    # Execute property post hook if available for list creation
                    if self.hooks:
                        actor_interface = self._get_actor_interface(myself)
                        if actor_interface:
                            auth_context = self._create_auth_context(check, "write")
                            transformed = self.hooks.execute_property_hooks(
                                prop_name,
                                "post",
                                actor_interface,
                                [],
                                [prop_name],
                                auth_context,
                            )
                            if transformed is None:
                                if self.response:
                                    self.response.set_status(403)
                                return

                    pair[prop_name] = "[Empty list property created]"
                else:
                    if self.response:
                        self.response.set_status(500, "List properties not supported")
                    return

            # Handle simple property creation
            elif prop_type == "simple" and self.request.get("value"):
                # Execute property post hook if available
                val = self.request.get("value")
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        auth_context = self._create_auth_context(check, "write")
                        transformed = self.hooks.execute_property_hooks(
                            prop_name,
                            "post",
                            actor_interface,
                            val,
                            [prop_name],
                            auth_context,
                        )
                        if transformed is not None:
                            val = transformed
                        else:
                            if self.response:
                                self.response.set_status(403)
                            return
                pair[prop_name] = val
                if myself and myself.property:
                    myself.property[prop_name] = val

            else:
                # Missing value for simple property
                if self.response:
                    self.response.set_status(400, "Value required for simple property")
                return
        elif len(self.request.arguments()) > 0:
            for name in self.request.arguments():
                # Execute property post hook if available
                val = self.request.get(name)
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        auth_context = self._create_auth_context(check, "write")
                        transformed = self.hooks.execute_property_hooks(
                            name, "post", actor_interface, val, [], auth_context
                        )
                        if transformed is not None:
                            val = transformed
                        else:
                            continue
                pair[name] = val
                if myself and myself.property:
                    myself.property[name] = val
        else:
            try:
                body = self.request.body
                if isinstance(body, bytes):
                    body = body.decode("utf-8", "ignore")
                elif body is None:
                    body = "{}"
                params = json.loads(body)
            except (TypeError, ValueError, KeyError):
                if self.response:
                    self.response.set_status(400, "Error in json body")
                return
            for key in params:
                val = params[key]
                # Handle special list property creation with metadata
                if isinstance(val, dict) and val.get("_type") == "list":
                    # This is a list property creation with metadata
                    if myself and hasattr(myself, "property_lists"):
                        list_prop = getattr(myself.property_lists, key)

                        # Set description and explanation if provided, or ensure metadata is persisted
                        description_set = False
                        if "description" in val:
                            list_prop.set_description(val["description"])
                            description_set = True
                        if "explanation" in val:
                            list_prop.set_explanation(val["explanation"])
                        elif not description_set:
                            # Ensure metadata is persisted even if no description/explanation provided
                            list_prop.set_description("")

                        # Execute property post hook if available for list creation
                        if self.hooks:
                            actor_interface = self._get_actor_interface(myself)
                            if actor_interface:
                                auth_context = self._create_auth_context(check, "write")
                                transformed = self.hooks.execute_property_hooks(
                                    key,
                                    "post",
                                    actor_interface,
                                    [],
                                    [key],
                                    auth_context,
                                )
                                if transformed is not None:
                                    pair[key] = "[Empty list property created]"
                                else:
                                    continue
                        else:
                            pair[key] = "[Empty list property created]"
                    else:
                        # List properties not supported
                        continue

                # Handle items array for bulk list updates
                elif isinstance(val, dict) and "items" in val:
                    # Validate items array structure
                    if not isinstance(val["items"], list):
                        logging.error(
                            f"Invalid 'items' field for property '{key}': expected list, got {type(val['items']).__name__}"
                        )
                        if self.response:
                            self.response.set_status(
                                400,
                                f"Invalid 'items' field for property '{key}': expected list, got {type(val['items']).__name__}",
                            )
                        return

                    if len(val["items"]) == 0:
                        logging.warning(
                            f"Empty 'items' array for property '{key}': no updates to perform"
                        )
                        pair[key] = "[No items to update]"
                        continue

                    # This is a bulk update for a list property
                    if (
                        myself
                        and hasattr(myself, "property_lists")
                        and myself.property_lists is not None
                        and myself.property_lists.exists(key)
                    ):
                        try:
                            list_prop = getattr(myself.property_lists, key)
                            items_updated = 0
                            items_deleted = 0

                            for i, item_spec in enumerate(val["items"]):
                                # Validate item structure
                                if not isinstance(item_spec, dict):
                                    logging.error(
                                        f"Invalid item at position {i}: must be a dictionary, got {type(item_spec).__name__}"
                                    )
                                    if self.response:
                                        self.response.set_status(
                                            400,
                                            f"Invalid item at position {i}: must be a dictionary, got {type(item_spec).__name__}",
                                        )
                                    return

                                # Check for required "index" field
                                if "index" not in item_spec:
                                    logging.error(
                                        f"Missing 'index' field in item at position {i}: {item_spec}"
                                    )
                                    if self.response:
                                        self.response.set_status(
                                            400,
                                            f"Missing 'index' field in item at position {i}",
                                        )
                                    return

                                index = item_spec["index"]

                                # Validate index type and value
                                if not isinstance(index, int):
                                    logging.error(
                                        f"Invalid index type in item at position {i}: expected integer, got {type(index).__name__}"
                                    )
                                    if self.response:
                                        self.response.set_status(
                                            400,
                                            f"Invalid index type in item at position {i}: expected integer, got {type(index).__name__}",
                                        )
                                    return

                                if index < 0:
                                    logging.error(
                                        f"Invalid index value in item at position {i}: {index} (must be >= 0)"
                                    )
                                    if self.response:
                                        self.response.set_status(
                                            400,
                                            f"Invalid index value in item at position {i}: {index} (must be >= 0)",
                                        )
                                    return

                                # Check if this is a deletion (empty item data)
                                if (
                                    len(item_spec) == 1
                                ):  # Only has "index" key, means delete
                                    try:
                                        if index < len(list_prop):
                                            del list_prop[index]
                                            items_deleted += 1
                                        else:
                                            logging.warning(
                                                f"Cannot delete item at index {index}: index out of range (list length: {len(list_prop)})"
                                            )
                                            # Don't fail the entire operation, just log warning
                                    except IndexError as e:
                                        logging.error(
                                            f"Error deleting item at index {index}: {e}"
                                        )
                                        # Don't fail the entire operation for delete errors
                                else:
                                    # Update/set item - the entire item_spec except "index" is the item data
                                    item_data = {
                                        k: v
                                        for k, v in item_spec.items()
                                        if k != "index"
                                    }
                                    try:
                                        # Extend list if needed
                                        while len(list_prop) <= index:
                                            list_prop.append(None)
                                        # Store the complete object
                                        list_prop[index] = item_data
                                        items_updated += 1
                                    except (IndexError, ValueError) as e:
                                        logging.error(
                                            f"Error updating item at index {index}: {e}"
                                        )
                                        if self.response:
                                            self.response.set_status(
                                                500,
                                                f"Error updating item at index {index}: {str(e)}",
                                            )
                                        return

                            # Execute property post hook if available
                            if self.hooks:
                                actor_interface = self._get_actor_interface(myself)
                                if actor_interface:
                                    # Pass the entire list for hook validation
                                    current_items = list_prop.to_list()
                                    auth_context = self._create_auth_context(
                                        check, "write"
                                    )
                                    transformed = self.hooks.execute_property_hooks(
                                        key,
                                        "post",
                                        actor_interface,
                                        current_items,
                                        [key],
                                        auth_context,
                                    )
                                    if transformed is None:
                                        # Hook rejected the update - need to revert changes
                                        if self.response:
                                            self.response.set_status(
                                                403, "Bulk update rejected by hooks"
                                            )
                                        return

                            pair[key] = (
                                f"[Bulk update: {items_updated} items updated, {items_deleted} items deleted]"
                            )

                        except Exception as e:
                            logging.error(
                                f"Error in bulk update for list property '{key}': {e}"
                            )
                            if self.response:
                                self.response.set_status(
                                    500, f"Error in bulk update: {str(e)}"
                                )
                            return
                    else:
                        # Not a list property or doesn't exist
                        if self.response:
                            self.response.set_status(
                                400, f"Property '{key}' is not a list property"
                            )
                        return
                else:
                    # Regular property handling
                    # Execute property post hook if available
                    if self.hooks:
                        actor_interface = self._get_actor_interface(myself)
                        if actor_interface:
                            auth_context = self._create_auth_context(check, "write")
                            transformed = self.hooks.execute_property_hooks(
                                key, "post", actor_interface, val, [], auth_context
                            )
                            if transformed is not None:
                                val = transformed
                            else:
                                continue
                    pair[key] = val
                    if isinstance(val, dict):
                        text = json.dumps(val)
                    else:
                        text = val
                    if myself and myself.property:
                        myself.property[key] = text
        if not pair:
            if self.response:
                self.response.set_status(403, "No attributes accepted")
            return
        out = json.dumps(pair)
        myself.register_diffs(target="properties", blob=out)
        if self.response:
            self.response.write(out)
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(201, "Created")

    def delete(self, actor_id, name):
        auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        resource = None
        if not name:
            path = []
        else:
            path = name.split("/")
            name = path[0]
            if len(path) >= 2 and len(path[1]) > 0:
                resource = path[1]
        # Use unified access control system for permission checking
        property_path = "/".join(path) if path else ""
        if not self._check_property_permission(
            actor_id, check, property_path, "delete"
        ):
            self.response.set_status(403)
            return
        if not name:
            # Get actor interface for property operations
            actor_interface = self._get_actor_interface(myself)
            if not actor_interface:
                if self.response:
                    self.response.set_status(500, "Internal error")
                return

            # Execute property delete hook if available
            if self.hooks:
                result = self.hooks.execute_property_hooks(
                    "*", "delete", actor_interface, actor_interface.properties.to_dict(), path
                )
                if result is None:
                    self.response.set_status(403)
                    return
            actor_interface.properties.clear()
            myself.register_diffs(target="properties", subtarget=None, blob="")
            self.response.set_status(204)
            return
        if len(path) == 1:
            # Check if this is a list property first
            if (
                myself
                and hasattr(myself, "property_lists")
                and myself.property_lists is not None
                and myself.property_lists.exists(name)
            ):
                # This is a list property - delete the entire list
                try:
                    list_prop = getattr(myself.property_lists, name)

                    # Execute property delete hook if available
                    if self.hooks:
                        actor_interface = self._get_actor_interface(myself)
                        if actor_interface:
                            # Pass current list data for hook validation
                            current_items = list_prop.to_list()
                            auth_context = self._create_auth_context(check, "delete")
                            result = self.hooks.execute_property_hooks(
                                name,
                                "delete",
                                actor_interface,
                                current_items,
                                path,
                                auth_context,
                            )
                            if result is None:
                                self.response.set_status(403)
                                return

                    # Delete the entire list including metadata
                    list_prop.delete()
                    myself.register_diffs(target="properties", subtarget=name, blob="")
                    self.response.set_status(204)
                    return

                except Exception as e:
                    logging.error(f"Error deleting list property '{name}': {e}")
                    self.response.set_status(
                        500, f"Error deleting list property: {str(e)}"
                    )
                    return

            # Regular property handling
            old_prop = myself.property[name] if myself and myself.property else None
            # Execute property delete hook if available
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface and path:
                    property_name = path[0] if path else "*"
                    auth_context = self._create_auth_context(check, "delete")
                    result = self.hooks.execute_property_hooks(
                        property_name,
                        "delete",
                        actor_interface,
                        old_prop or {},
                        path,
                        auth_context,
                    )
                    if result is None:
                        self.response.set_status(403)
                        return
            if myself and myself.property:
                myself.property[name] = None
            myself.register_diffs(target="properties", subtarget=name, blob="")
            self.response.set_status(204)
            return
        orig = myself.property[name] if myself and myself.property else None
        old = orig
        logging.debug("DELETE /properties original value(" + (orig or "") + ")")
        try:
            orig = json.loads(orig or "{}")
        except (TypeError, ValueError, KeyError):
            # Since /properties/something was handled above
            # orig must be json loadable
            self.response.set_status(404)
            return
        if not delete_dict(orig, path[1:]):
            self.response.set_status(404)
            return
        # Execute property delete hook if available
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface and path:
                property_name = path[0] if path else "*"
                auth_context = self._create_auth_context(check, "delete")
                result = self.hooks.execute_property_hooks(
                    property_name,
                    "delete",
                    actor_interface,
                    old or {},
                    path,
                    auth_context,
                )
                if result is None:
                    self.response.set_status(403)
                    return
        res = json.dumps(orig)
        logging.debug("Result to store( " + res + ") in /properties/" + name)
        if myself and myself.property:
            myself.property[name] = res
        myself.register_diffs(
            target="properties", subtarget=name, resource=resource, blob=""
        )
        self.response.set_status(204)


class PropertyMetadataHandler(base_handler.BaseHandler):
    """Handler for list property metadata operations.

    Handles PUT /{actor_id}/properties/{name}/metadata
    for updating list property description and explanation fields.
    """

    def _check_property_permission(
        self, actor_id: str, auth_obj, property_path: str, operation: str
    ) -> bool:
        """
        Check property permission using the unified access control system.

        Reuses the same permission logic as PropertiesHandler.
        """
        # Get peer ID from auth object (if authenticated via trust relationship)
        # Note: auth_obj.acl is a dict, not an object, so we use .get()
        peer_id = auth_obj.acl.get("peerid", "") if hasattr(auth_obj, "acl") else ""

        if not peer_id:
            # No peer relationship - fall back to legacy authorization
            legacy_subpath = property_path.split("/")[0] if property_path else ""
            method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
            return auth_obj.check_authorisation(
                path="properties",
                subpath=legacy_subpath,
                method=method_map.get(operation, "GET"),
            )

        # Use permission evaluator for peer-based access
        try:
            evaluator = get_permission_evaluator(self.config)
            result = evaluator.evaluate_property_access(
                actor_id, peer_id, property_path, operation
            )

            if result == PermissionResult.ALLOWED:
                return True
            elif result == PermissionResult.DENIED:
                logging.info(
                    f"Property metadata access denied: {actor_id} -> {peer_id} -> {property_path} ({operation})"
                )
                return False
            else:  # NOT_FOUND
                # Fall back to legacy for backward compatibility
                legacy_subpath = property_path.split("/")[0] if property_path else ""
                method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
                return auth_obj.check_authorisation(
                    path="properties",
                    subpath=legacy_subpath,
                    method=method_map.get(operation, "GET"),
                )

        except Exception as e:
            logging.error(
                f"Error in permission evaluation for metadata {actor_id}:{peer_id}:{property_path}: {e}"
            )
            # Fall back to legacy authorization on errors
            legacy_subpath = property_path.split("/")[0] if property_path else ""
            method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
            return auth_obj.check_authorisation(
                path="properties",
                subpath=legacy_subpath,
                method=method_map.get(operation, "GET"),
            )

    def get(self, actor_id: str, name: str):
        """Get list property metadata (description, explanation)."""
        auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj

        # Check read permission
        if not self._check_property_permission(actor_id, check, name, "read"):
            if self.response:
                self.response.set_status(403)
            return

        # Verify this is a list property
        if not (
            myself
            and hasattr(myself, "property_lists")
            and myself.property_lists is not None
            and myself.property_lists.exists(name)
        ):
            if self.response:
                self.response.set_status(
                    404, "Property not found or not a list property"
                )
            return

        # Get metadata
        list_prop = getattr(myself.property_lists, name)
        metadata = {
            "name": name,
            "is_list": True,
            "item_count": len(list_prop),
            "description": list_prop.get_description(),
            "explanation": list_prop.get_explanation(),
        }

        if self.response:
            self.response.write(json.dumps(metadata))
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(200)

    def put(self, actor_id: str, name: str):
        """Update list property metadata (description, explanation)."""
        auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj

        # Check write permission
        if not self._check_property_permission(actor_id, check, name, "write"):
            if self.response:
                self.response.set_status(403)
            return

        # Verify this is a list property
        if not (
            myself
            and hasattr(myself, "property_lists")
            and myself.property_lists is not None
            and myself.property_lists.exists(name)
        ):
            if self.response:
                self.response.set_status(
                    404, "Property not found or not a list property"
                )
            return

        # Parse request body
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            params = json.loads(body or "{}")
        except (TypeError, ValueError, KeyError):
            if self.response:
                self.response.set_status(400, "Invalid JSON body")
            return

        # Validate that at least one field is provided
        if "description" not in params and "explanation" not in params:
            if self.response:
                self.response.set_status(
                    400, "Request must include 'description' and/or 'explanation'"
                )
            return

        # Update metadata
        list_prop = getattr(myself.property_lists, name)

        if "description" in params:
            list_prop.set_description(str(params["description"]))
        if "explanation" in params:
            list_prop.set_explanation(str(params["explanation"]))

        # Register diff for metadata changes
        myself.register_diffs(
            target="properties",
            subtarget=name,
            blob=json.dumps({"action": "metadata_update", **params}),
        )

        if self.response:
            self.response.set_status(204)


class PropertyListItemsHandler(base_handler.BaseHandler):
    """Handler for list property items operations.

    Handles GET/POST /{actor_id}/properties/{name}/items
    for reading all items and adding/updating/deleting items in list properties.
    """

    def _check_property_permission(
        self, actor_id: str, auth_obj, property_path: str, operation: str
    ) -> bool:
        """
        Check property permission using the unified access control system.

        Reuses the same permission logic as PropertiesHandler.
        """
        # Get peer ID from auth object (if authenticated via trust relationship)
        # Note: auth_obj.acl is a dict, not an object, so we use .get()
        peer_id = auth_obj.acl.get("peerid", "") if hasattr(auth_obj, "acl") else ""

        if not peer_id:
            # No peer relationship - fall back to legacy authorization
            legacy_subpath = property_path.split("/")[0] if property_path else ""
            method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
            return auth_obj.check_authorisation(
                path="properties",
                subpath=legacy_subpath,
                method=method_map.get(operation, "GET"),
            )

        # Use permission evaluator for peer-based access
        try:
            evaluator = get_permission_evaluator(self.config)
            result = evaluator.evaluate_property_access(
                actor_id, peer_id, property_path, operation
            )

            if result == PermissionResult.ALLOWED:
                return True
            elif result == PermissionResult.DENIED:
                logging.info(
                    f"Property items access denied: {actor_id} -> {peer_id} -> {property_path} ({operation})"
                )
                return False
            else:  # NOT_FOUND
                # Fall back to legacy for backward compatibility
                legacy_subpath = property_path.split("/")[0] if property_path else ""
                method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
                return auth_obj.check_authorisation(
                    path="properties",
                    subpath=legacy_subpath,
                    method=method_map.get(operation, "GET"),
                )

        except Exception as e:
            logging.error(
                f"Error in permission evaluation for items {actor_id}:{peer_id}:{property_path}: {e}"
            )
            # Fall back to legacy authorization on errors
            legacy_subpath = property_path.split("/")[0] if property_path else ""
            method_map = {"read": "GET", "write": "PUT", "delete": "DELETE"}
            return auth_obj.check_authorisation(
                path="properties",
                subpath=legacy_subpath,
                method=method_map.get(operation, "GET"),
            )

    def get(self, actor_id: str, name: str):
        """Get all items from a list property."""
        auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj

        # Check read permission
        if not self._check_property_permission(actor_id, check, name, "read"):
            if self.response:
                self.response.set_status(403)
            return

        # Verify this is a list property
        if not (
            myself
            and hasattr(myself, "property_lists")
            and myself.property_lists is not None
            and myself.property_lists.exists(name)
        ):
            if self.response:
                self.response.set_status(
                    404, "Property not found or not a list property"
                )
            return

        # Get all items
        list_prop = getattr(myself.property_lists, name)
        items = list_prop.to_list()

        if self.response:
            self.response.write(json.dumps(items))
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(200)

    def post(self, actor_id: str, name: str):
        """Add, update, or delete items in a list property.

        Expects JSON body with:
        - action: "add", "update", or "delete"
        - item_value: The value to add or update to (for add/update)
        - item_index: The index to update or delete (for update/delete)
        """
        auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj

        # Check write permission
        if not self._check_property_permission(actor_id, check, name, "write"):
            if self.response:
                self.response.set_status(403)
            return

        # Verify this is a list property
        if not (
            myself
            and hasattr(myself, "property_lists")
            and myself.property_lists is not None
            and myself.property_lists.exists(name)
        ):
            if self.response:
                self.response.set_status(
                    404, "Property not found or not a list property"
                )
            return

        # Parse request body
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            params = json.loads(body or "{}")
        except (TypeError, ValueError, KeyError):
            if self.response:
                self.response.set_status(400, "Invalid JSON body")
            return

        action = params.get("action")
        if not action:
            if self.response:
                self.response.set_status(400, "Missing 'action' parameter")
            return

        list_prop = getattr(myself.property_lists, name)

        try:
            if action == "add":
                # Add new item
                item_value = params.get("item_value")
                if item_value is None:
                    if self.response:
                        self.response.set_status(400, "Missing 'item_value' parameter")
                    return

                list_prop.append(item_value)

                # Register diff for subscription notifications
                myself.register_diffs(
                    target="properties",
                    subtarget=name,
                    blob=json.dumps(
                        {
                            "action": "add",
                            "index": len(list_prop) - 1,
                            "value": item_value,
                        }
                    ),
                )

                if self.response:
                    self.response.write(
                        json.dumps({"success": True, "index": len(list_prop) - 1})
                    )
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.set_status(201)

            elif action == "update":
                # Update existing item
                item_index = params.get("item_index")
                item_value = params.get("item_value")

                if item_index is None:
                    if self.response:
                        self.response.set_status(400, "Missing 'item_index' parameter")
                    return
                if item_value is None:
                    if self.response:
                        self.response.set_status(400, "Missing 'item_value' parameter")
                    return

                try:
                    index = int(item_index)
                except ValueError:
                    if self.response:
                        self.response.set_status(400, "Invalid 'item_index' value")
                    return

                if index < 0 or index >= len(list_prop):
                    if self.response:
                        self.response.set_status(400, f"Index {index} out of range")
                    return

                list_prop[index] = item_value

                # Register diff for subscription notifications
                myself.register_diffs(
                    target="properties",
                    subtarget=name,
                    blob=json.dumps({"action": "update", "index": index, "value": item_value}),
                )

                if self.response:
                    self.response.set_status(204)

            elif action == "delete":
                # Delete item
                item_index = params.get("item_index")

                if item_index is None:
                    if self.response:
                        self.response.set_status(400, "Missing 'item_index' parameter")
                    return

                try:
                    index = int(item_index)
                except ValueError:
                    if self.response:
                        self.response.set_status(400, "Invalid 'item_index' value")
                    return

                if index < 0 or index >= len(list_prop):
                    if self.response:
                        self.response.set_status(400, f"Index {index} out of range")
                    return

                del list_prop[index]

                # Register diff for subscription notifications
                myself.register_diffs(
                    target="properties",
                    subtarget=name,
                    blob=json.dumps({"action": "delete", "index": index}),
                )

                if self.response:
                    self.response.set_status(204)

            else:
                if self.response:
                    self.response.set_status(400, f"Unknown action: {action}")
                return

        except Exception as e:
            logging.error(f"Error in list item operation '{action}' for '{name}': {e}")
            if self.response:
                self.response.set_status(500, f"Error processing list item: {str(e)}")
