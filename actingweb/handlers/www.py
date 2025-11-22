# mypy: disable-error-code="unreachable,unused-ignore"
import json
import logging

from actingweb.handlers import base_handler

logger = logging.getLogger(__name__)


class WwwHandler(base_handler.BaseHandler):
    def _get_consistent_urls(self, actor_id: str) -> dict[str, str]:
        """
        Get consistent URL variables for templates using config.root.
        Returns a dictionary with standardized URL paths that work across all pages.

        The config.fqdn may contain a base path like "demo.actingweb.io/base",
        and config.root is constructed as proto + fqdn + "/".

        Returns:
            Dict containing:
            - 'actor_root': Actor root path like /base/actor_id (no trailing slash)
            - 'actor_www': Actor www path like /base/actor_id/www (no trailing slash)
            - 'url': Backwards compatible URL (typically actor_www)

        Raises:
            RuntimeError: If calculated base path doesn't match config.root
        """
        if not self.config or not hasattr(self.config, "root") or not self.config.root:
            raise RuntimeError("Config object with root property is required")

        # Extract base path from config.root
        # config.root format: "https://demo.actingweb.io/base/"
        from urllib.parse import urlparse

        parsed_root = urlparse(self.config.root)
        base_path = parsed_root.path.rstrip("/")  # Remove trailing slash: "/base" or ""

        # Validate against current request URL if available for debugging
        if hasattr(self.request, "url") and self.request.url:
            try:
                parsed_request = urlparse(self.request.url)
                request_parts = parsed_request.path.strip("/").split("/")

                # Find actor_id in request path to validate base path
                if actor_id in request_parts:
                    actor_index = request_parts.index(actor_id)
                    detected_base_parts = request_parts[:actor_index]
                    detected_base = (
                        "/" + "/".join(detected_base_parts)
                        if detected_base_parts
                        else ""
                    )

                    # Validate that detected base matches config
                    if detected_base != base_path:
                        logger.error(
                            f"Base path mismatch: config.root indicates '{base_path}' but request URL indicates '{detected_base}'. "
                            f"Config.fqdn='{self.config.fqdn}', config.root='{self.config.root}', request.url='{self.request.url}'"
                        )
                        raise RuntimeError(
                            f"Base path mismatch: config.fqdn '{self.config.fqdn}' should match request path. "
                            f"Expected base '{base_path}' but detected '{detected_base}'"
                        )

                    logger.debug(
                        f"Base path validation successful: '{base_path}' matches request URL"
                    )
            except (ValueError, IndexError, AttributeError) as e:
                logger.debug(f"Could not validate base path from request URL: {e}")

        # Build URLs using config-derived base path
        actor_root = f"{base_path}/{actor_id}" if base_path else f"/{actor_id}"

        return {
            "actor_root": actor_root,
            "actor_www": f"{actor_root}/www",
            "url": f"{actor_root}/www",  # Backwards compatible - points to www
        }

    def get(self, actor_id: str, path: str) -> None:
        myself = self.require_authenticated_actor(actor_id, "www", "GET", path)
        if not myself:
            return
        if not self.config.ui:
            if self.response:
                self.response.set_status(404, "Web interface is not enabled")
            return

        if not path or path == "":
            # Use consistent URL calculation
            urls = self._get_consistent_urls(actor_id)

            self.response.template_values = {
                "url": urls["url"],
                "actor_root": urls["actor_root"],
                "actor_www": urls["actor_www"],
                "id": actor_id,
                "creator": myself.creator,
                "passphrase": myself.passphrase,
            }
            return

        if path == "init":
            # Use consistent URL calculation
            urls = self._get_consistent_urls(actor_id)

            self.response.template_values = {
                "id": myself.id,
                "url": urls["url"],
                "actor_root": urls["actor_root"],
                "actor_www": urls["actor_www"],
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
                                prop_name,
                                "put",
                                actor_interface,
                                prop_value,
                                [prop_name],
                            )
                            if put_test is None:
                                # PUT operation is blocked, so this property is read-only
                                read_only_properties.add(prop_name)
                    properties = filtered_properties

            # Check for list properties and prepare special display values
            display_properties = {}
            all_properties = properties.copy() if properties else {}

            # Discover standalone list properties using the proper interface
            if (
                myself
                and hasattr(myself, "property_lists")
                and myself.property_lists is not None
            ):
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
                        display_properties[prop_name] = (
                            f"[List with {list_length} items]"
                        )
                    except Exception as e:
                        logger.error(
                            f"Error getting length for list property '{prop_name}': {e}"
                        )
                        display_properties[prop_name] = "[List property]"
                else:
                    # Regular property - use original value
                    display_properties[prop_name] = prop_value

            # Debug logging
            logger.debug(
                f"Template values - properties: {list((display_properties or properties).keys())}"
            )
            logger.debug(f"Template values - list_properties: {list(list_properties)}")

            # Use consistent URL calculation
            urls = self._get_consistent_urls(actor_id)

            self.response.template_values = {
                "id": myself.id,
                "properties": display_properties or properties,
                "read_only_properties": read_only_properties,
                "list_properties": list_properties,
                "url": urls["url"],
                "actor_root": urls["actor_root"],
                "actor_www": urls["actor_www"],
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
            lookup = (
                myself.property[prop_name] if prop_name and myself.property else None
            )
            method_override = (
                self.request.params.get("_method", None)
                if self.request.params
                else None
            )
            if method_override and method_override.upper() == "DELETE":
                # Execute property delete hook first to check if deletion is allowed
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        hook_result = self.hooks.execute_property_hooks(
                            prop_name,
                            "delete",
                            actor_interface,
                            lookup or {},
                            [prop_name],
                        )
                        if hook_result is None:
                            # Hook rejected the deletion - return 403 Forbidden
                            self.response.set_status(
                                403, "Property deletion not allowed"
                            )
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
                        self.response.set_status(
                            500, f"Error deleting list property: {str(e)}"
                        )
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
                        prop_name or "*",
                        "get",
                        actor_interface,
                        lookup or {},
                        prop_path,
                    )
                    if hook_result is None:
                        # Hook indicates property should not be accessible (hidden)
                        self.response.set_status(404, "Property not found")
                        return
                    else:
                        lookup = hook_result
            # Use consistent URL calculation
            urls = self._get_consistent_urls(actor_id)

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
                    if (
                        myself.property
                        and hasattr(myself.property, "_config")
                        and myself.property._config is not None
                    ):
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

            # Always populate template values; handle list vs. simple explicitly
            if is_list_property:
                logger.debug(
                    f"Template variables for {prop_name}: is_list_property=True, list_items_count={len(list_items) if list_items is not None else 0}"
                )
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": display_value or "",
                    "raw_value": lookup or "",
                    "qual": "a",
                    "url": urls["actor_www"],
                    "actor_root": urls["actor_root"],
                    "actor_www": urls["actor_www"],
                    "is_read_only": is_read_only,
                    "is_list_property": True,
                    "list_items": list_items or [],
                    "list_description": list_description,
                    "list_explanation": list_explanation,
                }
            elif lookup is not None:
                logger.debug(
                    f"Template variables for {prop_name}: is_list_property=False"
                )
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": display_value,
                    "raw_value": lookup,
                    "qual": "a",
                    "url": urls["actor_www"],
                    "actor_root": urls["actor_root"],
                    "actor_www": urls["actor_www"],
                    "is_read_only": is_read_only,
                    "is_list_property": False,
                    "list_items": [],
                    "list_description": "",
                    "list_explanation": "",
                }
            else:
                # Property not found
                self.response.template_values = {
                    "id": myself.id,
                    "property": prop_name,
                    "value": "",
                    "raw_value": "",
                    "qual": "n",
                    "url": urls["actor_www"],
                    "actor_root": urls["actor_root"],
                    "actor_www": urls["actor_www"],
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

            # Sort by last_connected_at (most recent first), fallback to created_at if no last connection
            def get_sort_key(trust):
                if isinstance(trust, dict):
                    # Try last_connected_at, then last_accessed, then created_at, then empty string
                    return (
                        trust.get("last_connected_at")
                        or trust.get("last_accessed")
                        or trust.get("created_at")
                        or ""
                    )
                else:
                    # Object-like access
                    return (
                        getattr(trust, "last_connected_at", None)
                        or getattr(trust, "last_accessed", None)
                        or getattr(trust, "created_at", None)
                        or ""
                    )

            # Sort in descending order (most recent first)
            relationships = sorted(relationships, key=get_sort_key, reverse=True)

            # Build approve URIs and check for custom permissions
            connection_metadata: list[dict[str, str | None]] = []
            for t in relationships:
                if isinstance(t, dict):
                    rel = t.get("relationship", "")
                    peerid = t.get("peerid", "")
                    t["approveuri"] = (
                        f"{self.config.root}{myself.id or ''}/trust/{rel}/{peerid}"
                    )

                    # Check if this relationship has custom permissions
                    t["has_custom_permissions"] = self._has_custom_permissions(
                        myself.id or "", peerid
                    )

                    connection_metadata.append(
                        {
                            "peerid": peerid,
                            "established_via": t.get("established_via"),
                            "created_at": t.get("created_at"),
                            "last_connected_at": t.get("last_connected_at")
                            or t.get("last_accessed")
                            or t.get("created_at"),
                            "last_connected_via": t.get("last_connected_via"),
                        }
                    )
                else:
                    # Fallback for object-like items
                    rel = getattr(t, "relationship", "")
                    peerid = getattr(t, "peerid", "")
                    try:
                        t.approveuri = (
                            f"{self.config.root}{myself.id or ''}/trust/{rel}/{peerid}"
                        )
                        t.has_custom_permissions = self._has_custom_permissions(
                            myself.id or "", peerid
                        )
                    except Exception:
                        pass

                    connection_metadata.append(
                        {
                            "peerid": peerid,
                            "established_via": getattr(t, "established_via", None),
                            "created_at": getattr(t, "created_at", None),
                            "last_connected_at": getattr(t, "last_connected_at", None)
                            or getattr(t, "last_accessed", None)
                            or getattr(t, "created_at", None),
                            "last_connected_via": getattr(
                                t, "last_connected_via", None
                            ),
                        }
                    )

            # Get OAuth2 clients for this actor
            oauth_clients = self._get_oauth_clients_for_actor(actor_id)

            # Enrich OAuth2 client trust relationships with client metadata if missing
            if oauth_clients:
                client_index = {
                    client.get("client_id"): client
                    for client in oauth_clients
                    if client.get("client_id")
                }

                for rel in relationships:
                    if not isinstance(rel, dict):
                        continue

                    if rel.get("established_via") != "oauth2_client":
                        continue

                    peer_identifier = rel.get("peer_identifier")
                    stored_client_id = rel.get("oauth_client_id") or peer_identifier
                    client_info = client_index.get(stored_client_id)

                    if client_info:
                        if not rel.get("oauth_client_id"):
                            rel["oauth_client_id"] = client_info.get("client_id")

                        if not rel.get("client_name") and client_info.get(
                            "client_name"
                        ):
                            rel["client_name"] = client_info.get("client_name")

                        # Refresh description when it still references the raw identifier
                        desc = (rel.get("desc") or "").strip()
                        if desc.lower() == f"oauth2 client: {peer_identifier}".lower():
                            friendly = client_info.get("client_name")
                            if friendly:
                                rel["desc"] = f"OAuth2 client: {friendly}"

            # Use consistent URL calculation
            urls = self._get_consistent_urls(actor_id)

            self.response.template_values = {
                "id": myself.id,
                "trusts": relationships,
                "oauth_clients": oauth_clients,
                "trust_connections": connection_metadata,
                "url": f"{urls['actor_root']}/",
                "actor_root": urls["actor_root"],
                "actor_www": urls["actor_www"],
            }
            return

        if path == "trust/new":
            # Use consistent URL calculation
            urls = self._get_consistent_urls(actor_id)
            # Add new trust relationship form
            available_trust_types = self._get_available_trust_types()

            # Check if trust types are properly configured
            trust_types_error = None
            if not available_trust_types:
                trust_types_error = "Trust types are not properly configured. Cannot create trust relationships."

            self.response.template_values = {
                "id": myself.id,
                "url": f"{urls['actor_root']}/",
                "actor_root": urls["actor_root"],
                "actor_www": urls["actor_www"],
                "form_action": f"{urls['actor_root']}/www/trust/new",
                "form_method": "POST",
                "trust_types": available_trust_types,
                "error": trust_types_error,
                "default_relationship": self.config.default_relationship,
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

    def _has_custom_permissions(self, actor_id: str, peer_id: str) -> bool:
        """Check if a trust relationship has custom permission overrides."""
        if not actor_id or not peer_id:
            return False

        try:
            # Import permission system with fallback
            from ..trust_permissions import get_trust_permission_store

            permission_store = get_trust_permission_store(self.config)
            permissions = permission_store.get_permissions(actor_id, peer_id)
            return permissions is not None
        except Exception:
            # If permission system is not available or there's an error, assume no custom permissions
            return False

    def _get_available_trust_types(self) -> list[dict[str, str]]:
        """Get available trust types for trust relationship creation."""
        try:
            from ..trust_type_registry import get_registry

            registry = get_registry(self.config)
            trust_types = registry.list_types()

            # Convert to list of dicts for template use
            available_types = []
            for trust_type in trust_types:
                available_types.append(
                    {
                        "name": trust_type.name,
                        "display_name": trust_type.display_name,
                        "description": trust_type.description,
                    }
                )

            return available_types

        except Exception as e:
            logging.error(f"Error accessing trust type registry: {e}")
            # No fallback - this is a configuration error that should be fixed
            return []

    def _get_oauth_clients_for_actor(self, actor_id: str) -> list[dict[str, str]]:
        """Get registered OAuth2 clients for an actor."""
        try:
            from ..interface.oauth_client_manager import OAuth2ClientManager

            # Use the high-level OAuth2ClientManager interface
            client_manager = OAuth2ClientManager(actor_id, self.config)
            clients = client_manager.list_clients()

            # OAuth2ClientManager provides pre-formatted data ready for templates
            # Just need to map the field names to match template expectations
            processed_clients = []
            for client in clients:
                processed_client = {
                    "client_id": client.get("client_id", ""),
                    "client_name": client.get("client_name", "Unknown Client"),
                    "trust_type": client.get("trust_type", "mcp_client"),
                    "created_at": client.get("created_at_formatted", "Recently"),
                    "status": client.get("status", "active"),
                }
                processed_clients.append(processed_client)

            return processed_clients

        except Exception as e:
            logging.error(f"Error getting OAuth2 clients for actor {actor_id}: {e}")
            return []

    def _handle_new_trust_relationship(self, myself, actor_id: str) -> None:
        """Handle creation of a new trust relationship."""
        peer_url = self.request.get("peer_url")
        relationship = (
            self.request.get("relationship") or self.config.default_relationship
        )
        trust_type = self.request.get("trust_type") or ""
        description = self.request.get("description") or ""

        if not peer_url:
            self.response.set_status(400, "Peer URL is required")
            self.response.write("Error: Peer URL is required")
            return

        # Validate relationship name length
        if (
            relationship and len(relationship) > 100
        ):  # Reasonable length limit for human-readable names
            self.response.set_status(400, "Relationship name too long")
            self.response.write(
                "Error: Relationship name must be 100 characters or less"
            )
            return

        # Normalize URL (add https:// if missing)
        if not peer_url.startswith(("http://", "https://")):
            peer_url = "https://" + peer_url

        # Remove trailing slash
        peer_url = peer_url.rstrip("/")

        # Validate that trust type is provided
        if not trust_type:
            self.response.set_status(400, "Trust type is required")
            self.response.write("Error: Trust type is required")
            return

        try:
            # Create reciprocal trust relationship
            # The 'relationship' parameter in create_reciprocal_trust is the trust type requested from peer
            secret = self.config.new_token()
            new_trust = myself.create_reciprocal_trust(
                url=peer_url,
                secret=secret,
                desc=description,
                relationship=trust_type,  # Trust type requested from peer (goes in URL)
                trust_type="",  # Empty allows any mini-application type - trust registry type is separate
            )

            # TODO: Store human-readable relationship name separately if different from trust_type
            # For now, the relationship field will contain the trust type used in the protocol

            if new_trust:
                # Success - redirect back to trust page
                self.response.set_status(302, "Found")
                self.response.set_redirect(f"/{actor_id}/www/trust")
            else:
                self.response.set_status(400, "Failed to create trust relationship")
                self.response.write(
                    "Error: Unable to create trust relationship. Please check the peer URL and try again."
                )

        except Exception as e:
            logging.error(f"Error creating trust relationship: {e}")
            self.response.set_status(500, "Internal Server Error")
            self.response.write(f"Error: {str(e)}")

    def post(self, actor_id: str, path: str) -> None:
        """Handle POST requests for web UI property operations."""
        myself = self.require_authenticated_actor(actor_id, "www", "POST", path)
        if not myself:
            return
        if not self.config.ui:
            if self.response:
                self.response.set_status(404, "Web interface is not enabled")
            return

        # Handle trust relationship creation
        if path == "trust/new":
            self._handle_new_trust_relationship(myself, actor_id)
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

                    if (
                        myself
                        and hasattr(myself, "property_lists")
                        and myself.property_lists is not None
                        and myself.property_lists.exists(prop_name)
                    ):
                        try:
                            list_prop = getattr(myself.property_lists, prop_name)

                            if description is not None:
                                list_prop.set_description(description)
                            if explanation is not None:
                                list_prop.set_explanation(explanation)

                            # Redirect back to the property page
                            self.response.set_status(302, "Found")
                            self.response.set_redirect(
                                f"/{actor_id}/www/properties/{prop_name}"
                            )
                            return

                        except Exception as e:
                            logger.error(
                                f"Error updating list metadata for '{prop_name}': {e}"
                            )
                            self.response.set_status(
                                500, f"Error updating list metadata: {str(e)}"
                            )
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
                        logger.debug(
                            f"List item add request - prop_name: {prop_name}, item_value: {item_value}"
                        )

                        if not item_value:
                            self.response.set_status(
                                400, "Missing item_value parameter"
                            )
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
                            self.response.set_status(
                                500, "List properties not supported"
                            )
                            return

                    elif action == "update":
                        # Update existing item
                        item_index = self.request.get("item_index")
                        item_value = self.request.get("item_value")

                        if item_index is None or item_value is None:
                            self.response.set_status(
                                400, "Missing item_index or item_value parameter"
                            )
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
                                self.response.set_status(
                                    400, f"Index {index} out of range"
                                )
                                return
                            list_prop[index] = parsed_value
                        else:
                            self.response.set_status(
                                500, "List properties not supported"
                            )
                            return

                    elif action == "delete":
                        # Delete item
                        item_index = self.request.get("item_index")

                        if item_index is None:
                            self.response.set_status(
                                400, "Missing item_index parameter"
                            )
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
                                self.response.set_status(
                                    400, f"Index {index} out of range"
                                )
                                return
                            del list_prop[index]
                        else:
                            self.response.set_status(
                                500, "List properties not supported"
                            )
                            return

                    else:
                        self.response.set_status(400, f"Unknown action: {action}")
                        return

                    # Redirect back to the property page
                    self.response.set_status(302, "Found")
                    self.response.set_redirect(
                        f"/{actor_id}/www/properties/{prop_name}"
                    )
                    return

                except Exception as e:
                    logger.error(f"Error in list item management: {e}")
                    self.response.set_status(
                        500, f"Error processing list item: {str(e)}"
                    )
                    return

        # Initialize variables to avoid unbound issues
        property_name: str | None = None
        property_value: str | None = None
        property_type: str = "simple"

        if path == "properties":
            # Get form parameters
            property_name = self.request.get("property_name") or self.request.get(
                "property"
            )
            property_value = self.request.get("property_value") or self.request.get(
                "value"
            )
            property_type = (
                self.request.get("property_type") or "simple"
            )  # Default to simple

        elif "properties/" in path:
            property_name = path.split("/")[1]
            property_value = self.request.get("property_value") or self.request.get(
                "value"
            )
            property_type = "simple"  # Individual property updates are always simple
        # Handle property operations
        if property_name:
            try:
                # Handle list property creation
                if property_type == "list":
                    # Create empty list property
                    if (
                        myself
                        and hasattr(myself, "property_lists")
                        and myself.property_lists is not None
                    ):
                        # Check if list already exists using the proper interface
                        exists = myself.property_lists.exists(property_name)
                        if exists:
                            self.response.set_status(
                                400, f"List property '{property_name}' already exists"
                            )
                            return

                        # Create empty list by accessing it (this initializes the ListProperty)
                        list_prop = getattr(myself.property_lists, property_name)

                        # Initialize the list by ensuring metadata exists (this creates the list in the database)
                        _ = len(
                            list_prop
                        )  # This will trigger metadata creation if it doesn't exist

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
                                    property_name,
                                    "post",
                                    actor_interface,
                                    [],
                                    [property_name],
                                )
                                if hook_result is None:
                                    self.response.set_status(
                                        403,
                                        "List property creation not allowed by hooks",
                                    )
                                    return
                    else:
                        self.response.set_status(500, "List properties not supported")
                        return

                # Handle simple property operations
                elif property_type == "simple":
                    if not property_value:
                        # Missing value for simple property
                        self.response.set_status(
                            400, "Property value is required for simple properties"
                        )
                        return

                    # Create or update property
                    old_value = (
                        myself.property[property_name] if myself.property else None
                    )
                    is_new_property = old_value is None

                    # Execute property hooks before setting the property
                    final_value = property_value
                    if self.hooks:
                        actor_interface = self._get_actor_interface(myself)
                        if actor_interface:
                            hook_action = "post" if is_new_property else "put"
                            hook_result = self.hooks.execute_property_hooks(
                                property_name,
                                hook_action,
                                actor_interface,
                                property_value,
                                [property_name],
                            )
                            if hook_result is None:
                                self.response.set_status(
                                    403, "Property value not accepted by hooks"
                                )
                                return
                            final_value = hook_result

                    # Set the property with the potentially transformed value
                    if not myself.property:
                        self.response.set_status(
                            500, "PropertyStore is not initialized"
                        )
                        return
                    myself.property[property_name] = final_value

                else:
                    # Unknown property type
                    self.response.set_status(
                        400, f"Unknown property type: {property_type}"
                    )
                    return

                # Redirect back to properties page or init page after successful creation
                self.response.set_status(302, "Found")
                redirect_path = (
                    self.request.get("redirect_to") or f"/{actor_id}/www/properties"
                )
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
