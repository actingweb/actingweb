import copy
import json
import logging
from typing import Any

from actingweb.db import get_property_list
from actingweb.handlers import base_handler
from actingweb.property_list import ListCorruptionError, ListMetadataContentionError

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
        return False
    if len(path) > 1 and path[1] and len(path[1]) > 0:
        return delete_dict(d1.get(path[0]), path[1:])
    if len(path) == 1 and path[0] and path[0] in d1:
        try:
            del d1[path[0]]
            return True
        except KeyError:
            return False
    return False


logger = logging.getLogger(__name__)


def _write_list_corrupted_response(response: Any, name: str, error: Exception) -> None:
    """Write the structured 409 response for a ListCorruptionError.

    Shared by every handler class in this module that serves list content
    (PropertiesHandler, PropertyListItemsHandler). The exception's own
    message (list name + index only, never item values) is safe to put in
    the body.
    """
    logger.error(f"List '{name}' is corrupted: {error}")
    if response:
        response.set_status(409, "List corrupted")
        response.headers["Content-Type"] = "application/json"
        response.write(
            json.dumps(
                {
                    "error": "list_corrupted",
                    "list": name,
                    "detail": str(error),
                    "remedy": "compact",
                }
            )
        )


_LIST_METADATA_CONTENTION_RETRY_AFTER_SECONDS = "1"


