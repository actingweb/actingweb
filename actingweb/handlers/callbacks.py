import json
import logging
from typing import TYPE_CHECKING

from actingweb import auth
from actingweb.handlers import base_handler

if TYPE_CHECKING:
    from actingweb.interface.actor_interface import ActorInterface
    from actingweb.subscription_config import SubscriptionProcessingConfig

logger = logging.getLogger(__name__)


class CallbacksHandler(base_handler.BaseHandler):
    def get(self, actor_id, name):
        """Handles GETs to callbacks"""
        if self.request.get("_method") == "PUT":
            self.put(actor_id, name)
        if self.request.get("_method") == "POST":
            self.post(actor_id, name)
        auth_result = self._authenticate_dual_context(
            actor_id, "callbacks", "callbacks", name, add_response=False
        )
        if (
            not auth_result.actor
            or not auth_result.auth_obj
            or (
                auth_result.auth_obj.response["code"] != 200
                and auth_result.auth_obj.response["code"] != 401
            )
        ):
            auth.add_auth_response(appreq=self, auth_obj=auth_result.auth_obj)
            return
        myself = auth_result.actor
        if not auth_result.authorize("GET", "callbacks", name):
            return
        # Execute callback hook for GET
        hook_result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_callback_hooks(
                    name, actor_interface, {"method": "GET"}
                )

        if hook_result is not None:
            if self.response:
                self.response.set_status(200, "OK")
                self.response.headers["Content-Type"] = "application/json"
                self.response.write(json.dumps(hook_result))
        else:
            self.response.set_status(403, "Forbidden")

    def put(self, actor_id, name):
        """PUT requests are handled as POST for callbacks"""
        self.post(actor_id, name)

    def delete(self, actor_id, name):
        """Handles deletion of callbacks, like subscriptions"""
        auth_result = self._authenticate_dual_context(
            actor_id, "callbacks", "callbacks", name
        )
        if not auth_result.success:
            return
        myself = auth_result.actor
        check = auth_result.auth_obj
        path = name.split("/")
        if path[0] == "subscriptions":
            peerid = path[1]
            subid = path[2]
            if not check.check_authorisation(
                path="callbacks",
                subpath="subscriptions",
                method="DELETE",
                peerid=peerid,
            ):
                if self.response:
                    self.response.set_status(403, "Forbidden")
                return

            # Use developer API to delete callback subscription
            actor_interface = self._get_actor_interface(myself)
            if not actor_interface:
                if self.response:
                    self.response.set_status(500, "Internal error")
                return

            if actor_interface.subscriptions.delete_callback_subscription(
                peer_id=peerid, subscription_id=subid
            ):
                self.response.set_status(204, "Deleted")
                return
            self.response.set_status(404, "Not found")
            return
        if not check.check_authorisation(
            path="callbacks", subpath=name, method="DELETE"
        ):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return
        # Execute callback hook for DELETE
        hook_result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                hook_result = self.hooks.execute_callback_hooks(
                    name, actor_interface, {"method": "DELETE"}
                )

        if hook_result is not None:
            if self.response:
                self.response.set_status(200, "OK")
                self.response.headers["Content-Type"] = "application/json"
                self.response.write(json.dumps(hook_result))
        else:
            self.response.set_status(403, "Forbidden")

    def post(self, actor_id, name):
        """Handles POST callbacks"""
        auth_result = self._authenticate_dual_context(
            actor_id, "callbacks", "callbacks", name, add_response=False
        )
        myself = auth_result.actor
        check = auth_result.auth_obj
        # Allow unauthenticated requests to /callbacks/subscriptions and
        # /callbacks/permissions, so do the auth check further below
        path = name.split("/")

        # Handle permission callbacks: /callbacks/permissions/{granting_actor_id}
        if path[0] == "permissions" and len(path) >= 2:
            granting_actor_id = path[1]

            actor_interface = self._get_actor_interface(myself) if myself else None
            if not actor_interface:
                self.response.set_status(404, "Not found")
                return

            # Verify trust relationship exists with granting actor
            if not check or not check.check_authorisation(
                path="callbacks",
                subpath="permissions",
                method="POST",
                peerid=granting_actor_id,
            ):
                if self.response:
                    self.response.set_status(403, "Forbidden")
                return

            # Parse request body
            try:
                body: str | bytes | None = self.request.body
                if body is None:
                    body_str = "{}"
                elif isinstance(body, bytes):
                    body_str = body.decode("utf-8", "ignore")
                else:
                    body_str = body
                params = json.loads(body_str)
            except (TypeError, ValueError, KeyError):
                self.response.set_status(400, "Error in json body")
                return

            # Store permissions in PeerPermissionStore
            permission_changes: dict = {}
            try:
                from datetime import UTC, datetime

                from actingweb.peer_permissions import (
                    PeerPermissions,
                    detect_permission_changes,
                    get_peer_permission_store,
                )

                perm_data = params.get("data", {})
                timestamp = params.get("timestamp", datetime.now(UTC).isoformat())

                peer_perms = PeerPermissions(
                    actor_id=actor_id,
                    peer_id=granting_actor_id,
                    properties=perm_data.get("properties"),
                    methods=perm_data.get("methods"),
                    actions=perm_data.get("actions"),
                    tools=perm_data.get("tools"),
                    resources=perm_data.get("resources"),
                    prompts=perm_data.get("prompts"),
                    fetched_at=timestamp,
                )

                store = get_peer_permission_store(myself.config)

                # Get old permissions before storing new ones (for comparison)
                old_permissions = store.get_permissions(actor_id, granting_actor_id)

                # Detect what changed
                permission_changes = detect_permission_changes(
                    old_permissions, peer_perms
                )

                # Store new permissions
                success = store.store_permissions(peer_perms)

                logger.debug(
                    f"Stored permission callback from {granting_actor_id} "
                    f"for actor {actor_id}: success={success}, "
                    f"has_properties={peer_perms.properties is not None}"
                )

                # Auto-delete cached peer data if configured and access was revoked
                if permission_changes.get("has_revocations") and getattr(
                    myself.config, "auto_delete_on_revocation", False
                ):
                    self._delete_revoked_peer_data(
                        actor_interface,
                        granting_actor_id,
                        permission_changes.get("revoked_patterns", []),
                    )

                # Auto-sync when new permissions are granted
                # This fetches the newly accessible data immediately
                # Only perform auto-sync if subscription processing is enabled and auto_storage is on
                subscription_config = getattr(
                    myself.config, "_subscription_config", None
                )
                if (
                    permission_changes.get("granted_patterns")
                    and subscription_config
                    and subscription_config.enabled
                    and subscription_config.auto_storage
                ):
                    logger.info(
                        f"Auto-syncing peer {granting_actor_id} after permissions granted: "
                        f"{permission_changes['granted_patterns']}"
                    )
                    try:
                        sync_result = actor_interface.subscriptions.sync_peer(
                            granting_actor_id, config=subscription_config
                        )
                        if sync_result.success:
                            logger.info(
                                f"Auto-sync completed for {granting_actor_id}: "
                                f"{sync_result.subscriptions_synced} subscription(s), "
                                f"{sync_result.total_diffs_processed} diffs processed"
                            )
                        else:
                            logger.warning(
                                f"Auto-sync failed for {granting_actor_id}: {sync_result.error}"
                            )
                    except Exception as sync_error:
                        logger.error(
                            f"Error during auto-sync for {granting_actor_id}: {sync_error}",
                            exc_info=True,
                        )
                        # Don't fail the callback - sync is not critical
                elif permission_changes.get("granted_patterns"):
                    logger.debug(
                        f"Skipping auto-sync for {granting_actor_id} "
                        f"(subscription processing not enabled or auto_storage disabled)"
                    )

            except Exception as e:
                logger.error(f"Error storing permission callback: {e}")
                self.response.set_status(500, "Internal error")
                return

            # Execute permission callback hook for app-specific handling
            if self.hooks:
                hook_data = params.copy()
                hook_data["granting_actor_id"] = granting_actor_id
                hook_data["method"] = "POST"
                hook_data["permission_changes"] = permission_changes
                self.hooks.execute_callback_hooks(
                    "permissions", actor_interface, hook_data
                )

            self.response.set_status(204, "No Content")
            return

        if path[0] == "subscriptions":
            peerid = path[1]
            subid = path[2]

            # Use developer API to get callback subscription
            actor_interface = self._get_actor_interface(myself) if myself else None
            if not actor_interface:
                self.response.set_status(404, "Not found")
                return

            sub_info = actor_interface.subscriptions.get_callback_subscription(
                peer_id=peerid, subscription_id=subid
            )
            if sub_info:
                # Convert to dict for hook compatibility
                sub = sub_info.to_dict()
                logger.debug("Found subscription (" + str(sub) + ")")
                if not check or not check.check_authorisation(
                    path="callbacks",
                    subpath="subscriptions",
                    method="POST",
                    peerid=peerid,
                ):
                    if self.response:
                        self.response.set_status(403, "Forbidden")
                    return
                try:
                    body: str | bytes | None = self.request.body
                    if body is None:
                        body_str = "{}"
                    elif isinstance(body, bytes):
                        body_str = body.decode("utf-8", "ignore")
                    else:
                        body_str = body
                    params = json.loads(body_str)
                except (TypeError, ValueError, KeyError):
                    self.response.set_status(400, "Error in json body")
                    return

                # Process subscription callback internally FIRST (if configured)
                # Check if subscription processing is enabled
                subscription_config = getattr(
                    myself.config, "_subscription_config", None
                )

                result = False
                if (
                    subscription_config
                    and subscription_config.enabled
                    and subscription_config.auto_sequence
                ):
                    # Internal library processing: CallbackProcessor + RemotePeerStore
                    # Hooks are invoked inside the internal handler after validation
                    result = self._process_subscription_callback_internal(
                        actor_interface=actor_interface,
                        peer_id=peerid,
                        subscription_id=subid,
                        subscription=sub,
                        params=params,
                        config=subscription_config,
                    )
                elif self.hooks:
                    # Legacy fallback: just invoke user hooks directly (no internal processing)
                    hook_data = params.copy()
                    hook_data.update({"subscription": sub, "peerid": peerid})
                    hook_result = self.hooks.execute_callback_hooks(
                        "subscription", actor_interface, hook_data
                    )
                    result = bool(hook_result) if hook_result is not None else False

                if result:
                    self.response.set_status(204, "Found")
                else:
                    self.response.set_status(400, "Processing error")
                return
            self.response.set_status(404, "Not found")
            return
        if (
            not myself
            or not check
            or (check.response["code"] != 200 and check.response["code"] != 401)
        ):
            auth.add_auth_response(appreq=self, auth_obj=check)
            return
        if not auth_result.authorize("POST", "callbacks", name):
            return
        # Execute callback hook for POST
        hook_result = None
        if self.hooks:
            actor_interface = self._get_actor_interface(myself)
            if actor_interface:
                # Parse request body for hook data
                try:
                    body: str | bytes | None = self.request.body
                    if body is None:
                        body_str = "{}"
                    elif isinstance(body, bytes):
                        body_str = body.decode("utf-8", "ignore")
                    else:
                        body_str = body
                    hook_data = json.loads(body_str)
                except (TypeError, ValueError, KeyError):
                    hook_data = {}

                hook_data["method"] = "POST"
                hook_result = self.hooks.execute_callback_hooks(
                    name, actor_interface, hook_data
                )

        if hook_result is not None:
            if self.response:
                self.response.set_status(200, "OK")
                self.response.headers["Content-Type"] = "application/json"
                self.response.write(json.dumps(hook_result))
        else:
            self.response.set_status(403, "Forbidden")

    def _process_subscription_callback_internal(
        self,
        actor_interface: "ActorInterface",
        peer_id: str,
        subscription_id: str,
        subscription: dict,
        params: dict,
        config: "SubscriptionProcessingConfig",
    ) -> bool:
        """
        Process subscription callback through CallbackProcessor (internal library logic).

        This is the internal processing that happens BEFORE user hooks are invoked.
        It handles sequence validation, gap detection, deduplication, storage, and
        sequence number updates.

        Args:
            actor_interface: ActorInterface for the receiving actor
            peer_id: ID of the peer sending the callback
            subscription_id: ID of the subscription
            subscription: Subscription info dict
            params: Parsed callback request body
            config: Subscription processing configuration

        Returns:
            True if processed successfully, False otherwise
        """
        from actingweb.callback_processor import (
            CallbackProcessor,
            CallbackType,
            ProcessResult,
        )
        from actingweb.remote_storage import RemotePeerStore

        if not config.enabled:
            return False

        # Extract callback data
        # Check for callbacks with URL but no data (per ActingWeb spec v1.4)
        # This handles both:
        # 1. Low-granularity callbacks (granularity="low", url, no type)
        # 2. Resync callbacks (type="resync", url, no data)
        callback_url = params.get("url")
        callback_data = params.get("data")
        callback_type = params.get("type", "diff")
        granularity = params.get("granularity", "high")  # Extracted for debugging/logging

        # Track if we need to send PUT acknowledgment after processing
        # Per ActingWeb spec: high-granularity with data in body → 204 clears diff
        # But low-granularity/resync with URL only → must send PUT to acknowledge
        fetched_from_url = bool(callback_url and not callback_data)

        if callback_url and not callback_data:
            # Need to fetch data from URL
            fetch_type = (
                callback_type if callback_type == "resync" else "low-granularity"
            )
            logger.debug(
                f"{fetch_type.capitalize()} callback, fetching data from {callback_url}"
            )
            try:
                import httpx

                from actingweb.trust import Trust

                # Get trust relationship for authentication
                trust = Trust(
                    actor_id=actor_interface._core_actor.id,
                    peerid=peer_id,
                    config=actor_interface._core_actor.config,
                )
                trust_data = trust.get()
                secret = trust_data.get("secret", "") if trust_data else ""

                with httpx.Client(timeout=10.0) as client:
                    response = client.get(
                        callback_url,
                        headers={
                            "Authorization": f"Bearer {secret}",
                        },
                    )
                if response.status_code == 200:
                    url_data = response.json()

                    # Parse response based on callback type
                    if callback_type == "resync":
                        # Resync callback - URL points to resource
                        # Response can be:
                        # 1. Specific list: /properties/list_name -> returns array
                        # 2. All properties: /properties -> returns dict with metadata
                        # 3. Single scalar: /properties/name -> returns dict

                        if isinstance(url_data, list):
                            # Array response - this is a specific property list
                            # Extract list name from subtarget parameter (preferred)
                            subtarget = params.get("subtarget")

                            if subtarget:
                                # Use subtarget as list name
                                list_name = subtarget
                            else:
                                # Fall back to extracting from URL path
                                # URL format: /{actor_id}/properties/{list_name}
                                import re

                                match = re.search(
                                    r"/properties/([^/]+)/?$", callback_url
                                )
                                list_name = match.group(1) if match else "unknown"

                            # Wrap array in expected format for apply_resync_data()
                            # Use flag-based format (preferred)
                            callback_data = {
                                list_name: {"_list": True, "items": url_data}
                            }
                            logger.debug(
                                f"Fetched resync list '{list_name}': {len(url_data)} items"
                            )
                        else:
                            # Dict response - could be:
                            # - All properties (e.g., {"memory_travel": {"_list": true, "count": 3}})
                            # - Single scalar property (e.g., {"value": "...", "_list": false})
                            # Pass through as-is for apply_resync_data()
                            callback_data = url_data
                            logger.debug(
                                f"Fetched resync data: {len(callback_data)} keys"
                            )
                    else:
                        # Low-granularity diff callback
                        # URL points to subscription diff endpoint
                        # Response is a single diff object: {"data": {...}, "sequence": N, ...}
                        callback_data = url_data.get("data", {})
                        logger.debug(
                            f"Fetched low-granularity data: {len(callback_data)} keys"
                        )
                else:
                    logger.warning(
                        f"Failed to fetch {fetch_type} data: {response.status_code}"
                    )
                    callback_data = {}
            except Exception as e:
                logger.error(f"Error fetching {fetch_type} callback data: {e}")
                callback_data = {}
        else:
            callback_data = callback_data or {}

        sequence = params.get("sequence", 0)

        logger.debug(
            f"Processing subscription callback: peer={peer_id}, "
            f"sub={subscription_id}, seq={sequence}, type={callback_type}"
        )

        try:
            # Create processor
            processor = CallbackProcessor(
                actor_interface,
                gap_timeout_seconds=config.gap_timeout_seconds,
                max_pending=config.max_pending,
            )

            # Define handler for processed callbacks
            def handler(cb):
                """Handler invoked by CallbackProcessor after validation."""
                # Auto-storage: store data in RemotePeerStore
                if config.auto_storage:
                    store = RemotePeerStore(
                        actor_interface, peer_id, validate_peer_id=False
                    )
                    if cb.callback_type == CallbackType.RESYNC:
                        store.apply_resync_data(cb.data)
                    else:
                        store.apply_callback_data(cb.data)

                # Invoke subscription_data_hooks (from app.subscription_data_hook decorator)
                target = subscription.get("target", "properties")
                if config.subscription_data_hooks:
                    import inspect

                    # Invoke target-specific hooks
                    if target in config.subscription_data_hooks:
                        for hook in config.subscription_data_hooks[target]:
                            try:
                                if inspect.iscoroutinefunction(hook):
                                    # Can't await in sync context, run via asyncio.run
                                    import asyncio

                                    asyncio.run(
                                        hook(
                                            actor_interface,
                                            peer_id,
                                            target,
                                            cb.data,
                                            cb.sequence,
                                            cb.callback_type.value,
                                        )
                                    )
                                else:
                                    hook(
                                        actor_interface,
                                        peer_id,
                                        target,
                                        cb.data,
                                        cb.sequence,
                                        cb.callback_type.value,
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error in subscription_data_hook for {target}: {e}"
                                )

                    # Invoke wildcard hooks
                    if "*" in config.subscription_data_hooks:
                        for hook in config.subscription_data_hooks["*"]:
                            try:
                                if inspect.iscoroutinefunction(hook):
                                    import asyncio

                                    asyncio.run(
                                        hook(
                                            actor_interface,
                                            peer_id,
                                            target,
                                            cb.data,
                                            cb.sequence,
                                            cb.callback_type.value,
                                        )
                                    )
                                else:
                                    hook(
                                        actor_interface,
                                        peer_id,
                                        target,
                                        cb.data,
                                        cb.sequence,
                                        cb.callback_type.value,
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error in subscription_data_hook wildcard: {e}"
                                )

                # Invoke legacy callback hooks (for backward compatibility)
                if self.hooks:
                    hook_data = {
                        "peerid": peer_id,
                        "subscription": subscription,
                        "data": cb.data,
                        "sequence": cb.sequence,
                        "type": cb.callback_type.value,
                    }
                    self.hooks.execute_callback_hooks(
                        "subscription", actor_interface, hook_data
                    )

            # Process through CallbackProcessor
            result = processor.process_callback_sync(
                peer_id=peer_id,
                subscription_id=subscription_id,
                sequence=sequence,
                data=callback_data,
                callback_type=callback_type,
                handler=handler,
            )

            # Accept PENDING and RESYNC_TRIGGERED as success
            # PENDING: callback queued due to sequence gap (waiting for missing callbacks)
            # RESYNC_TRIGGERED: gap timeout exceeded, subscriber needs to sync from publisher
            # Per ActingWeb protocol, receiver handles gaps via polling, sender should not retry
            success = result in (
                ProcessResult.PROCESSED,
                ProcessResult.DUPLICATE,
                ProcessResult.PENDING,
                ProcessResult.RESYNC_TRIGGERED,
            )

            if success:
                logger.debug(
                    f"Subscription callback processed: peer={peer_id}, "
                    f"sub={subscription_id}, seq={sequence}, result={result.value}"
                )
            else:
                logger.warning(
                    f"Subscription callback rejected: peer={peer_id}, "
                    f"sub={subscription_id}, seq={sequence}, result={result.value}"
                )

            # Send PUT acknowledgment for low-granularity callbacks only
            # Per ActingWeb spec:
            # - High-granularity (data in body) → 204 auto-clears diff
            # - Low-granularity (URL only) → must send PUT to clear diff
            # - Resync (type="resync") → 204 means accepted baseline resync, NO diff to clear
            if (
                result == ProcessResult.PROCESSED
                and fetched_from_url
                and callback_type != "resync"
            ):
                logger.debug(
                    f"Sending PUT acknowledgment for low-granularity callback "
                    f"seq={sequence} to {peer_id}"
                )
                try:
                    from ..aw_proxy import AwProxy

                    # Create proxy to send PUT acknowledgment to peer
                    peer_target = {
                        "id": actor_interface._core_actor.id,
                        "peerid": peer_id,
                        "passphrase": None,
                    }
                    proxy = AwProxy(
                        peer_target=peer_target,
                        config=actor_interface._core_actor.config,
                    )
                    if proxy.trust:
                        # PUT /subscriptions/{our_actor_id}/{subscription_id} {"sequence": N}
                        path = f"subscriptions/{actor_interface._core_actor.id}/{subscription_id}"
                        ack_response = proxy.change_resource(
                            path=path, params={"sequence": sequence}
                        )
                        if ack_response is None or "error" in (ack_response or {}):
                            logger.warning(
                                f"Failed to send PUT acknowledgment to {peer_id} "
                                f"for subscription {subscription_id} seq={sequence}"
                            )
                        else:
                            logger.debug(
                                f"Successfully acknowledged low-granularity callback "
                                f"seq={sequence} to {peer_id}, diff cleared on publisher"
                            )
                except Exception as e:
                    logger.error(
                        f"Error sending PUT acknowledgment to {peer_id}: {e}",
                        exc_info=True,
                    )

            # If resync was triggered, actively sync from publisher to resolve gap
            if result == ProcessResult.RESYNC_TRIGGERED:
                logger.info(
                    f"Gap timeout triggered resync for {peer_id}:{subscription_id}, "
                    f"initiating sync from publisher"
                )
                try:
                    from ..interface.subscription_manager import SubscriptionManager

                    mgr = SubscriptionManager(actor_interface._core_actor)
                    sync_result = mgr.sync_subscription(peer_id, subscription_id)
                    if sync_result.success:
                        logger.info(
                            f"Resync completed: {sync_result.diffs_processed} diffs, "
                            f"sequence now at {sync_result.final_sequence}"
                        )
                    else:
                        logger.warning(
                            f"Resync failed: {sync_result.error or 'unknown error'}"
                        )
                except Exception as e:
                    logger.error(f"Error during automatic resync: {e}", exc_info=True)

            return success

        except Exception as e:
            logger.error(
                f"Error processing subscription callback: peer={peer_id}, "
                f"sub={subscription_id}, seq={sequence}, error={e}",
                exc_info=True,
            )
            return False

    def _delete_revoked_peer_data(
        self,
        actor_interface: "ActorInterface",
        peer_id: str,
        revoked_patterns: list[str],
    ) -> None:
        """Delete cached peer data for revoked property patterns.

        When a peer revokes access to certain properties (e.g., memory_*),
        this method deletes the locally cached data that was synced via
        subscriptions.

        Args:
            actor_interface: The actor interface for storage access
            peer_id: The peer who revoked access
            revoked_patterns: List of property patterns that were revoked
        """
        import fnmatch

        from actingweb.remote_storage import RemotePeerStore

        if not revoked_patterns:
            return

        try:
            store = RemotePeerStore(actor_interface, peer_id)

            # Get all stored lists for this peer
            all_lists = store.list_all_lists()

            deleted_count = 0
            for list_name in all_lists:
                # Check if this list matches any revoked pattern
                for pattern in revoked_patterns:
                    if fnmatch.fnmatch(list_name, pattern):
                        try:
                            store.delete_list(list_name)
                            deleted_count += 1
                            logger.info(
                                f"Deleted revoked peer data: {list_name} "
                                f"from peer {peer_id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to delete revoked data {list_name} "
                                f"from peer {peer_id}: {e}"
                            )
                        break  # Don't double-delete if multiple patterns match

            if deleted_count > 0:
                logger.info(
                    f"Deleted {deleted_count} cached items from peer {peer_id} "
                    f"due to permission revocation"
                )

        except Exception as e:
            logger.error(f"Error during revoked peer data deletion: {e}")
