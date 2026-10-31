# mypy: disable-error-code="unreachable,unused-ignore"
import json
import logging
from typing import Any

from actingweb.db import get_property
from actingweb.handlers import base_handler
from actingweb.property_list import (
    ListCorruptionError,
    ListItemSpanError,
    ListItemTooLargeError,
    ListMetadataContentionError,
)

from ..db.exceptions import DbError
from ..trust import is_valid_peer_baseuri

logger = logging.getLogger(__name__)


class WwwHandler(base_handler.BaseHandler):
    def _list_action_error(self, status: int, message: str) -> None:
        """Answer a list item action with ``status`` and the reason on a
        small HTML page (phone-width viewport, a link back to the list), so
        a browser shows why instead of a blank page. The reason is escaped
        and never carries item content."""
        import html

        back = getattr(self, "_list_back", None)
        # "Your text is kept" only where the form had text: add and update.
        typed = self.request.get("action") in ("add", "update")
        link = (
            f'<p><a href="{html.escape(back)}" '
            'onclick="if (history.length > 1) { history.back(); return false; }">'
            f"Back</a>{' (your text is kept)' if typed else ''} or "
            f'<a href="{html.escape(back)}">go to the list</a></p>'
            if back
            else ""
        )
        self.response.set_status(status, message)
        self.response.headers["Content-Type"] = "text/html; charset=utf-8"
        self.response.write(
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{status}</title><style>body{{font-family:system-ui,sans-serif;"
            "max-width:40rem;margin:2rem auto;padding:0 1rem;line-height:1.5}"
            f"</style></head><body><p>{html.escape(message)}</p>"
            f"{link}</body></html>"
        )

    def _list_page_items(
        self, list_prop: Any
    ) -> tuple[list[Any], list[dict[str, Any]], dict[str, Any] | None]:
        """The list page's items: ``(list_items, list_entries, edit_entry)``.

        A v2 list is read heads only (``resolve=False``): a spanned item's
        bodies are never read for the listing, and its slot in
        ``list_items`` holds ``UNRESOLVED``. Each entry carries the item's
        index, rank, a digest of its raw value (the forms post both, so a
        stale page cannot act on a different item), its size, whether it
        spans, and its JSON with key order and non-ASCII kept (``None`` for
        a spanned item). ``?edit=<rank>`` loads that one item fresh, whole,
        as ``edit_entry``. A v1 list is read as before, with positional
        entries (no rank).
        """
        from actingweb.property_list import UNRESOLVED
        from actingweb.property_list_span import encoded_size, value_digest

        def as_json(item: Any) -> str:
            return json.dumps(item, ensure_ascii=False)

        if list_prop.storage_format() != 2:
            items = list_prop.to_list()
            v1_entries = [
                {
                    "index": i,
                    "rank": None,
                    # A v1 item is addressed by position; the digest of its
                    # JSON lets an action refuse when the position now holds
                    # a different item.
                    "digest": value_digest(json.dumps(item)),
                    "spanned": False,
                    "bytes": encoded_size(json.dumps(item)),
                    "json": as_json(item),
                    "text": item if isinstance(item, str) else None,
                }
                for i, item in enumerate(items)
            ]
            # A v1 list has no ranks: an item is edited by its position,
            # which is what a v1 list's identity is.
            v1_edit: dict[str, Any] | None = None
            edit_index = self.request.get("edit_index")
            if (
                edit_index.isascii()
                and edit_index.isdigit()
                and int(edit_index) < len(v1_entries)
            ):
                v1_edit = dict(v1_entries[int(edit_index)])
            return items, v1_entries, v1_edit
        pairs = list_prop.items_with_handles(resolve=False)
        items = [item for _, item in pairs]
        entries = []
        edit_rank = self.request.get("edit") or None
        edit_entry: dict[str, Any] | None = None
        for i, (handle, item) in enumerate(pairs):
            unresolved = item is UNRESOLVED
            entry = {
                "index": i,
                "rank": handle.rank,
                "digest": value_digest(handle.raw_value),
                "spanned": handle.spanned,
                "bytes": handle.bytes
                if handle.spanned and handle.bytes is not None
                else encoded_size(json.dumps(item))
                if not unresolved
                else None,
                "json": None if unresolved else as_json(item),
                # A string item previews as its text, as its edit form shows it.
                "text": item if isinstance(item, str) else None,
            }
            entries.append(entry)
            if edit_rank is not None and handle.rank == edit_rank:
                fresh, full = list_prop.item_at(handle)
                edit_entry = {
                    **entry,
                    "digest": value_digest(fresh.raw_value),
                    "json": as_json(full),
                    # A string item is edited as its text, not as quoted
                    # JSON (the add form takes plain text too).
                    "text": full if isinstance(full, str) else None,
                }
        return items, entries, edit_entry

    def _list_is_read_only(
        self, myself: Any, prop_name: str, value: Any = None
    ) -> bool:
        """The read-only rule for a property page and its write actions: a
        put hook that rejects the property (probed with its current value,
        or ``{}``) makes it read-only. One rule for the page and the
        actions, so they cannot disagree."""
        if not self.hooks:
            return False
        actor_interface = self._get_actor_interface(myself)
        if not actor_interface:
            return False
        return (
            self.hooks.execute_property_hooks(
                prop_name, "put", actor_interface, value or {}, [prop_name]
            )
            is None
        )

    def _trust_uri(self, actor_id: str, relationship: str, peerid: str) -> str:
        """The trust row's URL, with the relationship and peer id quoted as
        path segments: a stored id from before 3.16 may hold characters
        (``/``, ``?``, ``.``) that would point the link somewhere else."""
        from urllib.parse import quote

        def segment(value: str, safe: str) -> str:
            quoted = quote(value, safe=safe)
            # A dot segment would be resolved away by the browser.
            return quoted.replace(".", "%2E") if quoted in (".", "..") else quoted

        return (
            f"{self.config.root}{actor_id}/trust/"
            f"{segment(str(relationship), '')}/{segment(str(peerid), ':@')}"
        )

    def _v1_item_changed(self, list_prop: Any, index: int) -> bool:
        """For a v1 list action that posted ``item_digest``: True when the
        item at ``index`` is no longer the one the page showed (a v1 list
        has no ranks; the digest is its stale-page guard), including when the
        position is now past the end. Best effort: the check and the write
        are two steps, and without ``item_digest`` there is no check."""
        from actingweb.property_list_span import value_digest

        digest = self.request.get("item_digest") or None
        if digest is None:
            return False
        try:
            current = list_prop[index]
        except IndexError:
            # The page showed an item at this position; it is gone now.
            return True
        return value_digest(json.dumps(current)) != digest

    def _list_target(self, list_prop: Any, index: int | None) -> tuple[Any, str | None]:
        """The handle a v2 item action writes through, and an error to
        answer instead. With ``item_rank`` (and ``item_digest``) posted, the
        item is the one the page showed: missing or changed since is a 409,
        never a different item at the same position. Without them, the
        position as before."""
        from actingweb.property_list_span import value_digest

        rank = self.request.get("item_rank") or None
        digest = self.request.get("item_digest") or None
        pairs = list_prop.items_with_handles(resolve=False)
        if rank is not None:
            for handle, _ in pairs:
                if handle.rank == rank:
                    if digest is not None and value_digest(handle.raw_value) != digest:
                        return None, "changed"
                    return handle, None
            return None, "changed"
        if index is None or index < 0 or index >= len(pairs):
            return None, "range"
        return pairs[index][0], None

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

            # Discover standalone list properties using the proper interface.
            # list_all_with_rows() pays for exactly one whole-partition dump
            # -- the same one list_all() alone already paid for and
            # discarded -- and the rows below serve every list's length
            # from that dump instead of a whole-list Query + an exists()
            # GetItem per list property.
            list_names: list[str] = []
            list_rows: dict[str, str] = {}
            if (
                myself
                and hasattr(myself, "property_lists")
                and myself.property_lists is not None
            ):
                list_names, list_rows = myself.property_lists.list_all_with_rows()
                logger.debug(f"Found list properties: {list_names}")
                for list_name in list_names:
                    if list_name not in all_properties:
                        # This is a standalone list property
                        all_properties[list_name] = None  # Placeholder value

            list_name_set = set(list_names)

            # Process all properties (regular + list)
            for prop_name, prop_value in all_properties.items():
                if prop_name in list_name_set:
                    # This is a list property
                    list_properties.add(prop_name)
                    try:
                        list_prop = getattr(myself.property_lists, prop_name)
                        list_prop.prime_from_rows(list_rows)
                        list_length = len(list_prop)
                        display_properties[prop_name] = (
                            f"[List with {list_length} items]"
                        )
                    except DbError:
                        raise
                    except Exception as e:
                        logger.error(
                            f"Error getting length for list property '{prop_name}': {e}"
                        )
                        display_properties[prop_name] = "[List property]"
                else:
                    # Regular property - use original value
                    display_properties[prop_name] = prop_value

            # Debug logging
            final_properties = (
                display_properties if display_properties else (properties or {})
            )
            logger.debug(
                f"Template values - properties: {list(final_properties.keys())}"
            )
            logger.debug(f"Template values - list_properties: {list(list_properties)}")

            # Use consistent URL calculation
            urls = self._get_consistent_urls(actor_id)

            self.response.template_values = {
                "id": myself.id,
                "properties": final_properties,
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
            if method_override and self._refuse_cross_site_override():
                # A link or image on another site must not delete or change
                # anything: SameSite=Lax cookies ride along on a top-level
                # GET, and cached basic-auth credentials on any request.
                return
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

                        # Register diff for subscription callbacks
                        myself.register_diffs(
                            target="properties", subtarget=prop_name, blob=""
                        )
                        deleted = True
                    except DbError:
                        raise
                    except Exception as e:
                        logger.error(f"Error deleting list property '{prop_name}': {e}")
                        self.response.set_status(
                            500, f"Error deleting list property: {str(e)}"
                        )
                        return

                elif lookup and myself.property:
                    # This is a regular property
                    myself.property[prop_name] = None
                    # Register diff for subscription callbacks
                    myself.register_diffs(
                        target="properties", subtarget=prop_name, blob=""
                    )
                    deleted = True

                if deleted:
                    # Redirect back to properties page
                    self.response.set_status(302, "Found")
                    self.response.set_redirect(self._www_path(actor_id, "/properties"))
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
            if self._list_is_read_only(myself, prop_name, lookup):
                is_read_only = True

            # Check if this is a list property and prepare appropriate display value
            display_value = lookup
            list_items = None
            list_entries: list[dict[str, Any]] = []
            list_error = ""
            edit_entry: dict[str, Any] | None = None
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
                    list_prop = getattr(myself.property_lists, prop_name)
                    list_items, list_entries, edit_entry = self._list_page_items(
                        list_prop
                    )
                    list_length = len(list_items)

                    # Get description and explanation
                    list_description = list_prop.get_description()
                    list_explanation = list_prop.get_explanation()

                    # For display, show summary
                    display_value = f"List with {list_length} items"

                except ListCorruptionError as e:
                    logger.error(f"List '{prop_name}' is corrupted: {e}")
                    display_value = (
                        "[List property is corrupted -- run "
                        "verify()/compact() to repair]"
                    )
                    list_error = str(e)
                    list_items = []
                except DbError:
                    raise
                except Exception as e:
                    logger.error(f"Error loading list items for '{prop_name}': {e}")
                    display_value = "[List property - error loading items]"
                    list_error = "The list's items could not be loaded"
                    list_items = []

            elif lookup is not None:
                try:
                    # Check if this property is an old-style distributed list by looking for metadata
                    if (
                        myself.property
                        and hasattr(myself.property, "_config")
                        and myself.property._config is not None
                    ):
                        db = get_property(myself.property._config)
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
                except DbError:
                    raise
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
                    "list_entries": list_entries,
                    "list_error": list_error,
                    "edit_entry": edit_entry,
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
                    t["approveuri"] = self._trust_uri(myself.id or "", rel, peerid)
                    # A link to the peer only for a plain http(s) base URL:
                    # the value came from the peer.
                    baseuri = t.get("baseuri") or ""
                    t["peer_link"] = baseuri if is_valid_peer_baseuri(baseuri) else ""

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
                        t.approveuri = self._trust_uri(myself.id or "", rel, peerid)
                        t.has_custom_permissions = self._has_custom_permissions(
                            myself.id or "", peerid
                        )
                    except DbError:
                        raise
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
                    # Check if hook wants to render a template
                    if isinstance(hook_result, dict) and "template" in hook_result:
                        # Hook returned template rendering request
                        # Set template values for Flask integration to render
                        template_data = hook_result.get("data", {})
                        # Use consistent URL calculation
                        urls = self._get_consistent_urls(actor_id)
                        self.response.template_values = {
                            "id": actor_id,
                            "url": urls["url"],
                            "actor_root": urls["actor_root"],
                            "actor_www": urls["actor_www"],
                            **template_data,
                        }
                        # Store template name for integration to use
                        self.response.template_name = hook_result.get("template")
                        return
                    elif isinstance(hook_result, str):
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
        except DbError:
            raise
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

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error accessing trust type registry: {e}")
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

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error getting OAuth2 clients for actor {actor_id}: {e}")
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
                self.response.set_redirect(self._www_path(actor_id, "/trust"))
            else:
                self.response.set_status(400, "Failed to create trust relationship")
                self.response.write(
                    "Error: Unable to create trust relationship. Please check the peer URL and try again."
                )

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error creating trust relationship: {e}")
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
        # Every web UI mutation: refuse a cross-site form post (see
        # _cross_site_refused).
        if self._refuse_cross_site():
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
                                self._www_path(actor_id, f"/properties/{prop_name}")
                            )
                            return

                        except DbError:
                            raise
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
                self._list_back = self._www_path(actor_id, f"/properties/{prop_name}")

                if not action:
                    self._list_action_error(400, "Missing action parameter")
                    return

                try:
                    read_only = action in (
                        "add",
                        "update",
                        "delete",
                    ) and self._list_is_read_only(myself, prop_name)
                except DbError:
                    raise
                except (
                    Exception
                ) as e:  # folds DbError: re-raised above; a hook bug answers 500
                    logger.error(f"Read-only check failed for '{prop_name}': {e}")
                    self._list_action_error(500, "Error processing list item")
                    return
                if read_only:
                    self._list_action_error(403, f"List '{prop_name}' is read-only")
                    return

                try:
                    if action == "add":
                        # Add new item to list
                        # A textarea posts line breaks as CRLF; the web UI
                        # stores them as LF, for add and update alike.
                        item_value = self.request.get("item_value").replace(
                            "\r\n", "\n"
                        )
                        logger.debug(
                            f"List item add request - prop_name: {prop_name}, item_value: {item_value}"
                        )

                        if not item_value or not item_value.strip():
                            self._list_action_error(
                                400, "The item is empty; nothing was added"
                            )
                            return

                        # Try to parse as JSON, fall back to string
                        try:
                            parsed_value = json.loads(item_value)
                            logger.debug(f"Parsed item_value as JSON: {parsed_value}")
                        except json.JSONDecodeError:
                            parsed_value = item_value
                            logger.debug(f"Using item_value as string: {parsed_value}")

                        # Get the list property and append. No length
                        # logging here: under v2 len() is a whole-list
                        # range query, and Python evaluates an f-string's
                        # interpolation before logger.debug() checks the
                        # level, so those calls ran in production with
                        # DEBUG off -- three whole-list reads for what
                        # should be one point write.
                        if myself and hasattr(myself, "property_lists"):
                            logger.debug(f"Getting list property: {prop_name}")
                            list_prop = getattr(myself.property_lists, prop_name)
                            list_prop.append(parsed_value)
                        else:
                            logger.error("List properties not supported")
                            self._list_action_error(
                                500, "List properties not supported"
                            )
                            return

                    elif action == "update":
                        # Update existing item
                        item_index = self.request.get("item_index") or None
                        # A textarea posts line breaks as CRLF; the web UI
                        # stores them as LF, for add and update alike.
                        item_value = self.request.get("item_value").replace(
                            "\r\n", "\n"
                        )

                        # An empty value is refused like add's: an empty form
                        # field must not silently blank the item.
                        has_rank = bool(self.request.get("item_rank"))
                        if item_index is None and not has_rank:
                            self._list_action_error(
                                400, "Missing item_index or item_rank parameter"
                            )
                            return
                        if not (item_value and item_value.strip()):
                            self._list_action_error(
                                400, "The item is empty; nothing was saved"
                            )
                            return

                        try:
                            index = int(item_index) if item_index is not None else None
                        except ValueError:
                            self._list_action_error(400, "Invalid item_index")
                            return

                        # Try to parse as JSON, fall back to string -- except
                        # when the form says the value is JSON (the edit
                        # form): a typo there must not silently turn an
                        # object into a string.
                        item_format = self.request.get("item_format")
                        try:
                            if item_format == "text":
                                # The edit form for a string item: the text
                                # is the item, never parsed as JSON.
                                parsed_value = item_value
                            else:
                                parsed_value = json.loads(item_value)
                        except json.JSONDecodeError:
                            if item_format == "json":
                                self._list_action_error(
                                    400, "The item is not valid JSON; nothing was saved"
                                )
                                return
                            parsed_value = item_value

                        # Get the list property and update. No separate
                        # length pre-check: under v1, __setitem__ already
                        # raises IndexError on an out-of-range index at no
                        # extra query cost. Under v2 (Phase 11:
                        # thoughts/plans/2026-08-20-v2-positional-access-
                        # cost.md), items_with_handles() below IS that
                        # bounds check -- it's the same one read
                        # __setitem__'s forced reload used to cost, just
                        # surfaced here so this branch can also resolve a
                        # handle to write through instead of an
                        # unconditional overwrite.
                        if myself and hasattr(myself, "property_lists"):
                            list_prop = getattr(myself.property_lists, prop_name)
                            try:
                                if list_prop.storage_format() == 2:
                                    handle, problem = self._list_target(
                                        list_prop, index
                                    )
                                    if problem == "changed":
                                        self._list_action_error(
                                            409,
                                            "The item changed or was removed since "
                                            "the page was loaded; nothing was saved",
                                        )
                                        return
                                    if handle is None:
                                        self._list_action_error(
                                            400, f"Index {index} out of range"
                                        )
                                        return
                                    if not list_prop.update_by_handle(
                                        handle, parsed_value
                                    ):
                                        self._list_action_error(
                                            503, "List item concurrently modified"
                                        )
                                        self.response.headers["Retry-After"] = "1"
                                        return
                                elif index is None:
                                    self._list_action_error(
                                        400, "Missing item_index parameter"
                                    )
                                    return
                                else:
                                    if self._v1_item_changed(list_prop, index):
                                        self._list_action_error(
                                            409,
                                            "The item changed or was removed since "
                                            "the page was loaded; nothing was saved",
                                        )
                                        return
                                    list_prop[index] = parsed_value
                            except ListItemSpanError:
                                raise
                            except IndexError:
                                self._list_action_error(
                                    400, f"Index {index} out of range"
                                )
                                return
                        else:
                            self._list_action_error(
                                500, "List properties not supported"
                            )
                            return

                    elif action == "delete":
                        # Delete item
                        item_index = self.request.get("item_index") or None

                        if item_index is None and not self.request.get("item_rank"):
                            self._list_action_error(400, "Missing item_index parameter")
                            return

                        try:
                            index = int(item_index) if item_index is not None else None
                        except ValueError:
                            self._list_action_error(400, "Invalid item_index")
                            return

                        # Get the list property and delete -- see the
                        # "update" branch above for the v1/v2 split
                        # rationale.
                        if myself and hasattr(myself, "property_lists"):
                            list_prop = getattr(myself.property_lists, prop_name)
                            try:
                                if list_prop.storage_format() == 2:
                                    handle, problem = self._list_target(
                                        list_prop, index
                                    )
                                    if problem == "changed":
                                        self._list_action_error(
                                            409,
                                            "The item changed or was removed since "
                                            "the page was loaded; nothing was deleted",
                                        )
                                        return
                                    if handle is None:
                                        self._list_action_error(
                                            400, f"Index {index} out of range"
                                        )
                                        return
                                    if not list_prop.delete_by_handle(handle):
                                        self._list_action_error(
                                            503, "List item concurrently modified"
                                        )
                                        self.response.headers["Retry-After"] = "1"
                                        return
                                elif index is None:
                                    self._list_action_error(
                                        400, "Missing item_index parameter"
                                    )
                                    return
                                else:
                                    if self._v1_item_changed(list_prop, index):
                                        self._list_action_error(
                                            409,
                                            "The item changed or was removed since "
                                            "the page was loaded; nothing was deleted",
                                        )
                                        return
                                    del list_prop[index]
                            except ListItemSpanError:
                                raise
                            except IndexError:
                                self._list_action_error(
                                    400, f"Index {index} out of range"
                                )
                                return
                        else:
                            self._list_action_error(
                                500, "List properties not supported"
                            )
                            return

                    else:
                        self._list_action_error(400, f"Unknown action: {action}")
                        return

                    # Redirect back to the property page
                    self.response.set_status(302, "Found")
                    self.response.set_redirect(self._list_back)
                    return

                except ListItemTooLargeError as e:
                    logger.warning(f"List item refused for '{prop_name}': {e}")
                    self._list_action_error(413, str(e))
                    return
                except ListItemSpanError as e:
                    logger.error(f"List '{prop_name}' has a broken span: {e}")
                    self._list_action_error(409, str(e))
                    return
                except ListMetadataContentionError as e:
                    logger.warning(f"List metadata contended for '{prop_name}': {e}")
                    self._list_action_error(503, "List metadata contended -- retry")
                    self.response.headers["Retry-After"] = "1"
                    return
                except DbError:
                    raise
                except Exception as e:
                    logger.error(f"Error in list item management: {e}")
                    self._list_action_error(500, "Error processing list item")
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

                        # Initialize the list by ensuring metadata exists (this creates the list in the database).
                        # Load-bearing, and deliberately left as a real len() call: this list is empty by
                        # construction (just created above), so the range query it issues reads zero items --
                        # there is no N+1 here to fix. See Phase 3 of
                        # thoughts/plans/2026-08-20-v2-positional-access-cost.md.
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
                # redirect_to may only name a page of this actor's own web
                # UI: anything else (another site, another actor) would make
                # the form an open redirect.
                www_root = self._www_path(actor_id)
                redirect_path = self.request.get("redirect_to") or ""
                if (
                    not (
                        redirect_path == www_root
                        or redirect_path.startswith(www_root + "/")
                    )
                    or "//" in redirect_path
                    or "\\" in redirect_path
                    # No dot segment, raw or encoded: the browser resolves
                    # "/<id>/www/../../<other>" out of this actor's UI.
                    or "%" in redirect_path
                    # Browsers strip tab and newline from a URL: "\t.." is "..".
                    or any(c.isspace() or ord(c) < 32 for c in redirect_path)
                    or any(seg in (".", "..") for seg in redirect_path.split("/"))
                ):
                    redirect_path = self._www_path(actor_id, "/properties")
                self.response.set_redirect(redirect_path)
                return

            except DbError:
                raise
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