def _write_list_metadata_contention_response(response: Any, error: Exception) -> None:
    """Write the structured 503 response for a ListMetadataContentionError.

    A contended metadata row is a retryable condition, not a server fault
    -- a bare 500 behind an API gateway sends consumers hunting a bug that
    is not there. ``Retry-After`` names the same bound the CAS retry loop
    itself already applied, so a well-behaved client's next attempt lands
    after the contention this response is reporting has had a chance to
    clear.
    """
    logger.warning(f"List metadata contention: {error}")
    if response:
        response.set_status(503, "List metadata contended")
        response.headers["Content-Type"] = "application/json"
        response.headers["Retry-After"] = _LIST_METADATA_CONTENTION_RETRY_AFTER_SECONDS
        response.write(
            json.dumps(
                {
                    "error": "list_metadata_contended",
                    "detail": str(error),
                }
            )
        )


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
                logger.info(
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
            logger.error(
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

    def _respond_list_corrupted(self, name: str, error: Exception) -> None:
        """Write the structured 409 response for a ListCorruptionError."""
        _write_list_corrupted_response(self.response, name, error)

    def _respond_list_metadata_contended(self, error: Exception) -> None:
        """Write the structured 503 response for a ListMetadataContentionError."""
        _write_list_metadata_contention_response(self.response, error)

    def _finish_bulk_list_update(
        self,
        myself,
        key: str,
        list_prop,
        check,
        pair: dict[str, Any],
        items_updated: int,
        items_deleted: int,
    ) -> bool:
        """Shared tail of the bulk list-item update path (POST with an
        ``items`` array): runs the property post hook, if any, against the
        full post-batch list, then sets the per-key response summary.

        Shared by both the v1 (positional) and v2 (handle-based) branches
        of the bulk update -- identical hook/response logic either way,
        only how the batch itself was applied differs between them.

        Returns ``False`` (having already set a 403 response) if a hook
        rejected the update -- the caller must ``return`` immediately
        without setting ``pair[key]``, matching the pre-Phase-11 behaviour
        where a hook rejection short-circuited before the summary was
        recorded.
        """
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                # Pass the entire list for hook validation
                current_items = list_prop.to_list()
                auth_context = self._create_auth_context(check, "write")
                transformed = self.hooks.execute_property_hooks(
                    key, "post", actor_interface, current_items, [key], auth_context
                )
                if transformed is None:
                    # Hook rejected the update - need to revert changes
                    if self.response:
                        self.response.set_status(403, "Bulk update rejected by hooks")
                    return False

        pair[key] = (
            f"[Bulk update: {items_updated} items updated, {items_deleted} items deleted]"
        )
        return True

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

        # Block direct access to list: prefixed properties
        # The "list:" prefix is an internal implementation detail
        if name.startswith("list:"):
            if self.response:
                self.response.set_status(404, "Not found")
            return

        # Try the simple property first (one read). Only on a miss consult
        # the list metadata — the collision checks guarantee a name cannot be
        # both a simple property and a list, so a simple-property hit never
        # needs the extra list-existence read.
        lookup = myself.property[name] if myself and myself.property else None

        # Check if this is a list property
        if (
            lookup is None
            and myself
            and hasattr(myself, "property_lists")
            and myself.property_lists is not None
            and myself.property_lists.exists(name)
        ):
            # This is a list property - handle format and index parameters
            logger.info(f"Processing list property '{name}'")
            index_param = (
                self.request.get("index") or None
            )  # Convert empty string to None
            format_param = (
                self.request.get("format") or None
            )  # Convert empty string to None

            try:
                logger.info(f"Getting list property object for '{name}'")
                list_prop = getattr(myself.property_lists, name)
                logger.info(f"Got list_prop: {type(list_prop).__name__}")
                logger.info(f"index_param={index_param}, format_param={format_param}")

                if index_param is not None:
                    logger.info(f"Handling index access for index={index_param}")
                    # Get specific item by index
                    try:
                        index = int(index_param)
                        item = list_prop[index]

                        # Execute property hook if available
                        if self.hooks:
                            actor_interface = self._get_actor_interface(myself)
                            if actor_interface:
                                hook_path = [str(index)]
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
                    except ListCorruptionError:
                        raise  # let the outer handler write the structured 409
                    except (IndexError, ValueError):
                        if self.response:
                            self.response.set_status(404, "List item not found")
                        return
                else:
                    logger.info(
                        f"Handling list access (not index), format_param={format_param}"
                    )
                    # Determine response format
                    if format_param == "short":
                        logger.info("Using short format")
                        # Short format: return metadata only
                        # This matches the format used in GET /properties?metadata=true
                        metadata = {
                            "_list": True,
                            # Advisory under v2 (count_hint) -- avoids a
                            # whole-list range query for a count-only
                            # request. See ListProperty's class docstring
                            # for the drift bound.
                            "count": list_prop.get_metadata()["length"],
                            "description": list_prop.get_description(),
                            "explanation": list_prop.get_explanation(),
                        }
                        out = json.dumps(metadata)
                    else:
                        # Default (no format or format=full): return all items
                        # This is the expected behavior for subscriptions
                        all_items = list_prop.to_list()

                        # Execute property hook if available
                        logger.info(
                            f"Checking hooks: has_hooks={self.hooks is not None}"
                        )
                        if self.hooks:
                            actor_interface = self._get_actor_interface(myself)
                            logger.info(
                                f"Got actor_interface: {actor_interface is not None}"
                            )
                            if actor_interface:
                                hook_path = []
                                auth_context = self._create_auth_context(check, "read")
                                logger.info(
                                    f"Executing property hooks for '{name}', items count={len(all_items)}"
                                )
                                transformed = self.hooks.execute_property_hooks(
                                    name,
                                    "get",
                                    actor_interface,
                                    all_items,
                                    hook_path,
                                    auth_context,
                                )
                                logger.info(
                                    f"Hook result: transformed is None? {transformed is None}"
                                )
                                if transformed is not None:
                                    all_items = transformed
                                else:
                                    logger.warning(
                                        f"Property hook returned None for '{name}', returning 404"
                                    )
                                    if self.response:
                                        self.response.set_status(404)
                                    return

                        out = json.dumps(all_items)

                if self.response:
                    self.response.set_status(200, "Ok")
                    self.response.headers["Content-Type"] = "application/json"
                    self.response.write(out)
                return

            except ListCorruptionError as e:
                self._respond_list_corrupted(name, e)
                return
            except Exception as e:
                logger.error(f"Error accessing list property '{name}': {e}")
                if self.response:
                    self.response.set_status(500, "Error accessing list property")
                return

        # Regular property handling (lookup was fetched above)
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
                        hook_path = path[1:] if len(path) > 1 else []
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

        # One partition read serves the whole response: simple properties,
        # list discovery, list metadata and (for format=full/metadata) list
        # items all come from this mapping instead of separate re-reads.
        all_rows: dict[str, Any] = {}
        if myself and myself.id and self.config:
            try:
                db_list = get_property_list(self.config)
                all_rows = db_list.fetch_all_including_lists(actor_id=myself.id) or {}
            except Exception as e:
                logger.error(f"Error bulk-reading properties: {e}")
                all_rows = {}
        properties = {
            name: value
            for name, value in all_rows.items()
            if not name.startswith("list:")
        }
        # Check query parameters
        include_metadata = self.request.get("metadata") == "true"
        format_param = self.request.get("format") or None

        # Mutual exclusion: format and metadata cannot be used together
        if include_metadata and format_param:
            if self.response:
                self.response.set_status(
                    400, "Cannot use format and metadata parameters together"
                )
            return

        pair = {}
        if properties and len(properties) > 0:
            for name, value in list(properties.items()):
                try:
                    js = json.loads(value)
                    pair[name] = js
                except ValueError:
                    pair[name] = value

        # Filter properties based on peer permissions (bulk evaluation)
        peer_id = check.acl.get("peerid", "") if hasattr(check, "acl") else ""
        if peer_id and actor_interface and actor_interface.id and pair:
            try:
                evaluator = get_permission_evaluator(self.config)
                # Use bulk evaluation to reduce logging verbosity
                property_names = list(pair.keys())
                results = evaluator.evaluate_bulk_property_access(
                    actor_interface.id, peer_id, property_names, "read"
                )
                # Filter based on results
                filtered_pair = {}
                for prop_name, prop_value in pair.items():
                    result = results.get(prop_name, PermissionResult.DENIED)
                    if result == PermissionResult.ALLOWED:
                        filtered_pair[prop_name] = prop_value
                    elif result == PermissionResult.NOT_FOUND:
                        # No specific rule - include for backward compatibility
                        filtered_pair[prop_name] = prop_value
                    # DENIED properties are excluded
                pair = filtered_pair
            except Exception as e:
                logger.error(f"Error filtering properties by permission: {e}")
                # On error, return empty for security (fail closed)
                pair = {}

        # Execute property hooks for all properties if available
        if self.hooks and pair:
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

        # Always discover list properties (needed for both metadata and non-metadata responses)
        list_names: set[str] = set()
        if (
            actor_interface
            and hasattr(actor_interface, "property_lists")
            and actor_interface.property_lists is not None
        ):
            # Derived from the bulk read above (same parse as list_all())
            all_list_names = {
                name[5:-5]
                for name in all_rows
                if name.startswith("list:") and name.endswith("-meta")
            }

            # Filter list properties based on peer permissions (bulk evaluation)
            if peer_id and actor_interface and actor_interface.id:
                try:
                    evaluator = get_permission_evaluator(self.config)
                    # Use bulk evaluation to reduce logging verbosity
                    results = evaluator.evaluate_bulk_property_access(
                        actor_interface.id, peer_id, list(all_list_names), "read"
                    )
                    for list_name, result in results.items():
                        if (
                            result == PermissionResult.ALLOWED
                            or result == PermissionResult.NOT_FOUND
                        ):
                            list_names.add(list_name)
                        # DENIED list properties are excluded
                except Exception as e:
                    logger.error(f"Error filtering list properties by permission: {e}")
                    # On error, exclude all list properties for security
                    list_names = set()
            else:
                # No peer - include all (owner access)
                list_names = all_list_names

        # Build response based on query parameters
        try:
            if include_metadata:
                # Metadata-only response: no property values, just structure info
                simple_names = list(pair.keys())
                simple_total_bytes = sum(len(json.dumps(v)) for v in pair.values())
                lists_info: dict[str, Any] = {}
                for list_name in list_names:
                    list_prop = getattr(actor_interface.property_lists, list_name)
                    list_prop.prime_from_rows(all_rows)
                    items = list_prop.to_list_from_rows(all_rows)
                    total_bytes = sum(len(json.dumps(item)) for item in items)
                    lists_info[list_name] = {
                        "count": len(items),
                        "total_bytes": total_bytes,
                        "description": list_prop.get_description(),
                        "explanation": list_prop.get_explanation(),
                    }
                pair = {
                    "simple": {
                        "properties": simple_names,
                        "total_bytes": simple_total_bytes,
                    },
                    "lists": lists_info,
                }
            elif format_param == "full":
                # Full format: simple props as-is + list props with items, description, explanation
                for list_name in list_names:
                    list_prop = getattr(actor_interface.property_lists, list_name)
                    list_prop.prime_from_rows(all_rows)
                    items = list_prop.to_list_from_rows(all_rows)
                    # Execute property hooks on list items if available
                    if self.hooks and actor_interface:
                        auth_context = self._create_auth_context(check, "read")
                        transformed_items = []
                        for item in items:
                            transformed = self.hooks.execute_property_hooks(
                                list_name,
                                "get",
                                actor_interface,
                                item,
                                [],
                                auth_context,
                            )
                            if transformed is not None:
                                transformed_items.append(transformed)
                            else:
                                transformed_items.append(item)
                        items = transformed_items
                    pair[list_name] = {
                        "_list": True,
                        "count": len(items),
                        "description": list_prop.get_description(),
                        "explanation": list_prop.get_explanation(),
                        "items": items,
                    }
            else:
                # Default / format=short: simple props as-is + minimal list markers
                for list_name in list_names:
                    list_prop = getattr(actor_interface.property_lists, list_name)
                    list_prop.prime_from_rows(all_rows)
                    pair[list_name] = {
                        "_list": True,
                        "count": len(list_prop),
                    }
        except ListCorruptionError as e:
            self._respond_list_corrupted(e.list_name, e)
            return

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

        # Check if this is a list operation (indicated by index parameter)
        # Note: request.get() may return None or "" when parameter is not present
        index_param = self.request.get("index")
        if index_param:
            # This is a list item operation - handle it appropriately
            if not (
                myself
                and hasattr(myself, "property_lists")
                and myself.property_lists is not None
                and myself.property_lists.exists(name)
            ):
                if self.response:
                    self.response.set_status(404, f"List property '{name}' not found")
                return

            # Check write permission
            property_path = "/".join(path) if path else ""
            if not check or not self._check_property_permission(
                actor_id, check, property_path, "write"
            ):
                if self.response:
                    self.response.set_status(403)
                return

            # Parse the body
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")
            elif body is None:
                body = ""

            try:
                item_value = json.loads(body)
            except (TypeError, ValueError, KeyError):
                item_value = body

            # Get the list property and set the item at the specified index
            try:
                index = int(index_param)
                if index < 0:
                    if self.response:
                        self.response.set_status(
                            400, f"Invalid index: {index} (must be >= 0)"
                        )
                    return

                list_prop = getattr(myself.property_lists, name)
                # Phase 11 (thoughts/plans/2026-08-20-v2-positional-access-
                # cost.md): under v2, one items_with_handles() read serves
                # BOTH the length this branch needs (spec: index == length
                # MAY create, index > length MUST 404 -- unbounded
                # append(None) padding was both a DoS vector and a spec
                # violation) AND the handle the replace case below writes
                # through, instead of a length-only read here followed by
                # __setitem__'s own forced reload. Under v1 there is no
                # handle to resolve, so this stays the length-only read it
                # always was.
                v2_pairs = None
                if list_prop.storage_format() == 2:
                    v2_pairs = list_prop.items_with_handles()
                    length = len(v2_pairs)
                else:
                    length = len(list_prop)

                if index > length:
                    if self.response:
                        self.response.set_status(
                            404, f"Index {index} beyond list length {length}"
                        )
                    return

                # Execute property put hook if available
                if self.hooks:
                    actor_interface = self._get_actor_interface(myself)
                    if actor_interface:
                        auth_context = self._create_auth_context(check, "write")
                        transformed = self.hooks.execute_property_hooks(
                            name,
                            "put",
                            actor_interface,
                            item_value,
                            [name, str(index)],
                            auth_context,
                        )
                        if transformed is not None:
                            item_value = transformed
                        else:
                            if self.response:
                                self.response.set_status(400, "Item rejected by hooks")
                            return

                # Set the item at the index (append if it equals the
                # current length; otherwise it's a bounds-checked replace)
                if index == length:
                    list_prop.append(item_value)
                elif v2_pairs is not None:
                    # v2 replace: a conditional write against the handle
                    # resolved above, not the old unconditional
                    # list_prop[index] = ... (which forced its own fresh
                    # reload and always overwrote whatever it found,
                    # silently clobbering a concurrent writer). A failed
                    # condition now surfaces as the SAME retryable 503 a
                    # metadata CAS exhaustion does -- the client's correct
                    # response is the same either way: re-read and retry.
                    handle = v2_pairs[index][0]
                    if not list_prop.update_by_handle(handle, item_value):
                        self._respond_list_metadata_contended(
                            RuntimeError(
                                f"list '{name}' item at index {index} was "
                                f"concurrently modified"
                            )
                        )
                        return
                else:
                    list_prop[index] = item_value

                # Register diff
                myself.register_diffs(
                    target="properties",
                    subtarget=name,
                    blob=json.dumps({"index": index, "value": item_value}),
                )

                if self.response:
                    self.response.set_status(204)
                return

            except ListMetadataContentionError as e:
                # append()/__setitem__ can raise this on a v1 list -- v1's
                # length write is semantic (advisory=False), so an
                # exhausted CAS retry surfaces here rather than being
                # swallowed. A v2 list's metadata touch is advisory and
                # never raises this. Map to 503 rather than letting it
                # fall through as an unhandled 500.
                self._respond_list_metadata_contended(e)
                return
            except (ValueError, IndexError) as e:
                logger.error(f"Error setting list item at index {index_param}: {e}")
                if self.response:
                    self.response.set_status(400, "Error setting list item")
                return

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
                        path[
                            1:
                        ],  # Exclude property name from path (already in property_name)
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
        # Make store to be at same level as orig value
        i = len(path) - 2
        while i > 0:
            c = copy.copy(store)
            store = {path[i]: c}
            i -= 1
        orig = myself.property[name] if myself and myself.property else None
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
        if myself and myself.property:
            myself.property[name] = res
        myself.register_diffs(
            target="properties", subtarget=name, resource=resource, blob=blob
        )
        self.response.set_status(204)

    def post(self, actor_id, name):
        """POST /properties -- includes the bulk list-item update path.

        Bulk update semantics (a property value shaped as
        ``{"items": [{"index": N, ...fields}, ...]}`` against a list
        property): every ``index`` in the batch is interpreted against the
        list as it stood BEFORE the batch, regardless of the order items
        appear in the request. Updates (an item_spec with fields beyond
        ``index``) are applied first, in the given order -- they never
        shift positions. Deletes (an item_spec with ONLY ``index``) are
        applied last, in descending index order, so each delete's target
        index is still valid: a delete only shifts indices ABOVE it, and
        descending order guarantees every not-yet-processed delete is at or
        below the one just applied.
        """
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
                        logger.error(
                            f"Invalid 'items' field for property '{key}': expected list, got {type(val['items']).__name__}"
                        )
                        if self.response:
                            self.response.set_status(
                                400,
                                f"Invalid 'items' field for property '{key}': expected list, got {type(val['items']).__name__}",
                            )
                        return

                    if len(val["items"]) == 0:
                        logger.warning(
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

                            if list_prop.storage_format() == 2:
                                # v2: resolve the whole batch against ONE
                                # strongly-consistent snapshot (one range
                                # read via items_with_handles()) instead of
                                # positional access -- each positional read/
                                # write below cost its own whole-list query
                                # under v2 before Phases 7-10. Ordering
                                # semantics (updates first in given order,
                                # deletes last in descending index order)
                                # are unchanged from the v1 branch below and
                                # are preserved here even though a v2
                                # handle's validity doesn't depend on other
                                # handles -- so the two branches produce
                                # identical output for identical input, and
                                # a same-index update+delete now applies the
                                # update and reports the delete as
                                # concurrently modified (its handle's raw
                                # bytes were pinned before the update
                                # changed them) -- see CHANGELOG/migration
                                # notes for 3.14: 3.13.0 deleted the updated
                                # row instead.
                                pairs = list_prop.items_with_handles()
                                snapshot_length = len(pairs)
                                pending_updates_v2: list[
                                    tuple[int, dict[str, Any]]
                                ] = []
                                pending_deletes_v2: list[int] = []
                                projected_length = snapshot_length

                                for i, item_spec in enumerate(val["items"]):
                                    if not isinstance(item_spec, dict):
                                        logger.error(
                                            f"Invalid item at position {i}: must be a dictionary, got {type(item_spec).__name__}"
                                        )
                                        if self.response:
                                            self.response.set_status(
                                                400,
                                                f"Invalid item at position {i}: must be a dictionary, got {type(item_spec).__name__}",
                                            )
                                        return

                                    if "index" not in item_spec:
                                        logger.error(
                                            f"Missing 'index' field in item at position {i}: {item_spec}"
                                        )
                                        if self.response:
                                            self.response.set_status(
                                                400,
                                                f"Missing 'index' field in item at position {i}",
                                            )
                                        return

                                    index = item_spec["index"]

                                    if not isinstance(index, int):
                                        logger.error(
                                            f"Invalid index type in item at position {i}: expected integer, got {type(index).__name__}"
                                        )
                                        if self.response:
                                            self.response.set_status(
                                                400,
                                                f"Invalid index type in item at position {i}: expected integer, got {type(index).__name__}",
                                            )
                                        return

                                    if index < 0:
                                        logger.error(
                                            f"Invalid index value in item at position {i}: {index} (must be >= 0)"
                                        )
                                        if self.response:
                                            self.response.set_status(
                                                400,
                                                f"Invalid index value in item at position {i}: {index} (must be >= 0)",
                                            )
                                        return

                                    if len(item_spec) == 1:  # Only "index" -- delete
                                        pending_deletes_v2.append(index)
                                    else:
                                        # Same bound as the v1 branch, and
                                        # the same DoS rationale: reject an
                                        # out-of-bounds index during
                                        # validation, before anything is
                                        # written.
                                        if index > projected_length:
                                            logger.error(
                                                f"Index {index} in item at position {i} is beyond list length {projected_length}"
                                            )
                                            if self.response:
                                                self.response.set_status(
                                                    400,
                                                    f"Index {index} in item at position {i} is beyond list length {projected_length}",
                                                )
                                            return
                                        if index == projected_length:
                                            projected_length += 1

                                        item_data = {
                                            k: v
                                            for k, v in item_spec.items()
                                            if k != "index"
                                        }
                                        pending_updates_v2.append((index, item_data))

                                # Resolve the final value for each targeted
                                # index before writing anything, and write
                                # each distinct index at most once. This
                                # mirrors what the v1 branch achieves for
                                # free via successive __setitem__ calls
                                # against a live, growing length: a later
                                # update in this batch always supersedes an
                                # earlier one at the same index. Without
                                # this, two updates at the same
                                # newly-created index would append two rows
                                # instead of one overwriting the other, and
                                # two updates at the same pre-existing
                                # index would have the second fail as
                                # "concurrently modified" against a handle
                                # the first one's own write had just
                                # invalidated -- not a real concurrent
                                # writer, just this batch's own earlier
                                # entry. See CHANGELOG/migration notes for
                                # 3.14.
                                final_value_by_index: dict[int, dict[str, Any]] = {}
                                for index, item_data in pending_updates_v2:
                                    final_value_by_index[index] = item_data

                                # An index this batch both creates (>=
                                # snapshot_length, via an update above) and
                                # deletes nets to "never existed" -- the
                                # same final state a create-then-delete
                                # produces in the v1 branch. Skip writing
                                # it at all rather than appending it just
                                # to immediately delete it again.
                                skip_new_indices = {
                                    index
                                    for index in pending_deletes_v2
                                    if index >= snapshot_length
                                    and index in final_value_by_index
                                }

                                # Pass 1: updates, ascending index order --
                                # required for the append case, where each
                                # new index must land in the same order it
                                # was assigned in validation above. An
                                # index within the pre-batch snapshot
                                # resolves to that row's handle; an index
                                # at or beyond the snapshot length is the
                                # append-at-length case and still goes
                                # through append() (Phase 9B: one
                                # get_last_in_range read, not a second
                                # whole-list query) rather than a handle,
                                # since there is no pre-existing row to
                                # address.
                                index_succeeded: dict[int, bool] = {}
                                for index in sorted(final_value_by_index):
                                    if index in skip_new_indices:
                                        index_succeeded[index] = True
                                        continue
                                    if index < snapshot_length:
                                        handle = pairs[index][0]
                                        if list_prop.update_by_handle(
                                            handle, final_value_by_index[index]
                                        ):
                                            index_succeeded[index] = True
                                        else:
                                            logger.warning(
                                                f"Cannot update item at index {index}: concurrently modified since the batch snapshot was read"
                                            )
                                            index_succeeded[index] = False
                                            # Don't fail the entire operation -- report per item, matching Pass 2's existing style below.
                                    else:
                                        list_prop.append(final_value_by_index[index])
                                        index_succeeded[index] = True

                                # Reported per request entry, matching the
                                # v1 branch's accounting, even though a
                                # duplicate index only ever produces one
                                # actual write -- see final_value_by_index
                                # above.
                                items_updated = sum(
                                    1
                                    for index, _ in pending_updates_v2
                                    if index_succeeded.get(index)
                                )

                                # Pass 2: deletes, highest index first --
                                # kept even though a v2 handle's validity
                                # doesn't depend on other handles, so the
                                # two branches produce identical output for
                                # identical input.
                                for index in sorted(pending_deletes_v2, reverse=True):
                                    if index in skip_new_indices:
                                        items_deleted += 1
                                    elif index < snapshot_length:
                                        handle = pairs[index][0]
                                        if list_prop.delete_by_handle(handle):
                                            items_deleted += 1
                                        else:
                                            logger.warning(
                                                f"Cannot delete item at index {index}: concurrently modified since the batch snapshot was read"
                                            )
                                            # Don't fail the entire operation, just log warning
                                    else:
                                        logger.warning(
                                            f"Cannot delete item at index {index}: index out of range (list length: {snapshot_length})"
                                        )
                                        # Don't fail the entire operation, just log warning

                                if not self._finish_bulk_list_update(
                                    myself,
                                    key,
                                    list_prop,
                                    check,
                                    pair,
                                    items_updated,
                                    items_deleted,
                                ):
                                    return
                                continue

                            # v1: unchanged from before Phase 11 -- dense
                            # integer indices don't have the whole-list-read
                            # cost this phase exists to remove, and this
                            # release scopes every cost fix to v2.
                            #
                            # Batch semantics: every "index" in this batch is
                            # interpreted against the list as it stood BEFORE
                            # the batch. Updates (__setitem__) don't shift
                            # positions, so they're applied first, in the
                            # given order; deletes DO shift later indices
                            # down by one, so they run last, in descending
                            # index order -- each delete's target is still
                            # valid because only lower, not-yet-processed
                            # indices are ever affected by a higher delete.
                            pending_updates: list[tuple[int, dict[str, Any]]] = []
                            pending_deletes: list[int] = []
                            # Read once. Update indices are bounds-checked
                            # against this, advanced by each append the batch
                            # performs (see the check below); delete indices
                            # keep their pre-batch meaning per the ordering
                            # semantics documented above.
                            projected_length = len(list_prop)

                            for i, item_spec in enumerate(val["items"]):
                                # Validate item structure
                                if not isinstance(item_spec, dict):
                                    logger.error(
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
                                    logger.error(
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
                                    logger.error(
                                        f"Invalid index type in item at position {i}: expected integer, got {type(index).__name__}"
                                    )
                                    if self.response:
                                        self.response.set_status(
                                            400,
                                            f"Invalid index type in item at position {i}: expected integer, got {type(index).__name__}",
                                        )
                                    return

                                if index < 0:
                                    logger.error(
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
                                    pending_deletes.append(index)
                                else:
                                    # Same bound as the PUT ?index=N path,
                                    # projected across the batch: an update
                                    # may address an existing item or append
                                    # at exactly the current length, never
                                    # beyond it. `projected_length` tracks
                                    # what the list will be when this update
                                    # runs, so a batch may still populate an
                                    # empty list with indices 0,1,2,...
                                    # Without this bound the update pass
                                    # padded the gap with append(None) one
                                    # row at a time, so a single request
                                    # naming index 10**8 became 10**8
                                    # database writes. Validating here (not
                                    # in the update pass) means an
                                    # out-of-bounds index rejects the batch
                                    # before anything is written.
                                    if index > projected_length:
                                        logger.error(
                                            f"Index {index} in item at position {i} is beyond list length {projected_length}"
                                        )
                                        if self.response:
                                            self.response.set_status(
                                                400,
                                                f"Index {index} in item at position {i} is beyond list length {projected_length}",
                                            )
                                        return
                                    if index == projected_length:
                                        projected_length += 1

                                    # Update/set item - the entire item_spec except "index" is the item data
                                    item_data = {
                                        k: v
                                        for k, v in item_spec.items()
                                        if k != "index"
                                    }
                                    pending_updates.append((index, item_data))

                            # Pass 1: updates, in the given order.
                            for index, item_data in pending_updates:
                                try:
                                    # Append-at-length case. Bounded to a
                                    # single append by the index <=
                                    # pre_batch_length check above: updates
                                    # never shrink the list, so len() here
                                    # is always >= pre_batch_length.
                                    while len(list_prop) <= index:
                                        list_prop.append(None)
                                    # Store the complete object
                                    list_prop[index] = item_data
                                    items_updated += 1
                                except (IndexError, ValueError) as e:
                                    logger.error(
                                        f"Error updating item at index {index}: {e}"
                                    )
                                    if self.response:
                                        self.response.set_status(
                                            500,
                                            f"Error updating item at index {index}",
                                        )
                                    return

                            # Pass 2: deletes, highest index first, so each
                            # target is still the position it was specified
                            # against (a delete only shifts LOWER,
                            # not-yet-processed indices).
                            for index in sorted(pending_deletes, reverse=True):
                                try:
                                    if index < len(list_prop):
                                        del list_prop[index]
                                        items_deleted += 1
                                    else:
                                        logger.warning(
                                            f"Cannot delete item at index {index}: index out of range (list length: {len(list_prop)})"
                                        )
                                        # Don't fail the entire operation, just log warning
                                except IndexError as e:
                                    logger.error(
                                        f"Error deleting item at index {index}: {e}"
                                    )
                                    # Don't fail the entire operation for delete errors

                            if not self._finish_bulk_list_update(
                                myself,
                                key,
                                list_prop,
                                check,
                                pair,
                                items_updated,
                                items_deleted,
                            ):
                                return

                        except ListCorruptionError as e:
                            self._respond_list_corrupted(key, e)
                            return
                        except ListMetadataContentionError as e:
                            self._respond_list_metadata_contended(e)
                            return
                        except Exception as e:
                            logger.error(
                                f"Error in bulk update for list property '{key}': {e}"
                            )
                            if self.response:
                                self.response.set_status(500, "Error in bulk update")
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
                    "*",
                    "delete",
                    actor_interface,
                    actor_interface.properties.to_dict(),
                    path,
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

                except ListCorruptionError as e:
                    self._respond_list_corrupted(name, e)
                    return
                except Exception as e:
                    logger.error(f"Error deleting list property '{name}': {e}")
                    self.response.set_status(500, "Error deleting list property")
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
                logger.info(
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
            logger.error(
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
            "_list": True,
            # Advisory under v2 (count_hint) -- see ListProperty's class
            # docstring for the drift bound.
            "count": list_prop.get_metadata()["length"],
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

        try:
            if "description" in params:
                list_prop.set_description(str(params["description"]))
            if "explanation" in params:
                list_prop.set_explanation(str(params["explanation"]))
        except ListMetadataContentionError as e:
            self._respond_list_metadata_contended(e)
            return

        # Register diff for metadata changes
        myself.register_diffs(
            target="properties",
            subtarget=name,
            blob=json.dumps({"action": "metadata_update", **params}),
        )

        if self.response:
            self.response.set_status(204)

    def _respond_list_metadata_contended(self, error: Exception) -> None:
        """Write the structured 503 response for a ListMetadataContentionError."""
        _write_list_metadata_contention_response(self.response, error)


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
                logger.info(
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
            logger.error(
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

    def _respond_list_corrupted(self, name: str, error: Exception) -> None:
        """Write the structured 409 response for a ListCorruptionError."""
        _write_list_corrupted_response(self.response, name, error)

    def _respond_list_metadata_contended(self, error: Exception) -> None:
        """Write the structured 503 response for a ListMetadataContentionError."""
        _write_list_metadata_contention_response(self.response, error)

    def get(self, actor_id: str, name: str):
        """Get all items from a list property.

        Response shape: ``{"items": [{"index": i, "item": ...}], "count": n}``
        -- storage indices on both this response and the ``item_index``
        accepted by ``update``/``delete`` below, so the two are always
        consistent with each other. This is an implementation extension,
        not part of the ActingWeb spec (which addresses items by path
        index, e.g. ``/properties/{name}/{index}``).
        """
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
        try:
            indexed = list_prop.to_indexed_list()
        except ListCorruptionError as e:
            self._respond_list_corrupted(name, e)
            return

        if self.response:
            self.response.write(
                json.dumps(
                    {
                        "items": [{"index": i, "item": item} for i, item in indexed],
                        "count": len(indexed),
                    }
                )
            )
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
                # Computed once and reused below, rather than two separate
                # len(list_prop) - 1 calls for the diff and the response.
                new_index = len(list_prop) - 1

                # Register diff for subscription notifications
                myself.register_diffs(
                    target="properties",
                    subtarget=name,
                    blob=json.dumps(
                        {
                            "action": "add",
                            "index": new_index,
                            "value": item_value,
                        }
                    ),
                )

                if self.response:
                    self.response.write(
                        json.dumps({"success": True, "index": new_index})
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

                # Phase 11 (thoughts/plans/2026-08-20-v2-positional-access-
                # cost.md): under v2, items_with_handles() below IS the
                # bounds check -- the same one read __setitem__'s forced
                # reload used to cost, just surfaced here so this branch
                # can also resolve a handle to write through instead of an
                # unconditional overwrite that silently clobbered a
                # concurrent writer. Under v1, __setitem__ still raises
                # IndexError on an out-of-range index at no extra query
                # cost, so that branch is unchanged.
                try:
                    if list_prop.storage_format() == 2:
                        pairs = list_prop.items_with_handles()
                        if index < 0 or index >= len(pairs):
                            if self.response:
                                self.response.set_status(
                                    400, f"Index {index} out of range"
                                )
                            return
                        if not list_prop.update_by_handle(pairs[index][0], item_value):
                            self._respond_list_metadata_contended(
                                RuntimeError(
                                    f"list '{name}' item at index {index} was "
                                    f"concurrently modified"
                                )
                            )
                            return
                    else:
                        list_prop[index] = item_value
                except IndexError:
                    if self.response:
                        self.response.set_status(400, f"Index {index} out of range")
                    return

                # Register diff for subscription notifications
                myself.register_diffs(
                    target="properties",
                    subtarget=name,
                    blob=json.dumps(
                        {"action": "update", "index": index, "value": item_value}
                    ),
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

                # v1/v2 split -- see the "update" branch above for the
                # rationale.
                try:
                    if list_prop.storage_format() == 2:
                        pairs = list_prop.items_with_handles()
                        if index < 0 or index >= len(pairs):
                            if self.response:
                                self.response.set_status(
                                    400, f"Index {index} out of range"
                                )
                            return
                        if not list_prop.delete_by_handle(pairs[index][0]):
                            self._respond_list_metadata_contended(
                                RuntimeError(
                                    f"list '{name}' item at index {index} was "
                                    f"concurrently modified"
                                )
                            )
                            return
                    else:
                        del list_prop[index]
                except IndexError:
                    if self.response:
                        self.response.set_status(400, f"Index {index} out of range")
                    return

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

        except ListCorruptionError as e:
            # Parity with /items GET and every other list-serving path: a
            # corrupted list is a structured 409 with a repair hint, never a
            # bare 500. No action above currently reads item rows, so this
            # is a contract guarantee rather than a reachable branch today.
            self._respond_list_corrupted(name, e)
            return
        except ListMetadataContentionError as e:
            self._respond_list_metadata_contended(e)
            return
        except Exception as e:
            logger.error(f"Error in list item operation '{action}' for '{name}': {e}")
            if self.response:
                self.response.set_status(500, "Error processing list item")
