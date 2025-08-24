# mypy: disable-error-code="unreachable,unused-ignore"
import json
import logging
from actingweb import auth
from actingweb.handlers import base_handler

logger = logging.getLogger(__name__)


class WwwHandler(base_handler.BaseHandler):

    def get(self, actor_id: str, path: str) -> None:
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
            if hasattr(self.request, "url") and self.request.url:
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

            # Note: List properties are now automatically filtered out at the database level
            # using the "list:" prefix, so no manual filtering needed here

            # Execute property hooks for each individual property to filter hidden ones
            # and determine which are read-only (protected from editing)
            read_only_properties = set()
            list_properties = set()  # Track which properties are lists

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

            # Check for list properties and prepare special display values
            display_properties = {}
            all_properties = properties.copy() if properties else {}

            # Discover standalone list properties using the proper interface
            if myself and hasattr(myself, "property_lists") and myself.property_lists is not None:
                list_names = myself.property_lists.list_all()
                logger.debug(f"Found list properties: {list_names}")
                for list_name in list_names:
                    if list_name not in all_properties:
                        # This is a standalone list property
                        all_properties[list_name] = None  # Placeholder value

            # Process all properties (regular + list)
            for prop_name, prop_value in all_properties.items():
                # Check if this is a list property using the proper interface
                if (
                    myself
                    and hasattr(myself, "property_lists")
                    and myself.property_lists is not None
                    and myself.property_lists.exists(prop_name)
                ):
                    # This is a list property
                    list_properties.add(prop_name)
                    try:
                        list_prop = getattr(myself.property_lists, prop_name)
                        list_length = len(list_prop)
                        display_properties[prop_name] = f"[List with {list_length} items]"
                    except Exception as e:
                        logger.error(f"Error getting length for list property '{prop_name}': {e}")
                        display_properties[prop_name] = "[List property]"
                else:
                    # Regular property - use original value
                    display_properties[prop_name] = prop_value

            # Debug logging
            logger.debug(f"Template values - properties: {list((display_properties or properties).keys())}")
            logger.debug(f"Template values - list_properties: {list(list_properties)}")

            self.response.template_values = {
                "id": myself.id,
                "properties": display_properties or properties,
                "read_only_properties": read_only_properties,
                "list_properties": list_properties,
            }
            return
        elif "properties/" in path and "/items" in path:
            # Handle list item management routes like /properties/notes/items
            path_parts = path.split("/")
            if len(path_parts) >= 3 and path_parts[2] == "items":
                prop_name = path_parts[1]
                # This is handled in the POST method
                self.response.set_status(405, "Method not allowed for list items")
                return
            # Fall through to regular property handling
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
                deleted = False

                # Check if this is a list property first
                if (
                    myself
                    and hasattr(myself, "property_lists")
                    and myself.property_lists is not None
                    and myself.property_lists.exists(prop_name)
                ):
                    # This is a list property - delete the entire list
                    try:
                        list_prop = getattr(myself.property_lists, prop_name)
                        list_prop.delete()  # Delete entire list including metadata

                        deleted = True
                    except Exception as e:
                        logger.error(f"Error deleting list property '{prop_name}': {e}")
                        self.response.set_status(500, f"Error deleting list property: {str(e)}")
                        return

                elif lookup and myself.property:
                    # This is a regular property
                    myself.property[prop_name] = None
                    deleted = True

                if deleted:
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
            if hasattr(self.request, "url") and self.request.url:
                from urllib.parse import urlparse

                parsed = urlparse(self.request.url)
                # Remove /www/properties/prop_name to get /mcp-server/actor_id
                path_parts = parsed.path.strip("/").split("/")
                try:
                    actor_index = path_parts.index(actor_id)
                    actor_base_path = "/" + "/".join(path_parts[: actor_index + 1])
                except (ValueError, IndexError):
                    actor_base_path = f"/{actor_id}"
            else:
                actor_base_path = f"/{actor_id}"

            # Check if this property is read-only (protected from editing)
            is_read_only = False
            is_list_property = False
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    # Test if property allows PUT operations (editing)
                    put_test = self.hooks.execute_property_hooks(
                        prop_name, "put", actor_interface, lookup or {}, [prop_name]
                    )
                    if put_test is None:
                        is_read_only = True

            # Check if this is a list property and prepare appropriate display value
            display_value = lookup
            list_items = None
            list_description = ""
            list_explanation = ""

            # Check if this is a list property using the new interface
            if (
                myself
                and hasattr(myself, "property_lists")
                and myself.property_lists is not None
                and myself.property_lists.exists(prop_name)
            ):
                is_list_property = True
                logger.debug(f"Property '{prop_name}' detected as list property")
                try:
                    # Get the actual list property and load all items
                    list_prop = getattr(myself.property_lists, prop_name)
                    list_items = list_prop.to_list()
                    list_length = len(list_items)
                    
                    # Get description and explanation
                    list_description = list_prop.get_description()
                    list_explanation = list_prop.get_explanation()

                    # For display, show summary
                    display_value = f"List with {list_length} items"

                except Exception as e:
                    logger.error(f"Error loading list items for '{prop_name}': {e}")
                    display_value = "[List property - error loading items]"
                    list_items = []

            elif lookup is not None:
                try:
                    # Check if this property is an old-style distributed list by looking for metadata
                    if myself.property and hasattr(myself.property, "_config") and myself.property._config is not None:
                        db = myself.property._config.DbProperty.DbProperty()
                        meta = db.get(actor_id=myself.id, name=f"{prop_name}-meta")
                        if meta is not None:
                            # This is an old-style list property
                            is_list_property = True
                            try:
                                meta_data = json.loads(meta)
                                list_length = meta_data.get("length", 0)
                                created_at = meta_data.get("created_at", "Unknown")

                                # For list properties, show metadata instead of raw value
                                display_value = f"List with {list_length} items (Created: {created_at}) - Legacy Format"
                            except (json.JSONDecodeError, TypeError):
                                display_value = "[List property - metadata error]"
                except Exception:
                    # If anything goes wrong, use original value
                    pass

            if lookup:
                logger.debug(f"Template variables for {prop_name}: is_list_property={is_list_property}, list_items_count={len(list_items) if list_items else 0}")
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": display_value,
                    "raw_value": lookup,
                    "qual": "a",
                    "url": actor_base_path,
                    "is_read_only": is_read_only,
                    "is_list_property": is_list_property,
                    "list_items": list_items,
                    "list_description": list_description,
                    "list_explanation": list_explanation,
                }
            else:
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": "",
                    "raw_value": "",
                    "qual": "n",
                    "url": actor_base_path,
                    "is_read_only": is_read_only,
                    "is_list_property": False,
                    "list_items": [],
                    "list_description": "",
                    "list_explanation": "",
                }
            return
        if path == "trust":
            relationships = myself.get_trust_relationships()
            if not relationships:
                relationships = []

            # Build approve URIs safely for dict-based relationships
            for t in relationships:
                if isinstance(t, dict):
                    rel = t.get("relationship", "")
                    peerid = t.get("peerid", "")
                    t["approveuri"] = f"{self.config.root}{myself.id or ''}/trust/{rel}/{peerid}"
                else:
                    # Fallback for object-like items
                    rel = getattr(t, "relationship", "")
                    peerid = getattr(t, "peerid", "")
                    try:
                        t.approveuri = f"{self.config.root}{myself.id or ''}/trust/{rel}/{peerid}"
                    except Exception:
                        pass

            # Compute actor base path for links (e.g., /<actor_id>)
            if hasattr(self.request, "url") and self.request.url:
                from urllib.parse import urlparse

                parsed = urlparse(self.request.url)
                path_parts = parsed.path.strip("/").split("/")
                try:
                    actor_index = path_parts.index(actor_id)
                    actor_base_path = "/" + "/".join(path_parts[: actor_index + 1])
                except (ValueError, IndexError):
                    actor_base_path = f"/{actor_id}"
            else:
                actor_base_path = f"/{actor_id}"

            self.response.template_values = {
                "id": myself.id,
                "trusts": relationships,
                "url": f"{actor_base_path}/",
            }
            return
        # Execute callback hook for custom web paths
        output = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_callback_hooks("www", actor_interface, {"path": path, "method": "GET"})
                if hook_result is not None:
                    if isinstance(hook_result, str):
                        output = hook_result  # type: ignore[unreachable]
                    elif isinstance(hook_result, dict):
                        output = json.dumps(hook_result)  # type: ignore[unreachable]
                    else:
                        output = str(hook_result)
        if output:
            self.response.write(output)
        else:
            self.response.set_status(404, "Not found")
        return

    def post(self, actor_id: str, path: str) -> None:
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

        # Handle list metadata updates (description/explanation)
        if "properties/" in path and "/metadata" in path:
            path_parts = path.split("/")
            if len(path_parts) >= 3 and path_parts[2] == "metadata":
                prop_name = path_parts[1]
                action = self.request.get("action")
                
                if action == "update":
                    # Update list metadata
                    description = self.request.get("description")
                    explanation = self.request.get("explanation")
                    
                    if (myself and hasattr(myself, "property_lists") and myself.property_lists is not None 
                        and myself.property_lists.exists(prop_name)):
                        try:
                            list_prop = getattr(myself.property_lists, prop_name)
                            
                            if description is not None:
                                list_prop.set_description(description)
                            if explanation is not None:
                                list_prop.set_explanation(explanation)
                                
                            # Redirect back to the property page
                            self.response.set_status(302, "Found")
                            self.response.set_redirect(f"/{actor_id}/www/properties/{prop_name}")
                            return
                            
                        except Exception as e:
                            logger.error(f"Error updating list metadata for '{prop_name}': {e}")
                            self.response.set_status(500, f"Error updating list metadata: {str(e)}")
                            return
                    else:
                        self.response.set_status(404, "List property not found")
                        return
                else:
                    self.response.set_status(400, f"Unknown metadata action: {action}")
                    return

        # Handle list item management first (before regular property handling)
        if "properties/" in path and "/items" in path:
            path_parts = path.split("/")
            if len(path_parts) >= 3 and path_parts[2] == "items":
                prop_name = path_parts[1]
                action = self.request.get("action")

                if not action:
                    self.response.set_status(400, "Missing action parameter")
                    return

                try:
                    if action == "add":
                        # Add new item to list
                        item_value = self.request.get("item_value")
                        logger.debug(f"List item add request - prop_name: {prop_name}, item_value: {item_value}")
                        
                        if not item_value:
                            self.response.set_status(400, "Missing item_value parameter")
                            return

                        # Try to parse as JSON, fall back to string
                        try:
                            parsed_value = json.loads(item_value)
                            logger.debug(f"Parsed item_value as JSON: {parsed_value}")
                        except json.JSONDecodeError:
                            parsed_value = item_value
                            logger.debug(f"Using item_value as string: {parsed_value}")

                        # Get the list property and append
                        if myself and hasattr(myself, "property_lists"):
                            logger.debug(f"Getting list property: {prop_name}")
                            list_prop = getattr(myself.property_lists, prop_name)
                            logger.debug(f"List length before append: {len(list_prop)}")
                            list_prop.append(parsed_value)
                            logger.debug(f"List length after append: {len(list_prop)}")
                        else:
                            logger.error("List properties not supported")
                            self.response.set_status(500, "List properties not supported")
                            return

                    elif action == "update":
                        # Update existing item
                        item_index = self.request.get("item_index")
                        item_value = self.request.get("item_value")

                        if item_index is None or item_value is None:
                            self.response.set_status(400, "Missing item_index or item_value parameter")
                            return

                        try:
                            index = int(item_index)
                        except ValueError:
                            self.response.set_status(400, "Invalid item_index")
                            return

                        # Try to parse as JSON, fall back to string
                        try:
                            parsed_value = json.loads(item_value)
                        except json.JSONDecodeError:
                            parsed_value = item_value

                        # Get the list property and update
                        if myself and hasattr(myself, "property_lists"):
                            list_prop = getattr(myself.property_lists, prop_name)
                            if index < 0 or index >= len(list_prop):
                                self.response.set_status(400, f"Index {index} out of range")
                                return
                            list_prop[index] = parsed_value
                        else:
                            self.response.set_status(500, "List properties not supported")
                            return

                    elif action == "delete":
                        # Delete item
                        item_index = self.request.get("item_index")

                        if item_index is None:
                            self.response.set_status(400, "Missing item_index parameter")
                            return

                        try:
                            index = int(item_index)
                        except ValueError:
                            self.response.set_status(400, "Invalid item_index")
                            return

                        # Get the list property and delete
                        if myself and hasattr(myself, "property_lists"):
                            list_prop = getattr(myself.property_lists, prop_name)
                            if index < 0 or index >= len(list_prop):
                                self.response.set_status(400, f"Index {index} out of range")
                                return
                            del list_prop[index]
                        else:
                            self.response.set_status(500, "List properties not supported")
                            return

                    else:
                        self.response.set_status(400, f"Unknown action: {action}")
                        return

                    # Redirect back to the property page
                    self.response.set_status(302, "Found")
                    self.response.set_redirect(f"/{actor_id}/www/properties/{prop_name}")
                    return

                except Exception as e:
                    logger.error(f"Error in list item management: {e}")
                    self.response.set_status(500, f"Error processing list item: {str(e)}")
                    return

        # Initialize variables to avoid unbound issues
        property_name: str | None = None
        property_value: str | None = None
        property_type: str = "simple"
        
        if path == "properties":
            # Get form parameters
            property_name = self.request.get("property_name") or self.request.get("property")
            property_value = self.request.get("property_value") or self.request.get("value")
            property_type = self.request.get("property_type") or "simple"  # Default to simple

        elif "properties/" in path:
            property_name = path.split("/")[1]
            property_value = self.request.get("property_value") or self.request.get("value")
            property_type = "simple"  # Individual property updates are always simple
        # Handle property operations
        if property_name:
            try:
                # Handle list property creation
                if property_type == "list":
                    # Create empty list property
                    if myself and hasattr(myself, "property_lists") and myself.property_lists is not None:
                        # Check if list already exists using the proper interface
                        exists = myself.property_lists.exists(property_name)
                        if exists:
                            self.response.set_status(400, f"List property '{property_name}' already exists")
                            return

                        # Create empty list by accessing it (this initializes the ListProperty)
                        list_prop = getattr(myself.property_lists, property_name)
                        
                        # Initialize the list by ensuring metadata exists (this creates the list in the database)
                        _ = len(list_prop)  # This will trigger metadata creation if it doesn't exist

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
                                hook_result = self.hooks.execute_property_hooks(
                                    property_name, "post", actor_interface, [], [property_name]
                                )
                                if hook_result is None:
                                    self.response.set_status(403, "List property creation not allowed by hooks")
                                    return
                    else:
                        self.response.set_status(500, "List properties not supported")
                        return

                # Handle simple property operations
                elif property_type == "simple":
                    if not property_value:
                        # Missing value for simple property
                        self.response.set_status(400, "Property value is required for simple properties")
                        return

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

                else:
                    # Unknown property type
                    self.response.set_status(400, f"Unknown property type: {property_type}")
                    return

                # Redirect back to properties page or init page after successful creation
                self.response.set_status(302, "Found")
                redirect_path = self.request.get("redirect_to") or f"/{actor_id}/www/properties"
                self.response.set_redirect(redirect_path)
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
                    if isinstance(hook_result, str):
                        output = hook_result  # type: ignore[unreachable]
                    elif isinstance(hook_result, dict):
                        output = json.dumps(hook_result)  # type: ignore[unreachable]
                    else:
                        output = str(hook_result)

        if output:
            self.response.write(output)
        else:
            self.response.set_status(404, "Not found")
        return
