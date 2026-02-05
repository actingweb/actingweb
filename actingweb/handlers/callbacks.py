import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from actingweb import auth
from actingweb.handlers import base_handler

if TYPE_CHECKING:
    from actingweb.aw_proxy import AwProxy
    from actingweb.interface.actor_interface import ActorInterface
    from actingweb.remote_storage import RemotePeerStore
    from actingweb.subscription_config import SubscriptionProcessingConfig

logger = logging.getLogger(__name__)


def _has_wildcard(pattern: str) -> bool:
    """Check if a pattern contains wildcard characters."""
    return "*" in pattern or "?" in pattern or "[" in pattern


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

            # Get subscription data before deletion for lifecycle hook
            sub_data = {}
            if self.hooks:
                from ..subscription import Subscription

                sub_obj = Subscription(
                    actor_id=actor_id,
                    peerid=peerid,
                    subid=subid,
                    callback=False,  # Callback subscription is inbound (callback=False)
                    config=myself.config,
                )
                sub_data = sub_obj.subscription if sub_obj.subscription else {}

            if actor_interface.subscriptions.delete_callback_subscription(
                peer_id=peerid, subscription_id=subid
            ):
                # Execute lifecycle hook after successful deletion
                # This is a peer-initiated deletion (they're deleting their subscription to us)
                if self.hooks and peerid:
                    try:
                        logger.info(
                            f"Executing subscription_deleted hook for peer {peerid}, initiated_by_peer=True"
                        )
                        self.hooks.execute_lifecycle_hooks(
                            "subscription_deleted",
                            actor=actor_interface,
                            peer_id=peerid,
                            subscription_id=subid,
                            subscription_data=sub_data,
                            initiated_by_peer=True,
                        )
                        logger.info(
                            f"Successfully executed subscription_deleted hook for {peerid}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Error executing subscription_deleted hook: {e}",
                            exc_info=True,
                        )

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
                    normalize_property_permission,
                )

                perm_data = params.get("data", {})
                timestamp = params.get("timestamp", datetime.now(UTC).isoformat())

                peer_perms = PeerPermissions(
                    actor_id=actor_id,
                    peer_id=granting_actor_id,
                    properties=normalize_property_permission(
                        perm_data.get("properties")
                    ),
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
                # This fetches the newly accessible data immediately using
                # incremental sync (only the newly granted properties, not full baseline)
                subscription_config = getattr(
                    myself.config, "_subscription_config", None
                )
                if (
                    permission_changes.get("granted_patterns")
                    and subscription_config
                    and subscription_config.enabled
                    and subscription_config.auto_storage
                ):
                    granted_patterns = permission_changes["granted_patterns"]
                    logger.info(
                        f"Incremental sync for peer {granting_actor_id} after permissions granted: "
                        f"{granted_patterns}"
                    )
                    try:
                        self._incremental_sync_granted_properties(
                            actor_interface=actor_interface,
                            peer_id=granting_actor_id,
                            granted_patterns=granted_patterns,
                        )
                        logger.info(
                            f"Incremental sync completed for {granting_actor_id}: "
                            f"{len(granted_patterns)} pattern(s) synced"
                        )
                    except Exception as sync_error:
                        logger.error(
                            f"Error during incremental sync for {granting_actor_id}: {sync_error}",
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
                logger.debug(f"Found subscription {subid} for peer {peerid}")
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

            if callback_type == "resync":
                # Resync callback - use shared baseline fetch method for consistency
                # This ensures proper handling of ?metadata=true and property list transformations
                target = params.get("target", "properties")
                subtarget = params.get("subtarget")
                resource = params.get("resource")

                try:
                    # Use SubscriptionManager's baseline fetch helper
                    # This handles metadata expansion, property list transformations, etc.
                    callback_data = (
                        actor_interface.subscriptions._fetch_and_transform_baseline(
                            peer_id=peer_id,
                            target=target,
                            subtarget=subtarget,
                            resource=resource,
                        )
                    )
                    if callback_data:
                        # Handle list responses when fetching a subtarget (e.g., properties/list_name)
                        # _fetch_and_transform_baseline returns a raw list for list properties,
                        # but apply_resync_data expects a dict. Wrap the list in the expected format.
                        if isinstance(callback_data, list) and subtarget:
                            callback_data = {
                                subtarget: {"_list": True, "items": callback_data}
                            }
                        logger.debug(
                            f"Fetched resync baseline for {target}"
                            f"{f'/{subtarget}' if subtarget else ''}: "
                            f"{len(callback_data)} {'keys' if isinstance(callback_data, dict) else 'items'}"
                        )
                    else:
                        logger.warning(f"Failed to fetch resync baseline for {target}")
                        callback_data = {}
                except Exception as e:
                    logger.error(f"Error fetching resync baseline: {e}")
                    callback_data = {}
            else:
                # Low-granularity diff callback - fetch from subscription diff endpoint
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
                        # Low-granularity: URL points to subscription diff endpoint
                        # Response is a single diff object: {"data": {...}, "sequence": N, ...}
                        callback_data = url_data.get("data", {})
                        logger.debug(
                            f"Fetched low-granularity data: {len(callback_data)} keys"
                        )
                    else:
                        logger.warning(
                            f"Failed to fetch low-granularity data: {response.status_code}"
                        )
                        callback_data = {}
                except Exception as e:
                    logger.error(f"Error fetching low-granularity callback data: {e}")
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

    def _incremental_sync_granted_properties(
        self,
        actor_interface: "ActorInterface",
        peer_id: str,
        granted_patterns: list[str],
    ) -> None:
        """Fetch and store only the newly granted properties from a peer.

        Instead of doing a full sync_peer() (which refetches baseline, capabilities,
        and permissions), this method only fetches the specific properties that were
        just granted access to.

        Args:
            actor_interface: The actor interface for storage access
            peer_id: The peer who granted access
            granted_patterns: List of property patterns that were newly granted
        """
        import fnmatch

        from actingweb.aw_proxy import AwProxy
        from actingweb.remote_storage import RemotePeerStore

        if not granted_patterns:
            return

        # Get proxy to peer
        proxy = AwProxy(
            peer_target={
                "id": actor_interface._core_actor.id,
                "peerid": peer_id,
                "passphrase": None,
            },
            config=actor_interface._core_actor.config,
        )

        if not proxy.trust:
            logger.warning(f"Cannot fetch granted properties: no trust with {peer_id}")
            return

        remote_store = RemotePeerStore(actor_interface, peer_id, validate_peer_id=False)

        for pattern in granted_patterns:
            if _has_wildcard(pattern):
                # Wildcard pattern: fetch property list and filter
                self._fetch_wildcard_properties(
                    proxy, remote_store, peer_id, pattern, fnmatch.fnmatch
                )
            else:
                # Exact property name: fetch directly
                self._fetch_single_property(proxy, remote_store, peer_id, pattern)

    def _fetch_single_property(
        self,
        proxy: "AwProxy",
        remote_store: "RemotePeerStore",
        peer_id: str,
        property_name: str,
    ) -> None:
        """Fetch a single property from a peer and store it.

        Handles both simple properties (stored as key-value) and list properties
        (stored via set_list with items array).
        """
        from datetime import UTC, datetime

        try:
            response = proxy.get_resource(path=f"properties/{property_name}")

            if response is None or (isinstance(response, dict) and "error" in response):
                error_msg = (
                    response.get("error")
                    if isinstance(response, dict)
                    else "no response"
                )
                logger.warning(
                    f"Failed to fetch property {property_name} from {peer_id}: {error_msg}"
                )
                return

            # Response could be:
            # 1. A list of items (for list properties): [{"data": ...}, ...]
            # 2. A dict with list markers: {"_list": True, "items": [...]}
            # 3. A simple dict value: {"value": "..."}
            if isinstance(response, list):
                # List property returned as array of items
                metadata = {
                    "source_actor": peer_id,
                    "source_property": property_name,
                    "synced_at": datetime.now(UTC).isoformat(),
                    "item_count": len(response),
                }
                remote_store.set_list(property_name, response, metadata=metadata)
                logger.debug(
                    f"Stored list property '{property_name}' from {peer_id}: "
                    f"{len(response)} items"
                )
            elif isinstance(response, dict) and response.get("_list") is True:
                # List property with flag-based format
                raw_items = response.get("items", [])
                items: list[dict[str, Any]] = (
                    raw_items if isinstance(raw_items, list) else []
                )
                metadata = {
                    "source_actor": peer_id,
                    "source_property": property_name,
                    "synced_at": datetime.now(UTC).isoformat(),
                    "item_count": len(items),
                }
                remote_store.set_list(property_name, items, metadata=metadata)
                logger.debug(
                    f"Stored list property '{property_name}' from {peer_id}: "
                    f"{len(items)} items"
                )
            elif isinstance(response, dict):
                # Simple property - store value
                remote_store.set_value(property_name, response)
                logger.debug(f"Stored property '{property_name}' from {peer_id}")
            else:
                logger.warning(
                    f"Unexpected response type for property {property_name} "
                    f"from {peer_id}: {type(response).__name__}"
                )
        except Exception as e:
            logger.error(
                f"Error fetching property {property_name} from {peer_id}: {e}",
                exc_info=True,
            )

    def _fetch_wildcard_properties(
        self,
        proxy: "AwProxy",
        remote_store: "RemotePeerStore",
        peer_id: str,
        pattern: str,
        fnmatch_func: Callable[[str, str], bool],
    ) -> None:
        """Fetch properties matching a wildcard pattern from a peer."""
        try:
            # Fetch property list from peer
            response = proxy.get_resource(path="properties")

            if response is None or "error" in (response or {}):
                error_msg = (
                    response.get("error")
                    if isinstance(response, dict)
                    else "no response"
                )
                logger.warning(
                    f"Failed to fetch property list from {peer_id}: {error_msg}"
                )
                return

            if not isinstance(response, dict):
                return

            # Filter properties matching the pattern
            matching_props = [
                prop_name
                for prop_name in response.keys()
                if fnmatch_func(prop_name, pattern)
            ]

            logger.debug(
                f"Found {len(matching_props)} properties matching pattern '{pattern}' "
                f"on peer {peer_id}"
            )

            # Fetch each matching property
            for prop_name in matching_props:
                self._fetch_single_property(proxy, remote_store, peer_id, prop_name)

        except Exception as e:
            logger.error(
                f"Error fetching wildcard properties '{pattern}' from {peer_id}: {e}",
                exc_info=True,
            )

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
