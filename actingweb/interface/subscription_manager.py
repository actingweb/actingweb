"""
Simplified subscription management for ActingWeb actors.
"""

import contextvars
import functools
import json
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from ..actor import Actor as CoreActor
from ..actor import TrustReplaced
from ..db.exceptions import DbError
from ..subscription import Subscription as CoreSubscription

if TYPE_CHECKING:
    from ..subscription_config import SubscriptionProcessingConfig

logger = logging.getLogger(__name__)

_revocation_pool: ThreadPoolExecutor | None = None
_revocation_pool_lock = threading.Lock()


def _forget_revocation_pool() -> None:
    """In a forked child the parent's pool threads do not exist: start a
    new pool on first use (3.16)."""
    global _revocation_pool, _revocation_pool_lock
    _revocation_pool = None
    _revocation_pool_lock = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_forget_revocation_pool)


def _revocation_executor() -> ThreadPoolExecutor:
    """The threads ``sync_peer_async`` deletes a revoked trust on (3.16):
    apart from the event loop's default executor, which the ``trust_deleted``
    hooks it waits on may need."""
    global _revocation_pool
    with _revocation_pool_lock:
        if _revocation_pool is None:
            _revocation_pool = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="aw-revocation"
            )
        return _revocation_pool


class SubscriptionInfo:
    """Represents a subscription to or from another actor."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @property
    def subscription_id(self) -> str:
        """Unique subscription ID."""
        return self._data.get("subscriptionid", "")

    @property
    def peer_id(self) -> str:
        """ID of the peer actor."""
        return self._data.get("peerid", "")

    @property
    def target(self) -> str:
        """Target being subscribed to."""
        return self._data.get("target", "")

    @property
    def subtarget(self) -> str | None:
        """Subtarget being subscribed to."""
        return self._data.get("subtarget")

    @property
    def resource(self) -> str | None:
        """Resource being subscribed to."""
        return self._data.get("resource")

    @property
    def granularity(self) -> str:
        """Granularity of notifications (high, low, none)."""
        return self._data.get("granularity", "high")

    @property
    def is_callback(self) -> bool:
        """Whether this subscription receives callbacks (we subscribed to another actor).

        When callback=True, we are the subscriber and will receive callbacks from the peer.
        When callback=False, we are the publisher and will send callbacks to the peer.
        """
        return self._data.get("callback", False)

    @property
    def is_outbound(self) -> bool:
        """Whether this is an outbound subscription (we subscribed to another actor).

        Outbound subscriptions are ones we initiated - we subscribed TO another actor.
        These have callback=True because we receive callbacks from them.
        """
        return self.is_callback

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self._data.copy()


class SubscriptionWithDiffs:
    """
    Wrapper around a core Subscription object that provides access to diff operations.

    This class is returned by get_subscription_with_diffs() and provides methods
    to retrieve and manage subscription diffs (change notifications).
    """

    def __init__(self, core_subscription: CoreSubscription):
        """Initialize with a core Subscription object."""
        self._core_sub = core_subscription

    @property
    def subscription_info(self) -> SubscriptionInfo | None:
        """Get the subscription info as a SubscriptionInfo object."""
        sub_data = self._core_sub.get()
        if sub_data:
            return SubscriptionInfo(sub_data)
        return None

    def get_diffs(self) -> list[dict[str, Any]]:
        """
        Get all pending diffs for this subscription.

        Returns a list of diffs ordered by timestamp (oldest first).
        Each diff contains: sequence, timestamp, and diff data.
        """
        diffs = self._core_sub.get_diffs()
        if diffs is None:
            return []
        return diffs if isinstance(diffs, list) else []

    def get_diff(self, seqnr: int) -> dict[str, Any] | None:
        """
        Get a specific diff by sequence number.

        Args:
            seqnr: The sequence number of the diff to retrieve

        Returns:
            The diff data if found, None otherwise
        """
        return self._core_sub.get_diff(seqnr=seqnr)

    def clear_diffs(self, seqnr: int = 0) -> None:
        """
        Clear all diffs up to and including the specified sequence number.

        Args:
            seqnr: Clear all diffs up to this sequence number.
                   If 0, clears all diffs.
        """
        self._core_sub.clear_diffs(seqnr=seqnr)

    def clear_diff(self, seqnr: int) -> bool:
        """
        Clear a specific diff by sequence number.

        Args:
            seqnr: The sequence number of the diff to clear

        Returns:
            True if the diff was cleared successfully, False otherwise
        """
        return bool(self._core_sub.clear_diff(seqnr=seqnr))


def _subtarget_value(response: Any, proxy: Any, subtarget: str) -> Any:
    """A single property's 2xx baseline as the value it is: an empty body
    or an empty JSON object is empty (``{subtarget: ""}``, which a replica
    stores as nothing); a body that is not JSON is the property's text only
    when the publisher itself answered (no redirect followed) as
    ``text/plain`` (specification 1.5) or ``application/json`` (a publisher
    before 3.16), otherwise it is a failed fetch (None: a login page behind
    a proxy is not the value); anything else as parsed."""
    if response != {}:
        return response
    raw = proxy.last_response_message
    text = (
        raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    ).strip()
    if not text:
        return {subtarget: ""}
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = _NOT_JSON
    if parsed == {}:
        return {subtarget: ""}
    if not _own_value_answer(proxy):
        return None
    return text


def rebuilds_for(config: Any, target: str | None) -> bool:
    """Whether a rebuild of a subscription to ``target`` has anything to
    do: a replica to replace (``auto_storage``), or a data hook that hears
    the baseline (one for the target, or ``"*"``). The behind poll, an owed
    rebuild on a poll and an owed rebuild on a callback all ask this, so a
    rebuild one of them owes is run by one that tells (3.16)."""
    if config.auto_storage:
        return True
    hooks = getattr(config, "subscription_data_hooks", None) or {}
    return bool(hooks.get("*")) or bool(target and hooks.get(target))


def _publisher_sequence(response: dict[str, Any]) -> int:
    """The sequence a publisher's ``/subscriptions`` answer carries, or 0
    when it is not an integer (``null``, text, a boolean, ``NaN``): such an
    answer is neither recorded nor compared (3.16)."""
    sequence = response.get("sequence", 0)
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        return 0
    return sequence


def sweep_after_baseline(
    core_actor: Any,
    store: Any,
    *,
    peer_id: str,
    target: str,
    subtarget: str | None,
    resource: str | None,
    baseline: Any,
    applied: Any,
    owed: list[str],
) -> None:
    """Delete from a replica what a baseline no longer carries, in the
    subscription's scope (3.16): at target level every replica name it lacks
    (properties only, and only when no subscription to another target of the
    peer stores into the same bucket), at subtarget level the subtarget, and
    each list recorded as out of step that it lacks. A skipped apply (a
    whole-target subscription stores these names) sweeps nothing. Called by
    ``rebuild_subscription`` and after a pushed resync's baseline."""
    from ..replica_revocation import stores_another_target

    carried = set(applied)
    stale: set[str] = (
        set() if applied.skipped else {name for name in owed if name not in carried}
    )
    if applied.skipped:
        pass
    elif (
        target == "properties"
        and not subtarget
        and isinstance(baseline, dict)
        and not stores_another_target(core_actor.config, core_actor.id or "", peer_id)
    ):
        # A whole-target baseline carries every name the peer may read: a
        # replica name it lacks was deleted at the publisher.
        stale |= {
            name
            for name in [*store.list_all_lists(), *store.list_scalar_names()]
            if name not in carried
        }
    elif subtarget and not resource and subtarget not in carried:
        stale.add(subtarget)
    for name in sorted(stale):
        if store._list_exists(name):  # noqa: SLF001
            store.delete_list(name)
        else:
            store.delete_value(name)


def _baseline_failed(response: Any, proxy: Any) -> bool:
    """Whether a target-level baseline fetch failed, decided from the wire
    (the status and a redirect), not from the body (3.16: a body with a
    property named ``error`` was read as a failed fetch). A proxy whose
    status is not a number (a test double) is judged by the body as before.
    """
    code = getattr(proxy, "last_response_code", None)
    if isinstance(code, int) and not isinstance(code, bool):
        if getattr(proxy, "last_response_redirected", False) is True:
            return True
        if response is None or not 200 <= code <= 299:
            return True
        if not response:
            # ``{}`` is an empty baseline only when the publisher answered
            # JSON: the proxy reads any other 2xx body (a proxy's page, a
            # 204) as ``{}``, and an empty baseline makes the sweep delete
            # the whole replica.
            content_type = str(getattr(proxy, "last_response_content_type", "") or "")
            return content_type.split(";", 1)[0].strip().lower() != "application/json"
        return False
    return response is None or (isinstance(response, dict) and "error" in response)


def _own_value_answer(proxy: Any) -> bool:
    """The last answer was the publisher's own property value: not
    redirected, and ``text/plain`` or ``application/json`` (any case,
    parameters ignored)."""
    if getattr(proxy, "last_response_redirected", False):
        return False
    content_type = str(getattr(proxy, "last_response_content_type", "") or "")
    media = content_type.split(";", 1)[0].strip().lower()
    return media in ("text/plain", "application/json")


def _confirms_list(meta: Any, proxy: Any) -> bool:
    """The metadata route answered for a list: a non-empty object without
    ``error``, not reached through a redirect (a login page parses as
    ``{}``)."""
    return (
        isinstance(meta, dict)
        and bool(meta)
        and "error" not in meta
        and not getattr(proxy, "last_response_redirected", False)
    )


_NOT_JSON = object()


@dataclass
class SubscriptionSyncResult:
    """Result of syncing a single subscription."""

    subscription_id: str
    success: bool
    diffs_fetched: int
    diffs_processed: int
    final_sequence: int
    error: str | None = None
    error_code: int | None = None
    # True when the poll stopped at a sequence a callback delivery is still
    # handling: it neither cleared nor recorded past it, and a later poll
    # picks the rest up.
    in_flight: bool = False
    # A rebuild that settled: the baseline it applied, for a caller that
    # tells the application's hooks (3.16, verification B1).
    baseline: Any = None
    # The subscription's target and subtarget, set with ``baseline``.
    target: str | None = None
    subtarget: str | None = None
    # True when the rebuild stored nothing because another subscription's
    # replica covers this one: a poll does not tell ``baseline`` (3.16).
    baseline_skipped: bool = False


@dataclass
class PeerSubscriptions:
    """One peer's subscriptions, as :meth:`SubscriptionManager.get_subscriptions_by_peer`
    groups them: ``outbound`` as :attr:`SubscriptionManager.outbound_subscriptions`
    selects (we subscribed to the peer), ``inbound`` as
    :attr:`SubscriptionManager.inbound_subscriptions` does (the peer
    subscribed to us)."""

    peer_id: str
    outbound: list[SubscriptionInfo]
    inbound: list[SubscriptionInfo]


@dataclass
class PeerSyncResult:
    """Result of syncing all subscriptions to a peer."""

    peer_id: str
    success: bool
    subscriptions_synced: int
    total_diffs_processed: int
    subscription_results: list[SubscriptionSyncResult]
    error: str | None = None


def _log_peer_clear_failure(proxy: Any, message: str) -> None:
    """Log a failed clear or acknowledgement at the publisher with its status:
    WARNING, or ERROR for a 403 (the publisher's access rows refuse it, so it
    will keep failing and the publisher's queue keeps growing)."""
    status = getattr(proxy, "last_response_code", None)
    log = logger.error if status == 403 else logger.warning
    hint = (
        " (refused: the publisher's access rows must admit PUT on "
        "subscriptions/<id>/<subid>)"
        if status == 403
        else ""
    )
    log(f"{message}: {status}{hint}")


class SubscriptionManager:
    """
    Simplified interface for managing subscriptions.

    Example usage:
        # Subscribe to another actor's data
        subscription = actor.subscriptions.subscribe_to_peer(
            peer_id="peer123",
            target="properties",
            subtarget="status"
        )

        # List all subscriptions
        for sub in actor.subscriptions.all_subscriptions:
            print(f"Subscription to {sub.peer_id}: {sub.target}")

        # Notify subscribers of changes
        actor.subscriptions.notify_subscribers(
            target="properties",
            data={"status": "active"}
        )

        # Unsubscribe
        actor.subscriptions.unsubscribe(peer_id="peer123", subscription_id="sub123")
    """

    def __init__(self, core_actor: CoreActor, hooks: Any = None):
        self._core_actor = core_actor
        self._hooks = hooks

    @property
    def all_subscriptions(self) -> list[SubscriptionInfo]:
        """Get all subscriptions (both inbound and outbound)."""
        subscriptions = self._core_actor.get_subscriptions()
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]

    @property
    def outbound_subscriptions(self) -> list[SubscriptionInfo]:
        """Get subscriptions to other actors (we subscribed to them).

        These are subscriptions we initiated - callback=True means we receive callbacks.
        """
        return [sub for sub in self.all_subscriptions if sub.is_outbound]

    @property
    def inbound_subscriptions(self) -> list[SubscriptionInfo]:
        """Get subscriptions from other actors (they subscribed to us).

        These are subscriptions others created - callback=False means we send callbacks.
        """
        return [sub for sub in self.all_subscriptions if not sub.is_callback]

    def get_subscriptions_by_peer(self) -> dict[str, PeerSubscriptions]:
        """Every subscription of the actor, grouped by peer id (3.16).

        One subscription read for the whole map. A peer with no subscription
        has no key. A read fault raises ``DbError``, as the other accessors
        do.
        """
        groups: dict[str, PeerSubscriptions] = {}
        for sub in self.all_subscriptions:
            group = groups.get(sub.peer_id)
            if group is None:
                group = groups[sub.peer_id] = PeerSubscriptions(
                    peer_id=sub.peer_id, outbound=[], inbound=[]
                )
            if sub.is_outbound:
                group.outbound.append(sub)
            if not sub.is_callback:
                group.inbound.append(sub)
        return groups

    def get_subscriptions_to_peer(self, peer_id: str) -> list[SubscriptionInfo]:
        """Get all subscriptions to a specific peer (outbound subscriptions).

        These are subscriptions we created to subscribe to their data.
        """
        subscriptions = self._core_actor.get_subscriptions(
            peerid=peer_id, callback=True
        )
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]

    def get_subscriptions_from_peer(self, peer_id: str) -> list[SubscriptionInfo]:
        """Get all subscriptions from a specific peer (inbound subscriptions).

        These are subscriptions they created to subscribe to our data.
        Returns inbound subscriptions where the peer_id matches.
        """
        # Get all inbound subscriptions (callback=False means they subscribed to us)
        all_inbound = self.inbound_subscriptions
        # Filter to only those from the specific peer
        return [sub for sub in all_inbound if sub.peer_id == peer_id]

    def get_subscriptions_for_target(
        self, target: str, subtarget: str = "", resource: str = ""
    ) -> list[SubscriptionInfo]:
        """Get all subscriptions for a specific target."""
        subscriptions = self._core_actor.get_subscriptions(
            target=target, subtarget=subtarget or None, resource=resource or None
        )
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]

    def subscribe_to_peer(
        self,
        peer_id: str,
        target: str,
        subtarget: str = "",
        resource: str = "",
        granularity: str = "high",
    ) -> str | None:
        """
        Subscribe to another actor's data and perform initial baseline sync.

        This method creates the subscription and immediately fetches baseline data,
        ensuring consistency regardless of whether the peer has existing data.

        Note: For async contexts, prefer subscribe_to_peer_async() for better
        performance and non-blocking execution.

        Args:
            peer_id: ID of the peer actor to subscribe to
            target: The target to subscribe to (e.g., "properties")
            subtarget: Optional subtarget within the target
            resource: Optional specific resource within the target
            granularity: Update granularity ("high" for real-time, "low" for batched)

        Returns:
            The subscription URL if successful, None otherwise.
        """
        # Create the remote subscription
        result = self._core_actor.create_remote_subscription(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
        )

        if not result or not isinstance(result, str):
            return None

        # Perform initial baseline fetch directly from the target endpoint
        # This bypasses the subscription diff endpoint and ensures we get the current state

        # Get configured subscription processing settings from the app
        # If not configured, use defaults (auto_storage=True for backward compatibility)
        config = (
            self._core_actor.config._subscription_config
            if self._core_actor.config
            else None
        )
        config = self._processing_config(config)

        transformed_data = self._fetch_and_transform_baseline(
            peer_id=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
        )
        if subtarget and transformed_data == {subtarget: ""}:
            # Not there yet: at a first subscription nothing is stored to
            # delete, so no baseline, as before 3.16.
            transformed_data = None

        if (
            transformed_data is not None if subtarget else transformed_data
        ) and config.auto_storage:
            # Store baseline data if auto_storage is enabled
            from ..remote_storage import RemotePeerStore
            from .actor_interface import ActorInterface

            actor_interface = ActorInterface(self._core_actor)
            store = RemotePeerStore(
                actor=actor_interface,
                peer_id=peer_id,
                validate_peer_id=False,
            )
            store.apply_resync_data(
                transformed_data,
                subtarget=subtarget or None,
                resource=resource or None,
                target=target,
            )
            logger.info(f"Stored initial baseline for {peer_id} from {target}")

        # Fetch peer metadata during initial subscription (independent of storage)
        if transformed_data:
            self._refresh_peer_metadata(peer_id)

        return result

    async def subscribe_to_peer_async(
        self,
        peer_id: str,
        target: str,
        subtarget: str = "",
        resource: str = "",
        granularity: str = "high",
    ) -> str | None:
        """
        Subscribe to another actor's data and perform initial baseline sync.

        This is the preferred method for creating subscriptions as it ensures
        the baseline data is fetched immediately after subscription creation,
        regardless of whether the peer has existing data or not.

        The method respects the sync_subscription_callbacks configuration:
        - In Lambda/serverless (sync mode): Uses blocking operations to prevent
          execution freeze before baseline fetch completes
        - In local/container (async mode): Uses true async operations for
          non-blocking execution

        Args:
            peer_id: ID of the peer actor to subscribe to
            target: The target to subscribe to (e.g., "properties")
            subtarget: Optional subtarget within the target
            resource: Optional specific resource within the target
            granularity: Update granularity ("high" for real-time, "low" for batched)

        Returns:
            The subscription URL if successful, None otherwise.

        Example:
            # Subscribe and get baseline in one call
            url = await actor.subscriptions.subscribe_to_peer_async(
                peer_id="peer123",
                target="properties",
                granularity="high"
            )
            if url:
                print(f"Subscribed and synced: {url}")
        """
        # Create the remote subscription
        # Note: This respects sync_subscription_callbacks config internally
        # for Lambda/serverless compatibility
        result = await self._core_actor.create_remote_subscription_async(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
        )

        if not result or not isinstance(result, str):
            return None

        # Fetch initial baseline directly from the target endpoint
        # We skip the subscription diff endpoint because:
        # 1. We just created the subscription - there are no diffs yet
        # 2. The subscription endpoint might not be ready yet (timing/eventual consistency)
        # 3. Fetching directly from /properties is more efficient for initial baseline

        # Get configured subscription processing settings from the app
        # If not configured, use defaults (auto_storage=True for backward compatibility)
        config = (
            self._core_actor.config._subscription_config
            if self._core_actor.config
            else None
        )
        config = self._processing_config(config)

        transformed_data = await self._fetch_and_transform_baseline_async(
            peer_id=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
        )
        if subtarget and transformed_data == {subtarget: ""}:
            transformed_data = None  # as the synchronous subscribe

        if (
            transformed_data is not None if subtarget else transformed_data
        ) and config.auto_storage:
            # Store baseline data if auto_storage is enabled
            from ..remote_storage import RemotePeerStore
            from .actor_interface import ActorInterface

            actor_interface = ActorInterface(self._core_actor)
            store = RemotePeerStore(
                actor=actor_interface,
                peer_id=peer_id,
                validate_peer_id=False,
            )
            store.apply_resync_data(
                transformed_data,
                subtarget=subtarget or None,
                resource=resource or None,
                target=target,
            )
            logger.info(f"Stored initial baseline for {peer_id} from {target}")

        # Fetch peer metadata during initial subscription (independent of storage)
        if transformed_data:
            await self._refresh_peer_metadata_async(peer_id)

        return result

    def unsubscribe(self, peer_id: str, subscription_id: str) -> bool:
        """Unsubscribe from a peer's data."""
        # Try to delete remote subscription first
        remote_result = self._core_actor.delete_remote_subscription(
            peerid=peer_id, subid=subscription_id
        )
        if remote_result:
            # Then delete local outbound subscription (callback=True)
            # IMPORTANT: Pass callback=True so RemotePeerStore cleanup happens
            local_result = self._core_actor.delete_subscription(
                peerid=peer_id, subid=subscription_id, callback=True
            )
            return bool(local_result)
        return False

    def unsubscribe_from_peer(self, peer_id: str) -> bool:
        """Unsubscribe from all of a peer's data.

        Cleanup of RemotePeerStore happens automatically in Subscription.delete().
        """
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        success = True
        for sub in subscriptions:
            if not self.unsubscribe(peer_id, sub.subscription_id):
                success = False
        return success

    def notify_subscribers(
        self, target: str, data: dict[str, Any], subtarget: str = "", resource: str = ""
    ) -> None:
        """
        Notify all subscribers of changes to the specified target.

        This will trigger callbacks to all actors subscribed to this target.

        With ``resource``, ``data`` is that resource's whole value. A
        subscriber at resource level is sent it. A subscriber above it
        applies what it is sent as the subtarget's whole value, so for
        ``target="properties"`` it is sent the subtarget's value as stored
        when this is called (3.16; less what its grant excludes): write the
        property first, then notify. The store is read only when such a
        subscriber exists; a subtarget it does not hold (a list's name
        included) sends ``{resource: data}``, as before. For another target
        the library has no store to read: pass the subtarget's whole value
        without ``resource``, or a subscriber above the resource keeps only
        ``{resource: data}``. For a large value consider
        ``Actor.request_resync()``, which sends no data.
        """
        import json

        blob = json.dumps(data) if isinstance(data, dict) else str(data)
        whole: Callable[[], str | None] | None = None
        if target == "properties" and subtarget and resource:
            whole = functools.partial(self._stored_property, subtarget)

        # Only when there is one: an application's override of
        # register_diffs with the older signature keeps working.
        whole_kw: dict[str, Any] = {} if whole is None else {"whole": whole}
        self._core_actor.register_diffs(
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            blob=blob,
            **whole_kw,
        )

    def _stored_property(self, name: str) -> str | None:
        """A property's stored value (JSON text), or None when the store
        holds none under the name."""
        from ..db.exceptions import DbError

        store = self._core_actor.property
        try:
            value = store[name] if store is not None else None
        except DbError:
            raise
        except ValueError:  # a name the store does not key (``list:...``)
            return None
        return value if isinstance(value, str) and value != "" else None

    def get_subscription(
        self, peer_id: str, subscription_id: str
    ) -> SubscriptionInfo | None:
        """Get a specific subscription."""
        sub_data = self._core_actor.get_subscription(
            peerid=peer_id, subid=subscription_id
        )
        if sub_data and isinstance(sub_data, dict):
            return SubscriptionInfo(sub_data)
        return None

    def get_callback_subscription(
        self, peer_id: str, subscription_id: str
    ) -> SubscriptionInfo | None:
        """
        Get a callback subscription (outbound - we subscribed to them).

        Callback subscriptions are ones we initiated - we receive callbacks from the peer.
        This is used when processing incoming callbacks to verify the subscription exists.

        Args:
            peer_id: ID of the peer actor we subscribed to
            subscription_id: ID of the subscription

        Returns:
            SubscriptionInfo if found, None otherwise

        Example:
            # In a callback handler, verify subscription exists
            sub = actor.subscriptions.get_callback_subscription(
                peer_id="peer123",
                subscription_id="sub456"
            )
            if sub:
                # Process the callback
                process_callback_data(data)
        """
        sub_data = self._core_actor.get_subscription(
            peerid=peer_id, subid=subscription_id, callback=True
        )
        # The backends look the row up by peer and id without filtering on
        # the flag: a row this actor holds as publisher (callback false)
        # must not be found here, or a subscriber could post callbacks to its
        # publisher under its own subscription id.
        if sub_data and isinstance(sub_data, dict) and sub_data.get("callback"):
            return SubscriptionInfo(sub_data)
        return None

    def revoke_peer_subscription(self, peer_id: str, subscription_id: str) -> bool:
        """
        Revoke a peer's subscription to our data (delete inbound subscription).

        Use this when you want to terminate a peer's subscription to your actor's data.
        This notifies the peer to delete their outbound subscription and deletes our
        local inbound subscription record. Lifecycle hooks will be executed with
        initiated_by_peer=False.

        Args:
            peer_id: ID of the peer actor
            subscription_id: ID of the inbound subscription to revoke

        Returns:
            True if revoked successfully, False otherwise

        Example:
            # Get inbound subscriptions from a peer
            inbound_subs = actor.subscriptions.get_subscriptions_from_peer("peer123")
            for sub in inbound_subs:
                # Revoke their subscription to us
                actor.subscriptions.revoke_peer_subscription("peer123", sub.subscription_id)
        """
        # Get subscription data before deletion for lifecycle hook
        sub_data = {}
        if self._hooks:
            from ..subscription import Subscription as CoreSubscription

            sub_obj = CoreSubscription(
                actor_id=self._core_actor.id,
                peerid=peer_id,
                subid=subscription_id,
                callback=False,
                config=self._core_actor.config,
            )
            sub_data = sub_obj.subscription if sub_obj.subscription else {}

        # Send DELETE to peer's callback endpoint
        remote_result = self._core_actor.delete_remote_subscription(
            peerid=peer_id, subid=subscription_id
        )

        if remote_result:
            # Delete local inbound subscription record (callback=False)
            local_result = self._core_actor.delete_subscription(
                peerid=peer_id,
                subid=subscription_id,
                callback=False,
            )

            # Execute lifecycle hook after successful deletion
            # initiated_by_peer=False because we initiated the deletion
            if local_result and self._hooks:
                try:
                    from .actor_interface import ActorInterface

                    registry = getattr(
                        self._core_actor.config, "service_registry", None
                    )
                    actor_interface = ActorInterface(
                        self._core_actor, service_registry=registry
                    )
                    self._hooks.execute_lifecycle_hooks(
                        "subscription_deleted",
                        actor=actor_interface,
                        peer_id=peer_id,
                        subscription_id=subscription_id,
                        subscription_data=sub_data,
                        initiated_by_peer=False,
                    )
                    logger.debug(
                        f"Executed subscription_deleted hook for {peer_id}, initiated_by_peer=False"
                    )
                except Exception as e:  # folds DbError: lifecycle hook after the subscription deletion committed
                    # Log hook execution error but don't fail subscription deletion
                    logger.warning(
                        f"Lifecycle hook failed for subscription {subscription_id}: {e}"
                    )

            return bool(local_result)
        return False

    def delete_callback_subscription(self, peer_id: str, subscription_id: str) -> bool:
        """
        Delete a callback subscription (local only, no peer notification).

        This is used when a peer terminates our subscription to them via a callback.
        We just remove our local record without notifying the peer (they already know).

        This is different from unsubscribe() which notifies the peer first.

        Args:
            peer_id: ID of the peer actor
            subscription_id: ID of the subscription to delete

        Returns:
            True if deleted successfully, False otherwise

        Example:
            # Peer sent DELETE callback to terminate our subscription
            deleted = actor.subscriptions.delete_callback_subscription(
                peer_id="peer123",
                subscription_id="sub456"
            )
            if deleted:
                logger.info("Callback subscription removed")
        """
        result = self._core_actor.delete_subscription(
            peerid=peer_id, subid=subscription_id, callback=True
        )
        return bool(result)

    def has_subscribers_for(
        self, target: str, subtarget: str = "", resource: str = ""
    ) -> bool:
        """Check if there are any subscribers for the given target.

        Subscribers are peers who subscribed to us - their subscription records
        have callback=False (we send callbacks to them).
        """
        subscriptions = self.get_subscriptions_for_target(target, subtarget, resource)
        return len([sub for sub in subscriptions if not sub.is_callback]) > 0

    def get_subscribers_for(
        self, target: str, subtarget: str = "", resource: str = ""
    ) -> list[str]:
        """Get list of peer IDs subscribed to the given target.

        Returns peers who subscribed to us - their subscription records
        have callback=False (we send callbacks to them).
        """
        subscriptions = self.get_subscriptions_for_target(target, subtarget, resource)
        return [sub.peer_id for sub in subscriptions if not sub.is_callback]

    def cleanup_peer_subscriptions(self, peer_id: str) -> bool:
        """Remove all subscriptions related to a specific peer."""
        # This is typically called when a trust relationship is deleted
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        success = True
        for sub in subscriptions:
            result = self._core_actor.delete_subscription(
                peerid=peer_id, subid=sub.subscription_id, callback=sub.is_callback
            )
            if not result:
                success = False
        return success

    def create_local_subscription(
        self,
        peer_id: str,
        target: str,
        subtarget: str = "",
        resource: str = "",
        granularity: str = "high",
    ) -> dict[str, Any] | None:
        """
        Create a local subscription (accept an incoming subscription from a peer).

        This is used when another actor subscribes to our data. The subscription
        is stored locally and we will send callbacks to the peer when data changes.

        Args:
            peer_id: ID of the peer actor subscribing to us
            target: Target they're subscribing to (e.g., "properties")
            subtarget: Optional subtarget (e.g., specific property name)
            resource: Optional resource identifier
            granularity: Notification granularity ("high", "low", or "none")

        Returns:
            Dictionary containing subscription details if successful:
            {
                "subscriptionid": "...",
                "peerid": "...",
                "target": "...",
                "subtarget": "...",
                "resource": "...",
                "granularity": "...",
                "sequence": 0
            }
            Returns None if creation failed.
        """
        new_sub = self._core_actor.create_subscription(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
            callback=False,  # Local subscriptions have callback=False (we send callbacks)
        )
        if new_sub and isinstance(new_sub, dict):
            return new_sub
        return None

    def get_subscription_with_diffs(
        self, peer_id: str, subscription_id: str
    ) -> SubscriptionWithDiffs | None:
        """
        Get a subscription object with diff operations support.

        This returns a SubscriptionWithDiffs object that provides methods
        to retrieve and manage subscription diffs (change notifications).

        Args:
            peer_id: ID of the peer actor
            subscription_id: ID of the subscription

        Returns:
            SubscriptionWithDiffs object if subscription exists, None otherwise

        Example:
            sub_with_diffs = actor.subscriptions.get_subscription_with_diffs(
                peer_id="peer123",
                subscription_id="sub456"
            )
            if sub_with_diffs:
                # Get all pending diffs
                diffs = sub_with_diffs.get_diffs()

                # Clear diffs up to sequence 10
                sub_with_diffs.clear_diffs(seqnr=10)
        """
        core_sub = self._core_actor.get_subscription_obj(
            peerid=peer_id, subid=subscription_id
        )
        if core_sub:
            # Verify subscription exists by checking if it has data
            sub_data = core_sub.get()
            if sub_data and len(sub_data) > 0:
                return SubscriptionWithDiffs(core_sub)
        return None

    # =========================================================================
    # Subscription Suspension
    # =========================================================================

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration for a target/subtarget.

        While suspended:
        - Property changes will NOT register diffs
        - No subscription callbacks will be sent
        - Use resume() to lift suspension and trigger resync

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if newly suspended, False if already suspended

        Example:
            # Suspend before bulk operation
            actor.subscriptions.suspend(target="properties", subtarget="memory_travel")

            # Perform bulk updates without triggering callbacks
            for item in bulk_data:
                actor.properties["memory_travel"] = item

            # Resume and notify subscribers to resync
            callbacks_sent = actor.subscriptions.resume(
                target="properties", subtarget="memory_travel"
            )
        """
        return self._core_actor.suspend_subscriptions(target, subtarget)

    def resume(self, target: str, subtarget: str | None = None) -> int:
        """Resume diff registration and send resync callbacks.

        Sends a resync callback to ALL subscriptions matching the target/subtarget,
        telling subscribers to perform a full GET to re-sync their state.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            Number of resync callbacks sent successfully

        Example:
            # Resume after bulk operation
            callbacks_sent = actor.subscriptions.resume(
                target="properties", subtarget="memory_travel"
            )
            print(f"Notified {callbacks_sent} subscribers to resync")
        """
        return self._core_actor.resume_subscriptions(target, subtarget)

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if diff registration is suspended for a target/subtarget.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if suspended, False otherwise

        Raises:
            DbError: the suspension could not be read (3.16; it answered
                False before). In a background job, catch it and retry; do
                not treat it as "not suspended".
        """
        return self._core_actor.is_subscription_suspended(target, subtarget)

    # =========================================================================
    # Pull-Based Sync API
    # =========================================================================

    def _own_trust_path(self, proxy: Any) -> str:
        """Our own trust row at the peer: ``trust/<relationship>/<our id>``
        (``trust/<our id>`` alone routes to the relationship handler, whose
        GET answers 404 whatever the peer holds)."""
        relationship = str(
            (getattr(proxy, "trust", None) or {}).get("relationship") or ""
        )
        return f"trust/{relationship}/{self._core_actor.id}"

    @staticmethod
    def _peer_trust_state(peer_id: str, proxy: Any) -> str:
        """What the probe of our own trust row at the peer says, by status:
        ``exists`` (2xx), ``revoked`` (401, 403 or 404: the peer no longer
        accepts the trust's secret, or holds no row) or ``unknown`` (no
        answer, a server error: the trust is kept)."""
        code = int(getattr(proxy, "last_response_code", 0) or 0)
        if 200 <= code < 300:
            logger.info(
                f"Trust relationship with {peer_id} still exists. "
                f"Subscriptions were deleted but trust is valid."
            )
            return "exists"
        if code in (401, 403, 404):
            logger.warning(
                f"Peer {peer_id} answered {code} for our trust row there; "
                "the trust appears revoked"
            )
            return "revoked"
        return "unknown"

    @staticmethod
    def _probed_secret(proxy: Any) -> str | None:
        """The secret of the trust row the revocation probe was sent with:
        the row the cleanup may delete (3.16)."""
        secret = str((getattr(proxy, "trust", None) or {}).get("secret") or "")
        return secret or None

    def _get_peer_proxy(self, peer_id: str) -> Any:
        """Get an AwProxy for communicating with a peer.

        Args:
            peer_id: The peer actor's ID

        Returns:
            AwProxy instance or None if no trust relationship exists
        """
        from ..aw_proxy import AwProxy

        # Get the trust relationship with this peer
        config = self._core_actor.config
        peer_target = {
            "id": self._core_actor.id,
            "peerid": peer_id,
            "passphrase": None,
        }
        return AwProxy(peer_target=peer_target, config=config)

    def _recorded_sequence(self, peer_id: str, subscription_id: str) -> int:
        """The sequence this subscriber has recorded for a subscription it
        holds, or 0."""
        from ..subscription import Subscription

        sub_obj = Subscription(
            actor_id=self._core_actor.id,
            peerid=peer_id,
            subid=subscription_id,
            callback=True,
            config=self._core_actor.config,
        )
        recorded = (sub_obj.get() or {}).get("sequence", 0) if sub_obj.handle else 0
        return recorded if isinstance(recorded, int) else 0

    def _behind_publisher(
        self, peer_id: str, subscription_id: str, response: dict[str, Any]
    ) -> bool:
        """Whether this subscriber has recorded a lower sequence than the
        publisher answers. A sequence that is not an integer is not
        compared (never behind). Asked only with ``auto_sequence``: without
        it callbacks record no sequence, and the recorded one says nothing
        about what was missed."""
        return self._recorded_sequence(peer_id, subscription_id) < (
            _publisher_sequence(response)
        )

    def _processing_config(
        self, config: "SubscriptionProcessingConfig | None"
    ) -> "SubscriptionProcessingConfig":
        """The configuration a poll or a rebuild runs with: the one passed,
        else the application's (``with_subscription_processing()``), else
        the defaults. A poll called without one used the defaults
        (``auto_storage`` on) whatever the application configured (3.16)."""
        from ..subscription_config import SubscriptionProcessingConfig

        if config is not None:
            return config
        app_config = getattr(self._core_actor.config, "_subscription_config", None)
        if app_config is not None:
            return app_config
        return SubscriptionProcessingConfig(enabled=True)

    def _rebuild_owed(self, peer_id: str, subscription_id: str) -> bool:
        """Whether this subscription's replica owes a rebuild (one that
        failed, or was marked). A read fault answers True: the rebuild then
        keeps its interval."""
        from ..callback_processor import CallbackProcessor
        from .actor_interface import ActorInterface

        try:
            processor = CallbackProcessor(actor=ActorInterface(self._core_actor))
            return bool(processor.rebuild_state(peer_id, subscription_id)["owed"])
        except Exception as e:  # folds DbError: not forced
            logger.warning(f"Reading the rebuild state of {peer_id} faulted: {e}")
            return True

    def _tell_polled_baseline(
        self,
        peer_id: str,
        config: "SubscriptionProcessingConfig | None",
        result: SubscriptionSyncResult,
    ) -> None:
        """A poll that replaced the replica from a baseline tells the
        application's data hooks once, with the baseline, the sequence
        recorded and ``"resync"`` (3.16). Called where the poll returns, on
        the caller's thread and loop: a coroutine hook of the async poll is
        scheduled there, as for a polled diff. Not the legacy
        ``subscription`` callback hook, which no poll path tells."""
        if (
            not result.success
            or result.baseline is None
            or result.baseline_skipped
            or not result.target
        ):
            return
        if (
            result.target == "properties"
            and not result.subtarget
            and not isinstance(result.baseline, dict)
        ):
            return
        from ..handlers.callbacks import run_subscription_data_hooks
        from .actor_interface import ActorInterface

        run_subscription_data_hooks(
            config,
            ActorInterface(self._core_actor),
            peer_id,
            result.target,
            result.baseline,
            result.final_sequence,
            "resync",
        )

    def sync_subscription(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
    ) -> SubscriptionSyncResult:
        """
        Sync a single subscription by fetching and processing pending diffs from the peer.

        This is a pull-based sync that fetches diffs from the peer actor that
        we subscribed to, processes them, and clears them on the peer.

        The application's subscription data hooks are called for each diff
        the poll applies, and once with ``"resync"`` and the whole baseline
        when the poll rebuilt from one and the rebuild settled (an owed
        rebuild, a resync marker, a list diff that could not be applied,
        which was told first, a poll behind the publisher with nothing to
        fetch, or diffs that were all applied already); the result's
        ``baseline`` is that value. A rebuild is run only when it has work:
        ``auto_storage``, or a data hook for the target or ``"*"``; one
        owed that only the legacy ``subscription`` callback hook would hear
        is left for the next callback. Not told: a quiet poll (nothing to
        fetch and the recorded sequence level with the publisher's), a
        baseline another subscription's replica covers or that had an entry
        that failed to store, and a rebuild that did not settle (owed; a
        failed one runs again at most once a minute, and a poll inside that
        minute fails with ``error_code`` 429). A key the replica refuses (a
        reserved name) is in the baseline the hook gets. Without ``config``
        the application's configuration is used.

        A rebuild reserves its attempt in the callback state store, also
        for a subscriber without ``auto_storage`` that has a data hook: a
        fault there raises ``DbError``, as it does with a replica.

        Args:
            peer_id: ID of the peer actor we subscribed to
            subscription_id: ID of the subscription to sync
            config: Optional processing configuration

        Returns:
            SubscriptionSyncResult with sync outcome

        Example:
            result = actor.subscriptions.sync_subscription(
                peer_id="peer123",
                subscription_id="sub456"
            )
            if result.success:
                print(f"Processed {result.diffs_processed} diffs")
            else:
                print(f"Sync failed: {result.error}")
        """
        # Resolved once: the poll and the baseline's hooks use the same one.
        config = self._processing_config(config)
        result = self._poll_subscription(peer_id, subscription_id, config)
        self._tell_polled_baseline(peer_id, config, result)
        return result

    def _poll_subscription(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
    ) -> SubscriptionSyncResult:
        """:meth:`sync_subscription` without the baseline's hook call."""
        from ..callback_processor import CallbackProcessor, CallbackType, ProcessResult
        from ..remote_storage import RemotePeerStore

        # Use default config if not provided
        config = self._processing_config(config)

        # Verify local subscription exists
        sub = self.get_callback_subscription(peer_id, subscription_id)
        if not sub:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Subscription not found",
                error_code=404,
            )

        if self._rebuild_owed_and_due(
            peer_id, subscription_id, config, target=sub.target
        ):
            # An owed rebuild waits for no further traffic (3.16): a sync runs
            # it instead of applying retained diffs to a stale replica.
            return self.rebuild_subscription(peer_id, subscription_id, config=config)

        # Get proxy to peer
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="No trust relationship with peer",
                error_code=404,
            )

        # Fetch diffs from peer
        # Path: /subscriptions/{our_actor_id}/{subscription_id}
        our_actor_id = self._core_actor.id
        path = f"subscriptions/{our_actor_id}/{subscription_id}"

        response = proxy.get_resource(path=path)

        if response is None:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Failed to communicate with peer",
                error_code=proxy.last_response_code or 502,
            )

        if "error" in response:
            error_code = response["error"].get("code", 500)
            error_msg = response["error"].get("message", "Unknown error")
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error=error_msg,
                error_code=error_code,
            )

        # Parse response: {sequence: int, data: [{sequence, timestamp, data}, ...]}
        diffs = response.get("data", [])
        if not isinstance(diffs, list):
            diffs = []

        diffs_fetched = len(diffs)

        if (
            diffs_fetched == 0
            and config.auto_sequence
            # Without a replica and without a data hook for the target
            # there is nothing to rebuild and nobody to tell.
            and rebuilds_for(config, sub.target)
            and self._behind_publisher(peer_id, subscription_id, response)
        ):
            # Behind the publisher with nothing retained to fetch (a gap
            # resync cleared callbacks no hook saw, say): a rebuild, not a
            # refresh, with or without a replica. It deletes what the
            # baseline no longer carries, an empty baseline included, records
            # the sequence only when it settled, stays owed when it did not,
            # and its baseline is the first the hooks hear of what changed.
            # Forced past an interval another path started (a pushed
            # resync's sweep), not past this path's own failure: a rebuild
            # that failed is owed, and is attempted again at most once a
            # minute (inside the interval the poll answers 429). Level with
            # the publisher, the refresh below is the state they already
            # heard about.
            return self.rebuild_subscription(
                peer_id,
                subscription_id,
                config=config,
                force=not self._rebuild_owed(peer_id, subscription_id),
            )

        # If no diffs, fetch baseline data from target resource using shared method
        if diffs_fetched == 0 and config.auto_storage:
            logger.info(
                f"No diffs for subscription {subscription_id}, fetching baseline from target"
            )

            # Fetch and transform baseline data
            transformed_data = self._fetch_and_transform_baseline(
                peer_id=peer_id,
                target=sub.target,
                subtarget=sub.subtarget,
                resource=sub.resource,
            )

            if transformed_data is None:
                # A failed fetch (an error, a redirect, an answer that is not
                # the publisher's own): not a success, and the sequence stays.
                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=False,
                    diffs_fetched=0,
                    diffs_processed=0,
                    final_sequence=0,
                    error=f"The baseline of {sub.subtarget!r} could not be fetched",
                    error_code=502,
                )
            if transformed_data is not None if sub.subtarget else transformed_data:
                # Store baseline data (a single property's falsy value is a
                # value, 3.16)
                from ..remote_storage import RemotePeerStore
                from .actor_interface import ActorInterface

                actor_interface = ActorInterface(self._core_actor)
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )

                store.apply_resync_data(
                    transformed_data,
                    subtarget=sub.subtarget or None,
                    target=sub.target,
                    resource=sub.resource or None,
                )
                logger.info(f"Stored baseline for subscription {subscription_id}")

            # Update local subscription sequence after baseline sync
            final_seq = _publisher_sequence(response)
            if final_seq > 0:
                from ..subscription import Subscription

                sub_obj = Subscription(
                    actor_id=self._core_actor.id,
                    peerid=peer_id,
                    subid=subscription_id,
                    callback=True,
                    config=self._core_actor.config,
                )
                if sub_obj.handle:
                    sub_obj.handle.modify(seqnr=final_seq)
                    logger.info(
                        f"Updated subscription {subscription_id} sequence to {final_seq} "
                        f"after baseline sync"
                    )

            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=True,
                diffs_fetched=0,
                diffs_processed=1,  # Count baseline fetch as 1 processed item
                final_sequence=_publisher_sequence(response),
                # No baseline for the hooks: level with the publisher,
                # this refresh is the replica they already heard about
                # (owner, 2026-11-16).
            )
        elif diffs_fetched == 0:
            # Update local subscription sequence for no-diffs case
            final_seq = _publisher_sequence(response)
            if final_seq > 0:
                from ..subscription import Subscription

                sub_obj = Subscription(
                    actor_id=self._core_actor.id,
                    peerid=peer_id,
                    subid=subscription_id,
                    callback=True,
                    config=self._core_actor.config,
                )
                if sub_obj.handle:
                    sub_obj.handle.modify(seqnr=final_seq)
                    logger.info(
                        f"Updated subscription {subscription_id} sequence to {final_seq} "
                        f"(no diffs, auto_storage disabled)"
                    )

            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=True,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=_publisher_sequence(response),
            )

        # Sort diffs by sequence
        diffs = sorted(diffs, key=lambda d: d.get("sequence", 0))

        # Import ActorInterface for creating the callback processor
        from .actor_interface import ActorInterface

        # Create actor interface for callback processor
        actor_interface = ActorInterface(self._core_actor)

        # Process each diff
        diffs_processed = 0
        in_flight = False
        rebuild_needed = False
        marker_seen = False
        max_sequence = 0

        # Set up handler based on config
        def process_handler(cb):
            """Handler to apply callback data to remote storage."""
            if config.auto_storage:
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )
                if cb.callback_type == CallbackType.RESYNC:
                    applied = store.apply_resync_data(
                        cb.data,
                        subtarget=sub.subtarget or None,
                        target=sub.target,
                        resource=sub.resource or None,
                    )
                    # As the callback handler: a baseline settles an owed
                    # rebuild only when it stored everything and carried each
                    # owed list.
                    owed = CallbackProcessor(actor=actor_interface).rebuild_state(
                        peer_id, subscription_id
                    )["lists"]
                    missing = [n for n in owed if n not in applied]
                    if not applied.skipped and (applied.failed or missing):
                        cb.out_of_step = {
                            "list": (applied.failed or missing)[0],
                            "operation": "resync",
                            "why": "the baseline did not settle the replica",
                        }
                else:
                    applied = store.apply_callback_data(
                        cb.data,
                        subtarget=sub.subtarget or None,
                        target=sub.target,
                        resource=sub.resource or None,
                    )
                    cb.out_of_step = applied.out_of_step
            # The application's data hooks, as a pushed callback runs them
            # (3.16: a poll, a gap resync's included, ran none).
            if not (
                sub.target == "properties"
                and not sub.subtarget
                and not isinstance(cb.data, dict)
            ):
                from ..handlers.callbacks import run_subscription_data_hooks

                run_subscription_data_hooks(
                    config,
                    actor_interface,
                    peer_id,
                    sub.target,
                    cb.data,
                    cb.sequence,
                    cb.callback_type.value,
                )

        # Create callback processor if sequence tracking is enabled
        if config.auto_sequence:
            processor = CallbackProcessor(
                actor=actor_interface,
                gap_timeout_seconds=config.gap_timeout_seconds,
                max_pending=config.max_pending,
            )

            for diff in diffs:
                if diff.get("type") == "resync" and rebuilds_for(config, sub.target):
                    # A resync marker (a ``none`` subscription's resume, or
                    # a client's): handled as a resync, by a rebuild (3.16).
                    marker_seen = True
                    break
                seq = diff.get("sequence", 0)
                data = diff.get("data", {})

                result = processor.process_callback_sync(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    sequence=seq,
                    data=data,
                    callback_type="diff",
                    handler=process_handler,  # stores only with auto_storage; hooks always
                )

                if result == ProcessResult.IN_PROGRESS:
                    # A callback delivery is handling this sequence now: stop
                    # here, so the poll neither clears nor records past it.
                    in_flight = True
                    break

                if result == ProcessResult.REBUILD and not rebuilds_for(
                    config, sub.target
                ):
                    # Owed from before, and nothing a poll can tell would
                    # hear it (no replica, no data hook): left owed for the
                    # next callback, whose legacy hook does (3.16).
                    result = ProcessResult.PROCESSED
                if result == ProcessResult.REBUILD:
                    # The processor advanced through this diff and dropped
                    # the rest of its batch: stop, the rebuild replaces it.
                    # Its baseline is told: the diffs after this one were
                    # never run, and the rebuild clears them (3.16).
                    rebuild_needed = True
                    break

                if result == ProcessResult.PROCESSED:
                    diffs_processed += 1

                if seq > max_sequence:
                    max_sequence = seq
        else:
            # No sequence tracking, just process all diffs
            for diff in diffs:
                if diff.get("type") == "resync" and rebuilds_for(config, sub.target):
                    # A resync marker (a ``none`` subscription's resume, or
                    # a client's): handled as a resync, by a rebuild (3.16).
                    marker_seen = True
                    break
                seq = diff.get("sequence", 0)
                data = diff.get("data", {})

                if config.auto_storage:
                    store = RemotePeerStore(
                        actor=actor_interface,
                        peer_id=peer_id,
                        validate_peer_id=False,
                    )
                    applied = store.apply_callback_data(
                        data,
                        subtarget=sub.subtarget or None,
                        target=sub.target,
                        resource=sub.resource or None,
                    )
                    if applied.out_of_step:
                        # Records nothing for this or later diffs: the
                        # rebuild replaces the replica.
                        rebuild_needed = True
                        break
                if not (
                    sub.target == "properties"
                    and not sub.subtarget
                    and not isinstance(data, dict)
                ):
                    from ..handlers.callbacks import run_subscription_data_hooks

                    run_subscription_data_hooks(
                        config, actor_interface, peer_id, sub.target, data, seq, "diff"
                    )

                diffs_processed += 1
                if seq > max_sequence:
                    max_sequence = seq

        if marker_seen:
            return self._rebuild_for_marker(peer_id, subscription_id, config)
        if rebuild_needed:
            rebuilt = self.rebuild_subscription(peer_id, subscription_id, config=config)
            return rebuilt

        # If we fetched diffs but processed none (all duplicates/rejected),
        # fetch baseline to ensure we're in sync
        if (
            diffs_fetched > 0
            and diffs_processed == 0
            and config.auto_storage
            and not in_flight
        ):
            logger.warning(
                f"Fetched {diffs_fetched} diffs but processed 0 (likely duplicates), "
                f"fetching baseline for subscription {subscription_id}"
            )

            # Through the shared fetch: a subtarget's list, value, gone and
            # failure are told apart as everywhere else (3.16).
            transformed_data = self._fetch_and_transform_baseline(
                peer_id=peer_id,
                target=sub.target,
                subtarget=sub.subtarget or None,
                resource=sub.resource or None,
            )

            if transformed_data is None:
                # As on the no-diffs path: a single property's baseline that
                # could not be fetched is a failed sync.
                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=False,
                    diffs_fetched=diffs_fetched,
                    diffs_processed=0,
                    final_sequence=0,
                    error=f"The baseline of {sub.subtarget!r} could not be fetched",
                    error_code=502,
                )
            if transformed_data is not None:
                # Apply baseline data
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )
                reapplied = store.apply_resync_data(
                    transformed_data,
                    subtarget=sub.subtarget or None,
                    target=sub.target,
                    resource=sub.resource or None,
                )
                logger.info(
                    f"Stored baseline data for subscription {subscription_id} "
                    f"after rejecting {diffs_fetched} duplicate diffs"
                )

                # Update sequence from response
                final_seq = _publisher_sequence(response)
                if final_seq > 0:
                    from ..subscription import Subscription

                    sub_obj = Subscription(
                        actor_id=self._core_actor.id,
                        peerid=peer_id,
                        subid=subscription_id,
                        callback=True,
                        config=self._core_actor.config,
                    )
                    if sub_obj.handle:
                        sub_obj.handle.modify(seqnr=final_seq)
                        logger.info(
                            f"Updated subscription {subscription_id} sequence to {final_seq} "
                            f"after baseline sync (duplicate diffs rejected)"
                        )

                    # Clear the duplicate diffs on the publisher to prevent repeated fetches
                    clear_response = proxy.change_resource(
                        path=path, params={"sequence": final_seq}
                    )
                    if clear_response is None or "error" in (clear_response or {}):
                        # Log warning but don't fail the sync
                        _log_peer_clear_failure(
                            proxy,
                            f"Failed to clear duplicate diffs on peer {peer_id} for subscription "
                            f"{subscription_id}, sequence {final_seq}",
                        )
                    else:
                        logger.debug(
                            f"Cleared duplicate diffs on peer {peer_id} for subscription "
                            f"{subscription_id} up to sequence {final_seq}"
                        )

                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=True,
                    diffs_fetched=diffs_fetched,
                    diffs_processed=1,  # Count baseline as 1 processed
                    final_sequence=_publisher_sequence(response),
                    # Told to the hooks only when all of it was applied, and
                    # only when the sequence was recorded: otherwise nothing
                    # was cleared and the same duplicates come back. Not
                    # while a rebuild is owed: that rebuild tells it.
                    baseline=(
                        None
                        if reapplied.skipped
                        or reapplied.failed
                        or _publisher_sequence(response) <= 0
                        or self._rebuild_owed(peer_id, subscription_id)
                        else transformed_data
                    ),
                    target=sub.target,
                    subtarget=sub.subtarget or None,
                )

        # Clear processed diffs on peer
        if max_sequence > 0:
            clear_response = proxy.change_resource(
                path=path, params={"sequence": max_sequence}
            )
            if clear_response is None or "error" in (clear_response or {}):
                # Log warning but don't fail the sync
                _log_peer_clear_failure(
                    proxy,
                    f"Failed to clear diffs on peer {peer_id} for subscription "
                    f"{subscription_id}, sequence {max_sequence}",
                )

        # Update local subscription sequence after processing diffs
        if max_sequence > 0:
            from ..subscription import Subscription

            sub_obj = Subscription(
                actor_id=self._core_actor.id,
                peerid=peer_id,
                subid=subscription_id,
                callback=True,
                config=self._core_actor.config,
            )
            # Only upward, and not past a live claim: a callback handling a
            # later sequence may have recorded it already (the processor
            # records each batch it handles), and a lower write here would
            # set it back.
            stored = (sub_obj.get() or {}).get("sequence", 0) if sub_obj.handle else 0
            if sub_obj.handle and not in_flight and max_sequence > int(stored or 0):
                sub_obj.handle.modify(seqnr=max_sequence)
                logger.info(
                    f"Updated subscription {subscription_id} sequence to {max_sequence} "
                    f"after processing {diffs_processed} diffs"
                )

        return SubscriptionSyncResult(
            subscription_id=subscription_id,
            success=True,
            diffs_fetched=diffs_fetched,
            diffs_processed=diffs_processed,
            final_sequence=max_sequence,
            in_flight=in_flight,
        )

    def _transform_baseline_list_properties(
        self,
        baseline_data: dict[str, Any],
        peer_id: str,
        target: str,
    ) -> dict[str, Any]:
        """
        Transform list property metadata into actual list items for baseline sync.

        When baseline fetch returns list metadata ({"_list": true, "count": N}),
        this fetches the actual items from the remote peer via ActingWeb protocol
        and transforms to the format expected by apply_resync_data().

        Args:
            baseline_data: Baseline response from remote peer (may contain list metadata)
            peer_id: ID of remote peer we're syncing from
            target: Subscription target (e.g., "properties")

        Returns:
            Transformed data with lists in format {"property_name": {"_list": true, "items": [...]}}
        """
        # Create result dict (shallow copy)
        result = dict(baseline_data)

        # Get proxy for fetching list items from remote peer
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            logger.warning(
                f"No trust with peer {peer_id}, skipping list transformation"
            )
            return baseline_data

        # Process each property in baseline data
        for property_name, value in baseline_data.items():
            # Skip if not a dict
            if not isinstance(value, dict):
                continue

            # Check for list metadata format: {"_list": true, "count": N}
            if not value.get("_list"):
                continue

            # Skip if already has items
            if "items" in value:
                continue

            # Fetch actual list items from remote peer
            try:
                list_path = f"{target}/{property_name}"
                logger.debug(
                    f"Fetching list items for {property_name} from peer {peer_id} at {list_path}"
                )

                # Fetch via ActingWeb protocol (remote peer enforces permissions)
                response = proxy.get_resource(path=list_path)

                # Validate response is a list
                if response is None:
                    logger.warning(
                        f"No response when fetching list {property_name} from peer {peer_id}"
                    )
                    continue

                if "error" in response:
                    logger.warning(
                        f"Error fetching list {property_name} from peer {peer_id}: {response.get('error')}"
                    )
                    continue

                if not isinstance(response, list):
                    logger.error(
                        f"Invalid response for list {property_name} from peer {peer_id}: "
                        f"expected list, got {type(response).__name__}"
                    )
                    continue

                # Transform to flag-based format with items
                result[property_name] = {"_list": True, "items": response}

                # Log warning for large lists
                if len(response) > 100:
                    logger.warning(
                        f"List property {property_name} from peer {peer_id} has {len(response)} items. "
                        f"Consider using subtarget subscriptions for better performance."
                    )

                logger.debug(
                    f"Successfully fetched {len(response)} items for list {property_name} from peer {peer_id}"
                )

            except Exception as e:  # folds DbError: peer HTTP only
                # Log error but continue processing other properties
                logger.error(
                    f"Error fetching list {property_name} from peer {peer_id}: {e}",
                    exc_info=True,
                )
                # Keep metadata as-is (fail gracefully)
                continue

        return result

    async def _transform_baseline_list_properties_async(
        self,
        baseline_data: dict[str, Any],
        peer_id: str,
        target: str,
    ) -> dict[str, Any]:
        """
        Async version: Transform list property metadata into actual list items for baseline sync.

        When baseline fetch returns list metadata ({"_list": true, "count": N}),
        this fetches the actual items from the remote peer via ActingWeb protocol
        and transforms to the format expected by apply_resync_data().

        Args:
            baseline_data: Baseline response from remote peer (may contain list metadata)
            peer_id: ID of remote peer we're syncing from
            target: Subscription target (e.g., "properties")

        Returns:
            Transformed data with lists in format {"property_name": {"_list": true, "items": [...]}}
        """
        # Create result dict (shallow copy)
        result = dict(baseline_data)

        # Get proxy for fetching list items from remote peer
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            logger.warning(
                f"No trust with peer {peer_id}, skipping list transformation"
            )
            return baseline_data

        # Process each property in baseline data
        for property_name, value in baseline_data.items():
            # Skip if not a dict
            if not isinstance(value, dict):
                continue

            # Check for list metadata format: {"_list": true, "count": N}
            if not value.get("_list"):
                continue

            # Skip if already has items
            if "items" in value:
                continue

            # Fetch actual list items from remote peer
            try:
                list_path = f"{target}/{property_name}"
                logger.debug(
                    f"Fetching list items for {property_name} from peer {peer_id} at {list_path}"
                )

                # Fetch via ActingWeb protocol (remote peer enforces permissions)
                response = await proxy.get_resource_async(path=list_path)

                # Validate response is a list
                if response is None:
                    logger.warning(
                        f"No response when fetching list {property_name} from peer {peer_id}"
                    )
                    continue

                if "error" in response:
                    logger.warning(
                        f"Error fetching list {property_name} from peer {peer_id}: {response.get('error')}"
                    )
                    continue

                if not isinstance(response, list):
                    logger.error(
                        f"Invalid response for list {property_name} from peer {peer_id}: "
                        f"expected list, got {type(response).__name__}"
                    )
                    continue

                # Transform to flag-based format with items
                result[property_name] = {"_list": True, "items": response}

                # Log warning for large lists
                if len(response) > 100:
                    logger.warning(
                        f"List property {property_name} from peer {peer_id} has {len(response)} items. "
                        f"Consider using subtarget subscriptions for better performance."
                    )

                logger.debug(
                    f"Successfully fetched {len(response)} items for list {property_name} from peer {peer_id}"
                )

            except Exception as e:  # folds DbError: peer HTTP only
                # Log error but continue processing other properties
                logger.error(
                    f"Error fetching list {property_name} from peer {peer_id}: {e}",
                    exc_info=True,
                )
                # Keep metadata as-is (fail gracefully)
                continue

        return result

    def sync_peer(
        self,
        peer_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
        force_refresh: bool = False,
    ) -> PeerSyncResult:
        """
        Sync all outbound subscriptions to a peer.

        Fetches and processes pending diffs for all subscriptions where
        we subscribed to the specified peer.

        Args:
            peer_id: ID of the peer actor
            config: Optional processing configuration
            force_refresh: If True, bypass capability cache staleness checks
                and always refetch. Use for manual/developer-triggered syncs.

        Returns:
            PeerSyncResult with aggregate sync outcome

        Example:
            result = actor.subscriptions.sync_peer("peer123")
            if result.success:
                print(f"Synced {result.subscriptions_synced} subscriptions, "
                      f"{result.total_diffs_processed} diffs total")
            else:
                for sub_result in result.subscription_results:
                    if not sub_result.success:
                        print(f"Failed: {sub_result.subscription_id}: {sub_result.error}")
        """
        # Get all outbound subscriptions to this peer
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        outbound_subs = [s for s in subscriptions if s.is_outbound]

        if not outbound_subs:
            return PeerSyncResult(
                peer_id=peer_id,
                success=True,
                subscriptions_synced=0,
                total_diffs_processed=0,
                subscription_results=[],
            )

        # Sync each subscription
        results: list[SubscriptionSyncResult] = []
        total_diffs = 0
        all_success = True

        for sub in outbound_subs:
            result = self.sync_subscription(
                peer_id=peer_id,
                subscription_id=sub.subscription_id,
                config=config,
            )
            results.append(result)
            total_diffs += result.diffs_processed
            if not result.success:
                all_success = False

        # Detect revoked trust: if ALL subscription syncs failed with 404, the peer may have
        # revoked the trust relationship. Verify by checking if peer actor still exists.
        all_subscriptions_404 = results and all(
            not r.success and r.error_code == 404 for r in results
        )
        if all_subscriptions_404:
            logger.warning(
                f"All {len(results)} subscription(s) failed with 404 for peer {peer_id}. "
                f"Verifying if peer actor exists or trust has been revoked."
            )

            # Verify trust relationship still exists from peer's perspective
            proxy = self._get_peer_proxy(peer_id)
            state = "unknown"
            if proxy:
                try:
                    proxy.get_resource(path=self._own_trust_path(proxy))
                except Exception as e:  # folds DbError: peer HTTP only
                    logger.warning(f"Exception verifying trust with {peer_id}: {e}")
                state = self._peer_trust_state(peer_id, proxy)
            trust_exists = state == "exists"

            # Only delete trust if peer's trust record doesn't exist or we can't access it
            if trust_exists:
                logger.info(
                    f"Trust with {peer_id} still exists, but subscriptions are gone. "
                    f"Cleaning up local subscriptions that were deleted by peer."
                )
                # Clean up the dead subscriptions locally
                try:
                    for result in results:
                        if not result.success and result.error_code == 404:
                            sub = self.get_callback_subscription(
                                peer_id, result.subscription_id
                            )
                            if sub:
                                logger.info(
                                    f"Deleting local subscription {result.subscription_id} - "
                                    f"peer deleted it but trust remains valid."
                                )
                                sub_obj = self._core_actor.get_subscription_obj(
                                    peerid=peer_id,
                                    subid=result.subscription_id,
                                    callback=sub.is_callback,
                                )
                                if sub_obj:
                                    sub_obj.delete()
                except DbError:
                    raise
                except Exception as e:
                    logger.error(
                        f"Error cleaning up dead subscriptions for {peer_id}: {e}",
                        exc_info=True,
                    )
                finally:
                    # The deletes went to storage, not through the core
                    # actor: its memo would keep the deleted rows (3.16).
                    self._core_actor.subs_list = None
            elif state == "unknown":
                logger.warning(
                    f"Could not tell whether {peer_id} still trusts this actor; "
                    "the trust is kept and the next sync asks again"
                )
            else:
                logger.warning(
                    f"Peer {peer_id} no longer holds this trust. "
                    f"Trust has been revoked. Cleaning up locally."
                )
                try:
                    # trust_deleted fires through TrustManager.fire_deleted,
                    # with the row the delete read, after the delete found it
                    # and before anything local goes (3.16): a row already
                    # gone fires nothing (it fired with {} and "friend").
                    from .actor_interface import ActorInterface

                    actor_interface = ActorInterface(self._core_actor)

                    def before_local_delete(row: dict[str, Any]) -> None:
                        # fire_deleted logs a hook's error, lets DbError through.
                        actor_interface.trust.fire_deleted(row, initiated_by_peer=True)

                    # Delete local trust relationship without notifying peer
                    # (already revoked): only the row the probe used, so a
                    # re-pair meanwhile keeps its row (3.16).
                    deleted = self._core_actor.delete_reciprocal_trust(
                        peerid=peer_id,
                        delete_peer=False,
                        expected_secret=self._probed_secret(proxy),
                        before_local_delete=before_local_delete,
                    )
                    if deleted:
                        logger.info(
                            f"Successfully cleaned up revoked trust relationship with {peer_id}"
                        )
                        return PeerSyncResult(
                            peer_id=peer_id,
                            success=False,
                            subscriptions_synced=0,
                            total_diffs_processed=total_diffs,
                            subscription_results=results,
                            error="Trust relationship has been revoked by peer",
                        )
                    else:
                        logger.warning(
                            f"Failed to delete trust relationship with {peer_id}"
                        )
                except TrustReplaced:
                    # Either before anything ran, or (the remaining window of
                    # the deletion invariants) after trust_deleted fired and
                    # the local cleanup ran: the new row stands either way.
                    logger.warning(
                        f"Trust with {peer_id} was re-paired during the "
                        "revocation cleanup; the new row is kept (if "
                        "trust_deleted already fired, the local cleanup "
                        "it announced has run)"
                    )
                except DbError:
                    raise
                except Exception as e:
                    logger.error(
                        f"Exception while cleaning up revoked trust with {peer_id}: {e}"
                    )

        # Refresh peer profile if configured
        # Try to use already-synced properties data first to avoid redundant fetch
        actor_config = self._core_actor.config
        actor_id = self._core_actor.id
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_profile_attributes", None)
        ):
            try:
                from ..peer_profile import fetch_peer_profile, get_peer_profile_store

                # Try to extract profile from synced properties
                profile, profile_extracted = self._extract_profile_from_remote_store(
                    peer_id=peer_id,
                    actor_id=actor_id,
                    actor_config=actor_config,
                )

                # Only fetch if we couldn't extract from synced data
                if not profile_extracted:
                    profile = fetch_peer_profile(
                        actor_id=actor_id,
                        peer_id=peer_id,
                        config=actor_config,
                        attributes=actor_config.peer_profile_attributes,
                    )
                    logger.debug(
                        f"Fetched peer profile for {peer_id} via fallback (extraction failed)"
                    )
                else:
                    logger.debug(
                        f"Extracted peer profile from synced properties for {peer_id}"
                    )

                store = get_peer_profile_store(actor_config)
                store.store_profile(profile)
            except Exception as e:  # folds DbError: best-effort peer profile cache refresh after the sync committed
                logger.warning(f"Failed to refresh peer profile during sync: {e}")

        # Refresh peer capabilities if configured (with staleness check)
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_capabilities_caching", False)
        ):
            try:
                from ..peer_capabilities import (
                    fetch_peer_methods_and_actions,
                    get_cached_capabilities_store,
                )

                store = get_cached_capabilities_store(actor_config)

                # Check cache staleness (skip if force_refresh)
                should_fetch = force_refresh
                if not force_refresh:
                    should_fetch = self._is_capability_cache_stale(
                        store, actor_id, peer_id, actor_config
                    )

                if should_fetch:
                    capabilities = fetch_peer_methods_and_actions(
                        actor_id=actor_id,
                        peer_id=peer_id,
                        config=actor_config,
                    )
                    store.store_capabilities(capabilities)
                    logger.debug(
                        f"Refreshed peer capabilities during sync_peer for {peer_id}"
                    )
                else:
                    logger.debug(
                        f"Using cached capabilities for {peer_id} (cache is fresh)"
                    )
            except Exception as e:  # folds DbError: best-effort peer capabilities cache refresh after the sync committed
                logger.warning(f"Failed to refresh peer capabilities during sync: {e}")

        return PeerSyncResult(
            peer_id=peer_id,
            success=all_success,
            subscriptions_synced=len([r for r in results if r.success]),
            total_diffs_processed=total_diffs,
            subscription_results=results,
        )

    async def sync_subscription_async(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
    ) -> SubscriptionSyncResult:
        """
        Async version of sync_subscription.

        Sync a single subscription by fetching and processing pending diffs from the peer.

        Args:
            peer_id: ID of the peer actor we subscribed to
            subscription_id: ID of the subscription to sync
            config: Optional processing configuration

        Returns:
            SubscriptionSyncResult with sync outcome

        Example:
            result = await actor.subscriptions.sync_subscription_async(
                peer_id="peer123",
                subscription_id="sub456"
            )
        """
        # Resolved once: the poll and the baseline's hooks use the same one.
        config = self._processing_config(config)
        result = await self._poll_subscription_async(peer_id, subscription_id, config)
        # After the await, on the caller's loop: a rebuild runs in a worker
        # thread, and a coroutine hook must not be run from there.
        self._tell_polled_baseline(peer_id, config, result)
        return result

    async def _poll_subscription_async(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
    ) -> SubscriptionSyncResult:
        """:meth:`sync_subscription_async` without the baseline's hook call."""
        from ..callback_processor import CallbackProcessor, CallbackType, ProcessResult
        from ..remote_storage import RemotePeerStore

        # Use default config if not provided
        config = self._processing_config(config)

        # Verify local subscription exists
        sub = self.get_callback_subscription(peer_id, subscription_id)
        if not sub:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Subscription not found",
                error_code=404,
            )

        if self._rebuild_owed_and_due(
            peer_id, subscription_id, config, target=sub.target
        ):
            return await self.rebuild_subscription_async(
                peer_id, subscription_id, config=config
            )

        # Get proxy to peer
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="No trust relationship with peer",
                error_code=404,
            )

        # Fetch diffs from peer (async)
        our_actor_id = self._core_actor.id
        path = f"subscriptions/{our_actor_id}/{subscription_id}"

        response = await proxy.get_resource_async(path=path)

        if response is None:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Failed to communicate with peer",
                error_code=proxy.last_response_code or 502,
            )

        if "error" in response:
            error_code = response["error"].get("code", 500)
            error_msg = response["error"].get("message", "Unknown error")
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error=error_msg,
                error_code=error_code,
            )

        # Parse response
        diffs = response.get("data", [])
        if not isinstance(diffs, list):
            diffs = []

        diffs_fetched = len(diffs)

        if (
            diffs_fetched == 0
            and config.auto_sequence
            # Without a replica and without a data hook for the target
            # there is nothing to rebuild and nobody to tell.
            and rebuilds_for(config, sub.target)
            and self._behind_publisher(peer_id, subscription_id, response)
        ):
            # As the synchronous poll: behind, a rebuild.
            return await self.rebuild_subscription_async(
                peer_id,
                subscription_id,
                config=config,
                force=not self._rebuild_owed(peer_id, subscription_id),
            )

        # If no diffs, fetch baseline data from target resource using shared method
        if diffs_fetched == 0 and config.auto_storage:
            logger.info(
                f"No diffs for subscription {subscription_id}, fetching baseline from target"
            )

            # Fetch and transform baseline data
            transformed_data = await self._fetch_and_transform_baseline_async(
                peer_id=peer_id,
                target=sub.target,
                subtarget=sub.subtarget,
                resource=sub.resource,
            )

            if transformed_data is None:
                # A failed fetch (an error, a redirect, an answer that is not
                # the publisher's own): not a success, and the sequence stays.
                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=False,
                    diffs_fetched=0,
                    diffs_processed=0,
                    final_sequence=0,
                    error=f"The baseline of {sub.subtarget!r} could not be fetched",
                    error_code=502,
                )
            if transformed_data is not None if sub.subtarget else transformed_data:
                # Store baseline data (a single property's falsy value is a
                # value, 3.16)
                from ..remote_storage import RemotePeerStore
                from .actor_interface import ActorInterface

                actor_interface = ActorInterface(self._core_actor)
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )

                store.apply_resync_data(
                    transformed_data,
                    subtarget=sub.subtarget or None,
                    target=sub.target,
                    resource=sub.resource or None,
                )
                logger.info(f"Stored baseline for subscription {subscription_id}")

            # Update local subscription sequence after baseline sync
            final_seq = _publisher_sequence(response)
            if final_seq > 0:
                from ..subscription import Subscription

                sub_obj = Subscription(
                    actor_id=self._core_actor.id,
                    peerid=peer_id,
                    subid=subscription_id,
                    callback=True,
                    config=self._core_actor.config,
                )
                if sub_obj.handle:
                    sub_obj.handle.modify(seqnr=final_seq)
                    logger.info(
                        f"Updated subscription {subscription_id} sequence to {final_seq} "
                        f"after baseline sync"
                    )

            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=True,
                diffs_fetched=0,
                diffs_processed=1,  # Count baseline fetch as 1 processed item
                final_sequence=_publisher_sequence(response),
                # No baseline for the hooks: level with the publisher,
                # this refresh is the replica they already heard about
                # (owner, 2026-11-16).
            )
        elif diffs_fetched == 0:
            # Update local subscription sequence for no-diffs case
            final_seq = _publisher_sequence(response)
            if final_seq > 0:
                from ..subscription import Subscription

                sub_obj = Subscription(
                    actor_id=self._core_actor.id,
                    peerid=peer_id,
                    subid=subscription_id,
                    callback=True,
                    config=self._core_actor.config,
                )
                if sub_obj.handle:
                    sub_obj.handle.modify(seqnr=final_seq)
                    logger.info(
                        f"Updated subscription {subscription_id} sequence to {final_seq} "
                        f"(no diffs, auto_storage disabled)"
                    )

            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=True,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=_publisher_sequence(response),
            )

        # Sort diffs by sequence
        diffs = sorted(diffs, key=lambda d: d.get("sequence", 0))

        from .actor_interface import ActorInterface

        actor_interface = ActorInterface(self._core_actor)

        diffs_processed = 0
        in_flight = False
        rebuild_needed = False
        marker_seen = False
        max_sequence = 0

        # Async handler for callback processing
        async def process_handler_async(cb):
            """Async handler to apply callback data to remote storage."""
            if config.auto_storage:
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )
                if cb.callback_type == CallbackType.RESYNC:
                    applied = store.apply_resync_data(
                        cb.data,
                        subtarget=sub.subtarget or None,
                        target=sub.target,
                        resource=sub.resource or None,
                    )
                    # As the callback handler: a baseline settles an owed
                    # rebuild only when it stored everything and carried each
                    # owed list.
                    owed = CallbackProcessor(actor=actor_interface).rebuild_state(
                        peer_id, subscription_id
                    )["lists"]
                    missing = [n for n in owed if n not in applied]
                    if not applied.skipped and (applied.failed or missing):
                        cb.out_of_step = {
                            "list": (applied.failed or missing)[0],
                            "operation": "resync",
                            "why": "the baseline did not settle the replica",
                        }
                else:
                    applied = store.apply_callback_data(
                        cb.data,
                        subtarget=sub.subtarget or None,
                        target=sub.target,
                        resource=sub.resource or None,
                    )
                    cb.out_of_step = applied.out_of_step
            # The application's data hooks, as a pushed callback runs them
            # (3.16: a poll, a gap resync's included, ran none).
            if not (
                sub.target == "properties"
                and not sub.subtarget
                and not isinstance(cb.data, dict)
            ):
                from ..handlers.callbacks import run_subscription_data_hooks

                run_subscription_data_hooks(
                    config,
                    actor_interface,
                    peer_id,
                    sub.target,
                    cb.data,
                    cb.sequence,
                    cb.callback_type.value,
                )

        if config.auto_sequence:
            processor = CallbackProcessor(
                actor=actor_interface,
                gap_timeout_seconds=config.gap_timeout_seconds,
                max_pending=config.max_pending,
            )

            for diff in diffs:
                if diff.get("type") == "resync" and rebuilds_for(config, sub.target):
                    # A resync marker (a ``none`` subscription's resume, or
                    # a client's): handled as a resync, by a rebuild (3.16).
                    marker_seen = True
                    break
                seq = diff.get("sequence", 0)
                data = diff.get("data", {})

                result = await processor.process_callback(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    sequence=seq,
                    data=data,
                    callback_type="diff",
                    handler=process_handler_async,  # stores only with auto_storage; hooks always
                )

                if result == ProcessResult.IN_PROGRESS:
                    # A callback delivery is handling this sequence now: stop
                    # here, so the poll neither clears nor records past it.
                    in_flight = True
                    break

                if result == ProcessResult.REBUILD and not rebuilds_for(
                    config, sub.target
                ):
                    # Owed from before, and nothing a poll can tell would
                    # hear it (no replica, no data hook): left owed for the
                    # next callback, whose legacy hook does (3.16).
                    result = ProcessResult.PROCESSED
                if result == ProcessResult.REBUILD:
                    # The processor advanced through this diff and dropped
                    # the rest of its batch: stop, the rebuild replaces it.
                    # Its baseline is told: the diffs after this one were
                    # never run, and the rebuild clears them (3.16).
                    rebuild_needed = True
                    break

                if result == ProcessResult.PROCESSED:
                    diffs_processed += 1

                if seq > max_sequence:
                    max_sequence = seq
        else:
            for diff in diffs:
                if diff.get("type") == "resync" and rebuilds_for(config, sub.target):
                    # A resync marker (a ``none`` subscription's resume, or
                    # a client's): handled as a resync, by a rebuild (3.16).
                    marker_seen = True
                    break
                seq = diff.get("sequence", 0)
                data = diff.get("data", {})

                if config.auto_storage:
                    store = RemotePeerStore(
                        actor=actor_interface,
                        peer_id=peer_id,
                        validate_peer_id=False,
                    )
                    applied = store.apply_callback_data(
                        data,
                        subtarget=sub.subtarget or None,
                        target=sub.target,
                        resource=sub.resource or None,
                    )
                    if applied.out_of_step:
                        # Records nothing for this or later diffs: the
                        # rebuild replaces the replica.
                        rebuild_needed = True
                        break
                if not (
                    sub.target == "properties"
                    and not sub.subtarget
                    and not isinstance(data, dict)
                ):
                    from ..handlers.callbacks import run_subscription_data_hooks

                    run_subscription_data_hooks(
                        config, actor_interface, peer_id, sub.target, data, seq, "diff"
                    )

                diffs_processed += 1
                if seq > max_sequence:
                    max_sequence = seq

        if marker_seen:
            import asyncio

            return await asyncio.to_thread(
                self._rebuild_for_marker, peer_id, subscription_id, config
            )
        if rebuild_needed:
            rebuilt = await self.rebuild_subscription_async(
                peer_id, subscription_id, config=config
            )
            return rebuilt

        # If we fetched diffs but processed none (all duplicates/rejected),
        # fetch baseline to ensure we're in sync
        if (
            diffs_fetched > 0
            and diffs_processed == 0
            and config.auto_storage
            and not in_flight
        ):
            logger.warning(
                f"Fetched {diffs_fetched} diffs but processed 0 (likely duplicates), "
                f"fetching baseline for subscription {subscription_id}"
            )

            # Through the shared fetch (as the synchronous sync).
            transformed_data = await self._fetch_and_transform_baseline_async(
                peer_id=peer_id,
                target=sub.target,
                subtarget=sub.subtarget or None,
                resource=sub.resource or None,
            )

            if transformed_data is None:
                # As on the no-diffs path: a single property's baseline that
                # could not be fetched is a failed sync.
                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=False,
                    diffs_fetched=diffs_fetched,
                    diffs_processed=0,
                    final_sequence=0,
                    error=f"The baseline of {sub.subtarget!r} could not be fetched",
                    error_code=502,
                )
            if transformed_data is not None:
                # Apply baseline data
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )
                reapplied = store.apply_resync_data(
                    transformed_data,
                    subtarget=sub.subtarget or None,
                    target=sub.target,
                    resource=sub.resource or None,
                )
                logger.info(
                    f"Stored baseline data for subscription {subscription_id} "
                    f"after rejecting {diffs_fetched} duplicate diffs"
                )

                # Update sequence from response
                final_seq = _publisher_sequence(response)
                if final_seq > 0:
                    from ..subscription import Subscription

                    sub_obj = Subscription(
                        actor_id=self._core_actor.id,
                        peerid=peer_id,
                        subid=subscription_id,
                        callback=True,
                        config=self._core_actor.config,
                    )
                    if sub_obj.handle:
                        sub_obj.handle.modify(seqnr=final_seq)
                        logger.info(
                            f"Updated subscription {subscription_id} sequence to {final_seq} "
                            f"after baseline sync (duplicate diffs rejected)"
                        )

                    # Clear the duplicate diffs on the publisher to prevent repeated fetches
                    clear_response = await proxy.change_resource_async(
                        path=path, params={"sequence": final_seq}
                    )
                    if clear_response is None or "error" in (clear_response or {}):
                        # Log warning but don't fail the sync
                        _log_peer_clear_failure(
                            proxy,
                            f"Failed to clear duplicate diffs on peer {peer_id} for subscription "
                            f"{subscription_id}, sequence {final_seq}",
                        )
                    else:
                        logger.debug(
                            f"Cleared duplicate diffs on peer {peer_id} for subscription "
                            f"{subscription_id} up to sequence {final_seq}"
                        )

                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=True,
                    diffs_fetched=diffs_fetched,
                    diffs_processed=1,  # Count baseline as 1 processed
                    final_sequence=_publisher_sequence(response),
                    # Told to the hooks only when all of it was applied, and
                    # only when the sequence was recorded: otherwise nothing
                    # was cleared and the same duplicates come back. Not
                    # while a rebuild is owed: that rebuild tells it.
                    baseline=(
                        None
                        if reapplied.skipped
                        or reapplied.failed
                        or _publisher_sequence(response) <= 0
                        or self._rebuild_owed(peer_id, subscription_id)
                        else transformed_data
                    ),
                    target=sub.target,
                    subtarget=sub.subtarget or None,
                )

        # Clear processed diffs on peer (async)
        if max_sequence > 0:
            clear_response = await proxy.change_resource_async(
                path=path, params={"sequence": max_sequence}
            )
            if clear_response is None or "error" in (clear_response or {}):
                _log_peer_clear_failure(
                    proxy,
                    f"Failed to clear diffs on peer {peer_id} for subscription "
                    f"{subscription_id}, sequence {max_sequence}",
                )

        # Update local subscription sequence after processing diffs
        if max_sequence > 0:
            from ..subscription import Subscription

            sub_obj = Subscription(
                actor_id=self._core_actor.id,
                peerid=peer_id,
                subid=subscription_id,
                callback=True,
                config=self._core_actor.config,
            )
            # Only upward, and not past a live claim: a callback handling a
            # later sequence may have recorded it already (the processor
            # records each batch it handles), and a lower write here would
            # set it back.
            stored = (sub_obj.get() or {}).get("sequence", 0) if sub_obj.handle else 0
            if sub_obj.handle and not in_flight and max_sequence > int(stored or 0):
                sub_obj.handle.modify(seqnr=max_sequence)
                logger.info(
                    f"Updated subscription {subscription_id} sequence to {max_sequence} "
                    f"after processing {diffs_processed} diffs"
                )

        return SubscriptionSyncResult(
            subscription_id=subscription_id,
            success=True,
            diffs_fetched=diffs_fetched,
            diffs_processed=diffs_processed,
            final_sequence=max_sequence,
            in_flight=in_flight,
        )

    def _rebuild_for_marker(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None",
    ) -> SubscriptionSyncResult:
        """A polled resync marker: mark the rebuild owed, then rebuild now
        (fetch the baseline, apply, sweep, record the sequence, clear the
        publisher's diffs up to it). The marker is cleared only by a rebuild
        that succeeded; a failed fetch leaves it queued and the rebuild owed,
        so the next poll tries again (3.16, specification 1.5)."""
        from ..callback_processor import CallbackProcessor
        from .actor_interface import ActorInterface

        CallbackProcessor(ActorInterface(self._core_actor)).settle_rebuild(
            peer_id, subscription_id, rebuilt=False, restart_interval=False
        )
        return self.rebuild_subscription(
            peer_id, subscription_id, config=config, force=True
        )

    def rebuild_subscription(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
        *,
        force: bool = False,
    ) -> SubscriptionSyncResult:
        """Rebuild this subscription's replica from a baseline, for a replica
        that could not apply a list diff (it no longer holds what the
        publisher's list held).

        Not ``sync_subscription()``: that applies the publisher's retained
        diffs first, which the replica may already hold. This method tells no
        hook: its caller tells the result's ``baseline`` (when
        ``baseline_skipped`` is not set), as the callback and poll paths do. In this order:
        reserve the attempt (``CallbackProcessor.begin_rebuild``: at most one
        attempt a minute per subscription, successful or not, and never two
        at once; ``force`` skips the interval, not the race); read the
        subscription's sequence from the publisher; fetch the baseline; read
        the sequence again, and fetch again (up to three times) when it moved,
        so the baseline matches the sequence recorded; apply it; delete what
        the baseline no longer carries (at target level every replica name
        it does not carry, at subtarget level the subtarget, and each list
        recorded as out of step); record the sequence (never moving it
        backwards), prune the pending queue through it and clear the
        publisher's diffs up to it; settle the owed rebuild. A sequence that
        kept moving, or an entry that could not be stored, leaves the rebuild
        owed after the rest is applied. A failure leaves it owed (the next
        callback or sync after the interval runs it again).
        """
        from ..callback_processor import CallbackProcessor
        from ..remote_storage import RemotePeerStore
        from ..subscription import Subscription
        from .actor_interface import ActorInterface

        config = self._processing_config(config)
        actor_interface = ActorInterface(self._core_actor)
        processor = CallbackProcessor(
            actor=actor_interface,
            gap_timeout_seconds=config.gap_timeout_seconds,
            max_pending=config.max_pending,
        )

        def result(
            success: bool, error: str | None = None, code: int | None = None
        ) -> SubscriptionSyncResult:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=success,
                diffs_fetched=0,
                diffs_processed=1 if success else 0,
                final_sequence=0,
                error=error,
                error_code=code,
            )

        def failed(error: str, code: int = 502) -> SubscriptionSyncResult:
            logger.warning(
                f"Rebuild of {peer_id}:{subscription_id} failed ({error}); the "
                "rebuild stays owed"
            )
            processor.settle_rebuild(peer_id, subscription_id, rebuilt=False)
            return result(False, error, code)

        if not processor.begin_rebuild(peer_id, subscription_id, force=force):
            logger.info(
                f"Rebuild of {peer_id}:{subscription_id} not started: another "
                "attempt started inside the rebuild interval"
            )
            return result(False, "A rebuild was attempted inside the interval", 429)

        sub = self.get_callback_subscription(peer_id, subscription_id)
        if not sub:
            return failed("Subscription not found", 404)
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            return failed("No trust relationship with peer", 404)
        path = f"subscriptions/{self._core_actor.id}/{subscription_id}"

        def read_sequence() -> int | None:
            response = proxy.get_resource(path=path)
            if response is None or "error" in response:
                return None
            sequence = response.get("sequence", 0)
            if not isinstance(sequence, int) or isinstance(sequence, bool):
                return None
            return sequence

        # The lists owed and the recorded sequence before the baseline is
        # read: a list marked, or any callback recorded, while it is read and
        # applied leaves the rebuild owed (that callback's change may be in
        # the baseline and applied again, or overwritten by it).
        owed = processor.rebuild_state(peer_id, subscription_id)["lists"]
        sub_obj = Subscription(
            actor_id=self._core_actor.id,
            peerid=peer_id,
            subid=subscription_id,
            callback=True,
            config=self._core_actor.config,
        )
        recorded_before = (
            (sub_obj.get() or {}).get("sequence", 0) if sub_obj.handle else 0
        )
        settled = True
        baseline: Any = None
        sequence: int | None = None
        fetched: Any
        for _ in range(3):
            sequence = read_sequence()
            if sequence is None:
                return failed("Failed to read the subscription's sequence")
            fetched = self._fetch_and_transform_baseline(
                peer_id=peer_id,
                target=sub.target,
                subtarget=sub.subtarget or None,
                resource=sub.resource or None,
            )
            if fetched is None:
                return failed("Failed to fetch the baseline")
            baseline = fetched
            after = read_sequence()
            if after is None:
                return failed("Failed to read the subscription's sequence")
            if after == sequence:
                break
        else:
            # Still moving: apply the latest baseline at the sequence read
            # before it (a diff after it may apply twice) and stay owed.
            logger.warning(
                f"Rebuild of {peer_id}:{subscription_id}: the publisher's "
                "sequence kept moving; the rebuild stays owed"
            )
            settled = False
        assert sequence is not None
        # A resource-level baseline may be any value (merged at its path).
        baseline_data: dict[str, Any] = cast(dict[str, Any], baseline)

        # A baseline another subscription's replica covers is not stored
        # here: the result says so, and a poll does not tell it.
        skipped = False
        if config.auto_storage:
            store = RemotePeerStore(
                actor=actor_interface, peer_id=peer_id, validate_peer_id=False
            )
            applied = store.apply_resync_data(
                baseline_data,
                subtarget=sub.subtarget or None,
                target=sub.target,
                resource=sub.resource or None,
            )
            skipped = bool(applied.skipped)
            if applied.failed:
                logger.warning(
                    f"Rebuild of {peer_id}:{subscription_id}: {applied.failed!r} "
                    "could not be stored; the rebuild stays owed"
                )
                settled = False
            sweep_after_baseline(
                self._core_actor,
                store,
                peer_id=peer_id,
                target=sub.target,
                subtarget=sub.subtarget or None,
                resource=sub.resource or None,
                baseline=baseline,
                applied=applied,
                owed=owed,
            )
        # Read afresh: a Subscription serves its first read from a cache, and
        # the check below must see what a callback recorded meanwhile.
        sub_obj = Subscription(
            actor_id=self._core_actor.id,
            peerid=peer_id,
            subid=subscription_id,
            callback=True,
            config=self._core_actor.config,
        )
        if sub_obj.handle:
            current = sub_obj.get() or {}
            recorded = current.get("sequence", 0)
            if not isinstance(recorded, int) or recorded < sequence:
                # Never backwards: a callback processed while this ran may
                # have recorded a later sequence.
                sub_obj.handle.modify(seqnr=sequence)
            if recorded != recorded_before:
                logger.warning(
                    f"Rebuild of {peer_id}:{subscription_id}: a callback "
                    f"(sequence {recorded}) was processed during it; the "
                    "rebuild stays owed"
                )
                settled = False
        processor._prune_pending(peer_id, subscription_id, sequence)  # noqa: SLF001
        if sequence > 0:
            proxy.change_resource(path=path, params={"sequence": sequence})
        if settled and set(
            processor.rebuild_state(peer_id, subscription_id)["lists"]
        ) - set(owed):
            # A list was marked out of step after the baseline was read.
            settled = False
        if not processor.settle_rebuild(peer_id, subscription_id, rebuilt=settled):
            logger.error(
                f"Rebuild of {peer_id}:{subscription_id}: settling its state lost "
                "every compare-and-swap; it may run again after the interval"
            )
        logger.info(
            f"Rebuilt the replica of {peer_id}:{subscription_id} from a baseline "
            f"at sequence {sequence}"
        )
        return SubscriptionSyncResult(
            subscription_id=subscription_id,
            success=settled,
            diffs_fetched=0,
            diffs_processed=1,
            final_sequence=sequence,
            error=None if settled else "The rebuild stays owed",
            baseline=baseline if settled else None,
            target=sub.target,
            subtarget=sub.subtarget or None,
            baseline_skipped=skipped,
        )

    def _rebuild_owed_and_due(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig",
        target: str | None = None,
        *,
        told_elsewhere: bool = False,
    ) -> bool:
        """Whether this subscription owes a rebuild whose interval has
        passed, when a rebuild has anything to do (``rebuilds_for``: a
        replica, or a data hook for ``target``, read from the subscription
        when not given; ``told_elsewhere``: the caller has another hook that
        hears it, the legacy ``subscription`` callback hook). A read fault
        answers False and the sync runs as before."""
        if (
            not told_elsewhere
            and not config.auto_storage
            and not config.subscription_data_hooks
        ):
            return False
        from ..callback_processor import CallbackProcessor
        from .actor_interface import ActorInterface

        try:
            if not config.auto_storage and not told_elsewhere:
                if target is None:
                    sub = self.get_callback_subscription(peer_id, subscription_id)
                    target = sub.target if sub else None
                if not rebuilds_for(config, target):
                    return False
            processor = CallbackProcessor(actor=ActorInterface(self._core_actor))
            state = processor.rebuild_state(peer_id, subscription_id)
        except Exception as e:  # folds DbError: the sync below still runs
            logger.warning(f"Reading the rebuild state of {peer_id} faulted: {e}")
            return False
        if not state["owed"]:
            return False
        return processor._rebuild_due(  # noqa: SLF001
            {"rebuild_owed": True, "rebuilt_at": state["rebuilt_at"]}
        )

    async def rebuild_subscription_async(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
        *,
        force: bool = False,
    ) -> SubscriptionSyncResult:
        """``rebuild_subscription()`` for async callers (run in a worker
        thread)."""
        import asyncio

        return await asyncio.to_thread(
            functools.partial(
                self.rebuild_subscription,
                peer_id,
                subscription_id,
                config,
                force=force,
            )
        )

    def _fetch_and_transform_baseline(
        self,
        peer_id: str,
        target: str,
        subtarget: str | None = None,
        resource: str | None = None,
        known_list: bool = False,
    ) -> Any:
        """
        Fetch and transform baseline data from peer (synchronous).

        This is a helper method that fetches baseline data from the target endpoint
        and transforms it appropriately (e.g., property list metadata expansion).
        It does NOT store the data - that's the caller's responsibility.

        Args:
            peer_id: ID of the peer to fetch baseline from
            target: The target endpoint (e.g., "properties")
            subtarget: Optional subtarget
            resource: Optional resource

        Returns:
            Transformed baseline data dict, or None if fetch failed
        """
        # Construct full target path
        target_path = target
        if subtarget:
            target_path = f"{target_path}/{subtarget}"
        if resource:
            target_path = f"{target_path}/{resource}"

        # Get proxy for peer communication
        proxy = self._get_peer_proxy(peer_id)
        if not proxy:
            logger.warning(f"Cannot fetch baseline for {peer_id}: no proxy available")
            return None

        # Fetch baseline data from target resource
        try:
            baseline_response = proxy.get_resource(path=target_path)
        except Exception as e:  # folds DbError: peer HTTP only
            logger.warning(f"Failed to fetch baseline for {peer_id} from {target}: {e}")
            return None

        if target == "properties" and subtarget and not resource:
            # A single property's baseline, told apart by facts on the wire
            # (3.16): 404 is gone; any other non-2xx, or no answer, a failed
            # fetch; a 2xx body is the value (the spec's properties are
            # untyped: an empty body or ``{}`` is empty, text is text), and
            # an array is a list's items only when the spec's metadata route
            # answers for it (404 there: a value that is an array).
            code = int(proxy.last_response_code or 0)
            if (
                baseline_response is not None
                and code == 404
                and not getattr(proxy, "last_response_redirected", False)
            ):
                return {subtarget: ""}
            if (
                baseline_response is None
                or not 200 <= code <= 299
                or getattr(proxy, "last_response_redirected", False) is True
            ):
                logger.warning(
                    f"Baseline of {subtarget!r} from {peer_id} failed ({code})"
                )
                return None
            value = _subtarget_value(baseline_response, proxy, subtarget)
            if value is None:
                logger.warning(
                    f"Baseline of {subtarget!r} from {peer_id}: a body that is "
                    "not JSON and not the publisher's own answer"
                )
                return None
            if not isinstance(value, list):
                return value
            if known_list:
                return {subtarget: {"_list": True, "items": value}}
            meta = proxy.get_resource(path=f"properties/{subtarget}/metadata")
            if _confirms_list(meta, proxy):
                return {subtarget: {"_list": True, "items": value}}
            if proxy.last_response_code == 404 and not getattr(
                proxy, "last_response_redirected", False
            ):
                return value
            logger.warning(
                f"Baseline of {subtarget!r} from {peer_id}: could not tell a "
                f"list from a value ({proxy.last_response_code})"
            )
            return None
        if (
            resource
            and getattr(proxy, "last_response_code", None) == 404
            and getattr(proxy, "last_response_redirected", False) is not True
        ):
            # A resource that is gone is an empty value, not a failed fetch
            # (3.16): the replica deletes that path.
            return ""
        if _baseline_failed(baseline_response, proxy):
            logger.warning(
                f"No baseline available for {peer_id} from {target} "
                f"({getattr(proxy, 'last_response_code', None)})"
            )
            return None
        if not baseline_response:
            # An empty baseline is empty, not a failed fetch (3.16: both were
            # None, so a publisher with nothing left could never be rebuilt).
            baseline_response = {}

        # For properties subscriptions, transform list metadata into actual items
        if target == "properties" and not subtarget and not resource:
            return self._transform_baseline_list_properties(
                baseline_data=baseline_response,
                peer_id=peer_id,
                target=target,
            )
        return baseline_response

    async def _fetch_and_transform_baseline_async(
        self,
        peer_id: str,
        target: str,
        subtarget: str | None = None,
        resource: str | None = None,
        known_list: bool = False,
    ) -> Any:
        """
        Fetch and transform baseline data from peer (asynchronous).

        This is a helper method that fetches baseline data from the target endpoint
        and transforms it appropriately (e.g., property list metadata expansion).
        It does NOT store the data - that's the caller's responsibility.

        Args:
            peer_id: ID of the peer to fetch baseline from
            target: The target endpoint (e.g., "properties")
            subtarget: Optional subtarget
            resource: Optional resource

        Returns:
            Transformed baseline data dict, or None if fetch failed
        """
        # Construct full target path
        target_path = target
        if subtarget:
            target_path = f"{target_path}/{subtarget}"
        if resource:
            target_path = f"{target_path}/{resource}"

        # Get proxy for peer communication
        proxy = self._get_peer_proxy(peer_id)
        if not proxy:
            logger.warning(f"Cannot fetch baseline for {peer_id}: no proxy available")
            return None

        # Fetch baseline data from target resource
        try:
            baseline_response = await proxy.get_resource_async(path=target_path)
        except Exception as e:  # folds DbError: peer HTTP only
            logger.warning(f"Failed to fetch baseline for {peer_id} from {target}: {e}")
            return None

        if target == "properties" and subtarget and not resource:
            # A single property's baseline, told apart by facts on the wire
            # (3.16): 404 is gone; any other non-2xx, or no answer, a failed
            # fetch; a 2xx body is the value (the spec's properties are
            # untyped: an empty body or ``{}`` is empty, text is text), and
            # an array is a list's items only when the spec's metadata route
            # answers for it (404 there: a value that is an array).
            code = int(proxy.last_response_code or 0)
            if (
                baseline_response is not None
                and code == 404
                and not getattr(proxy, "last_response_redirected", False)
            ):
                return {subtarget: ""}
            if (
                baseline_response is None
                or not 200 <= code <= 299
                or getattr(proxy, "last_response_redirected", False) is True
            ):
                logger.warning(
                    f"Baseline of {subtarget!r} from {peer_id} failed ({code})"
                )
                return None
            value = _subtarget_value(baseline_response, proxy, subtarget)
            if value is None:
                logger.warning(
                    f"Baseline of {subtarget!r} from {peer_id}: a body that is "
                    "not JSON and not the publisher's own answer"
                )
                return None
            if not isinstance(value, list):
                return value
            if known_list:
                return {subtarget: {"_list": True, "items": value}}
            meta = await proxy.get_resource_async(
                path=f"properties/{subtarget}/metadata"
            )
            if _confirms_list(meta, proxy):
                return {subtarget: {"_list": True, "items": value}}
            if proxy.last_response_code == 404 and not getattr(
                proxy, "last_response_redirected", False
            ):
                return value
            logger.warning(
                f"Baseline of {subtarget!r} from {peer_id}: could not tell a "
                f"list from a value ({proxy.last_response_code})"
            )
            return None
        if (
            resource
            and getattr(proxy, "last_response_code", None) == 404
            and getattr(proxy, "last_response_redirected", False) is not True
        ):
            # A resource that is gone is an empty value, not a failed fetch
            # (3.16): the replica deletes that path.
            return ""
        if _baseline_failed(baseline_response, proxy):
            logger.warning(
                f"No baseline available for {peer_id} from {target} "
                f"({getattr(proxy, 'last_response_code', None)})"
            )
            return None
        if not baseline_response:
            # An empty baseline is empty, not a failed fetch (3.16: both were
            # None, so a publisher with nothing left could never be rebuilt).
            baseline_response = {}

        # For properties subscriptions, transform list metadata into actual items
        if target == "properties" and not subtarget and not resource:
            return await self._transform_baseline_list_properties_async(
                baseline_data=cast(dict[str, Any], baseline_response),
                peer_id=peer_id,
                target=target,
            )
        else:
            return baseline_response

    def _is_capability_cache_stale(
        self,
        store: Any,
        actor_id: str,
        peer_id: str,
        actor_config: Any,
    ) -> bool:
        """Check if cached peer capabilities are stale and need refetching.

        Args:
            store: The CachedCapabilitiesStore instance
            actor_id: The actor ID
            peer_id: The peer ID
            actor_config: Config object with peer_capabilities_max_age_seconds

        Returns:
            True if cache is stale or missing (should fetch), False if fresh (skip fetch)
        """
        from datetime import UTC, datetime

        try:
            cached = store.get_capabilities(actor_id, peer_id)
            if not cached or not cached.fetched_at:
                return True  # No cache - need to fetch

            max_age = getattr(actor_config, "peer_capabilities_max_age_seconds", 3600)
            if max_age <= 0:
                return True  # Staleness check disabled - always fetch

            fetched_time = datetime.fromisoformat(cached.fetched_at)
            age_seconds = (datetime.now(UTC) - fetched_time).total_seconds()

            if age_seconds < max_age:
                logger.debug(
                    f"Capability cache for {peer_id} is fresh "
                    f"(age: {age_seconds:.0f}s, max: {max_age}s)"
                )
                return False  # Cache is fresh

            logger.debug(
                f"Capability cache for {peer_id} is stale "
                f"(age: {age_seconds:.0f}s, max: {max_age}s)"
            )
            return True  # Cache is stale

        except Exception as e:  # folds DbError: staleness probe, refetches
            logger.debug(
                f"Error checking capability cache staleness for {peer_id}: {e}"
            )
            return True  # On error, fetch to be safe

    def _extract_profile_from_remote_store(
        self,
        peer_id: str,
        actor_id: str,
        actor_config: Any,
    ) -> tuple[Any, bool]:
        """
        Extract peer profile from already-synced properties in RemotePeerStore.

        This avoids redundant network fetches by using data already synced during
        subscription baseline sync.

        Args:
            peer_id: ID of the peer to extract profile for
            actor_id: ID of the local actor
            actor_config: Actor configuration with peer_profile_attributes

        Returns:
            Tuple of (PeerProfile, success_flag) where success_flag indicates
            if extraction succeeded
        """
        from datetime import UTC, datetime

        from ..peer_profile import PeerProfile
        from ..remote_storage import RemotePeerStore
        from .actor_interface import ActorInterface

        # Check if we have recently synced properties data
        actor_interface = ActorInterface(self._core_actor)
        remote_store = RemotePeerStore(
            actor=actor_interface,
            peer_id=peer_id,
            validate_peer_id=False,
        )

        # Initialize profile object
        profile = PeerProfile(
            actor_id=actor_id,
            peer_id=peer_id,
            fetched_at=datetime.now(UTC).isoformat(),
        )

        try:
            # Track if we successfully extracted any attributes
            profile_extracted = False

            # Get properties from remote store (properties are stored as values)
            for attr in actor_config.peer_profile_attributes:
                value_data = remote_store.get_value(attr)

                if value_data is not None:
                    # Extract actual value (properties are wrapped in {"value": ...})
                    if isinstance(value_data, dict) and "value" in value_data:
                        actual_value = value_data["value"]
                    else:
                        actual_value = value_data

                    # Convert to string for standard profile attributes
                    if attr == "displayname":
                        profile.displayname = (
                            str(actual_value) if actual_value is not None else None
                        )
                        profile_extracted = True
                    elif attr == "email":
                        profile.email = (
                            str(actual_value) if actual_value is not None else None
                        )
                        profile_extracted = True
                    elif attr == "description":
                        profile.description = (
                            str(actual_value) if actual_value is not None else None
                        )
                        profile_extracted = True
                    else:
                        # Store in extra_attributes (keep original type)
                        profile.extra_attributes[attr] = actual_value
                        profile_extracted = True

            return profile, profile_extracted

        except Exception as e:  # folds DbError: cache read, a fault falls back to fetching the profile from the peer
            # If reading from store fails, return failure
            logger.warning(
                f"Profile extraction failed for {peer_id}: {e}",
            )
            return profile, False

    def _refresh_peer_metadata(self, peer_id: str) -> None:
        """
        Refresh cached peer metadata (profile, capabilities, permissions).

        This is called during initial subscription creation to cache peer information.

        Args:
            peer_id: ID of the peer to refresh metadata for
        """
        actor_id = self._core_actor.id
        actor_config = self._core_actor.config

        # Refresh peer profile if configured
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_profile_attributes", None)
        ):
            try:
                from ..peer_profile import fetch_peer_profile, get_peer_profile_store

                profile = fetch_peer_profile(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                    attributes=actor_config.peer_profile_attributes,
                )
                store = get_peer_profile_store(actor_config)
                store.store_profile(profile)
                logger.debug(f"Refreshed peer profile for {peer_id}")
            except Exception as e:  # folds DbError: cache warm after the subscription and baseline committed
                logger.warning(f"Failed to refresh peer profile: {e}")

        # Refresh peer capabilities if configured
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_capabilities_caching", False)
        ):
            try:
                from ..peer_capabilities import (
                    fetch_peer_methods_and_actions,
                    get_cached_capabilities_store,
                )

                capabilities = fetch_peer_methods_and_actions(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                )
                store = get_cached_capabilities_store(actor_config)
                store.store_capabilities(capabilities)
                logger.debug(f"Refreshed peer capabilities for {peer_id}")
            except Exception as e:  # folds DbError: cache warm after the subscription and baseline committed
                logger.warning(f"Failed to refresh peer capabilities: {e}")

        # Refresh peer permissions if configured
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_permissions_caching", False)
        ):
            try:
                from ..peer_permissions import (
                    fetch_peer_permissions,
                    get_peer_permission_store,
                )

                permissions = fetch_peer_permissions(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                )
                # A failed fetch carries no permissions: it never replaces
                # the stored copy (as in sync_peer).
                if not permissions.fetch_error:
                    from ..replica_revocation import cleanup_after_store

                    store = get_peer_permission_store(actor_config)
                    old_grant = (
                        store.read_stored_permissions(actor_id, peer_id)[1]
                        if getattr(actor_config, "auto_delete_on_revocation", False)
                        else None
                    )
                    if store.store_permissions(permissions):
                        cleanup_after_store(
                            actor_config,
                            self._core_actor,
                            peer_id,
                            old_grant,
                            permissions,
                        )
                    logger.debug(f"Refreshed peer permissions for {peer_id}")
            except Exception as e:  # folds DbError: cache warm after the subscription and baseline committed
                logger.warning(f"Failed to refresh peer permissions: {e}")

    async def _refresh_peer_metadata_async(self, peer_id: str) -> None:
        """
        Refresh cached peer metadata (profile, capabilities, permissions) asynchronously.

        This is called during initial subscription creation to cache peer information.

        Args:
            peer_id: ID of the peer to refresh metadata for
        """
        actor_id = self._core_actor.id
        actor_config = self._core_actor.config

        # Refresh peer profile if configured
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_profile_attributes", None)
        ):
            try:
                from ..peer_profile import (
                    fetch_peer_profile_async,
                    get_peer_profile_store,
                )

                profile = await fetch_peer_profile_async(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                    attributes=actor_config.peer_profile_attributes,
                )
                store = get_peer_profile_store(actor_config)
                store.store_profile(profile)
                logger.debug(f"Refreshed peer profile for {peer_id}")
            except Exception as e:  # folds DbError: cache warm after the subscription and baseline committed
                logger.warning(f"Failed to refresh peer profile: {e}")

        # Refresh peer capabilities if configured
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_capabilities_caching", False)
        ):
            try:
                from ..peer_capabilities import (
                    fetch_peer_methods_and_actions_async,
                    get_cached_capabilities_store,
                )

                capabilities = await fetch_peer_methods_and_actions_async(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                )
                store = get_cached_capabilities_store(actor_config)
                store.store_capabilities(capabilities)
                logger.debug(f"Refreshed peer capabilities for {peer_id}")
            except Exception as e:  # folds DbError: cache warm after the subscription and baseline committed
                logger.warning(f"Failed to refresh peer capabilities: {e}")

        # Refresh peer permissions if configured
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_permissions_caching", False)
        ):
            try:
                from ..peer_permissions import (
                    fetch_peer_permissions_async,
                    get_peer_permission_store,
                )

                permissions = await fetch_peer_permissions_async(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                )
                # A failed fetch carries no permissions: it never replaces
                # the stored copy (as in sync_peer).
                if not permissions.fetch_error:
                    from ..replica_revocation import cleanup_after_store

                    store = get_peer_permission_store(actor_config)
                    old_grant = (
                        store.read_stored_permissions(actor_id, peer_id)[1]
                        if getattr(actor_config, "auto_delete_on_revocation", False)
                        else None
                    )
                    if store.store_permissions(permissions):
                        cleanup_after_store(
                            actor_config,
                            self._core_actor,
                            peer_id,
                            old_grant,
                            permissions,
                        )
                    logger.debug(f"Refreshed peer permissions for {peer_id}")
            except Exception as e:  # folds DbError: cache warm after the subscription and baseline committed
                logger.warning(f"Failed to refresh peer permissions: {e}")

    async def sync_peer_async(
        self,
        peer_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
        _skip_revocation_detection: bool = False,
        force_refresh: bool = False,
    ) -> PeerSyncResult:
        """
        Async version of sync_peer.

        Sync all outbound subscriptions to a peer.

        Args:
            peer_id: ID of the peer actor
            config: Optional processing configuration
            _skip_revocation_detection: Internal parameter to skip trust revocation
                detection during initial subscription sync (to avoid false positives
                from timing/eventual consistency issues)
            force_refresh: If True, bypass capability cache staleness checks
                and always refetch. Use for manual/developer-triggered syncs.

        Returns:
            PeerSyncResult with aggregate sync outcome

        Example:
            result = await actor.subscriptions.sync_peer_async("peer123")
        """
        import asyncio

        # Get all outbound subscriptions to this peer
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        outbound_subs = [s for s in subscriptions if s.is_outbound]

        if not outbound_subs:
            return PeerSyncResult(
                peer_id=peer_id,
                success=True,
                subscriptions_synced=0,
                total_diffs_processed=0,
                subscription_results=[],
            )

        # Sync each subscription concurrently
        tasks = [
            self.sync_subscription_async(
                peer_id=peer_id,
                subscription_id=sub.subscription_id,
                config=config,
            )
            for sub in outbound_subs
        ]

        results = await asyncio.gather(*tasks)

        total_diffs = sum(r.diffs_processed for r in results)
        all_success = all(r.success for r in results)

        # Detect revoked trust: if ALL subscription syncs failed with 404, the peer may have
        # revoked the trust relationship. Verify by checking if peer actor still exists.
        # Skip this check during initial sync right after subscription creation to avoid
        # false positives from timing/eventual consistency issues.
        all_subscriptions_404 = (
            results
            and all(not r.success and r.error_code == 404 for r in results)
            and not _skip_revocation_detection
        )
        if all_subscriptions_404:
            logger.warning(
                f"All {len(results)} subscription(s) failed with 404 for peer {peer_id}. "
                f"Verifying if peer actor exists or trust has been revoked."
            )

            # Verify trust relationship still exists from peer's perspective
            proxy = self._get_peer_proxy(peer_id)
            state = "unknown"
            if proxy:
                try:
                    await proxy.get_resource_async(path=self._own_trust_path(proxy))
                except Exception as e:  # folds DbError: peer HTTP only
                    logger.warning(f"Exception verifying trust with {peer_id}: {e}")
                state = self._peer_trust_state(peer_id, proxy)
            trust_exists = state == "exists"

            # Only delete trust if peer's trust record doesn't exist or we can't access it
            if trust_exists:
                logger.info(
                    f"Trust with {peer_id} still exists, but subscriptions are gone. "
                    f"Cleaning up local subscriptions that were deleted by peer."
                )
                # Clean up the dead subscriptions locally
                try:
                    for result in results:
                        if not result.success and result.error_code == 404:
                            sub = self.get_callback_subscription(
                                peer_id, result.subscription_id
                            )
                            if sub:
                                logger.info(
                                    f"Deleting local subscription {result.subscription_id} - "
                                    f"peer deleted it but trust remains valid."
                                )
                                sub_obj = self._core_actor.get_subscription_obj(
                                    peerid=peer_id,
                                    subid=result.subscription_id,
                                    callback=sub.is_callback,
                                )
                                if sub_obj:
                                    await asyncio.to_thread(sub_obj.delete)
                except DbError:
                    raise
                except Exception as e:
                    logger.error(
                        f"Error cleaning up dead subscriptions for {peer_id}: {e}",
                        exc_info=True,
                    )
                finally:
                    # As in the sync clean-up: the memo would keep the
                    # deleted rows (3.16).
                    self._core_actor.subs_list = None
            elif state == "unknown":
                logger.warning(
                    f"Could not tell whether {peer_id} still trusts this actor; "
                    "the trust is kept and the next sync asks again"
                )
            else:
                logger.warning(
                    f"Peer {peer_id} no longer holds this trust. "
                    f"Trust has been revoked. Cleaning up locally."
                )
                try:
                    # trust_deleted fires as in the sync twin: through
                    # TrustManager, with the row the delete read, after the
                    # delete found it and before anything local goes (3.16; a
                    # row already gone fires nothing). The delete runs on a
                    # thread of its own executor, not the default one, which
                    # a coroutine hook awaited on this loop may need (its
                    # *_async calls use it): revocations filling the default
                    # pool would otherwise wait on hooks waiting on it. A
                    # sync hook runs in that thread (off the loop).
                    from .actor_interface import ActorInterface

                    trust = ActorInterface(self._core_actor).trust
                    loop = asyncio.get_running_loop()

                    def before_local_delete(row: dict[str, Any]) -> None:
                        trust.fire_deleted(row, initiated_by_peer=True, loop=loop)

                    # Delete local trust relationship without notifying peer
                    # (already revoked): only the row the probe used.
                    # The request's context (correlation, runtime context)
                    # goes with it, as asyncio.to_thread would carry it.
                    deleted = await loop.run_in_executor(
                        _revocation_executor(),
                        contextvars.copy_context().run,
                        functools.partial(
                            self._core_actor.delete_reciprocal_trust,
                            peerid=peer_id,
                            delete_peer=False,
                            expected_secret=self._probed_secret(proxy),
                            before_local_delete=before_local_delete,
                        ),
                    )
                    if deleted:
                        logger.info(
                            f"Successfully cleaned up revoked trust relationship with {peer_id}"
                        )
                        return PeerSyncResult(
                            peer_id=peer_id,
                            success=False,
                            subscriptions_synced=0,
                            total_diffs_processed=total_diffs,
                            subscription_results=list(results),
                            error="Trust relationship has been revoked by peer",
                        )
                    else:
                        logger.warning(
                            f"Failed to delete trust relationship with {peer_id}"
                        )
                except TrustReplaced:
                    # Either before anything ran, or (the remaining window of
                    # the deletion invariants) after trust_deleted fired and
                    # the local cleanup ran: the new row stands either way.
                    logger.warning(
                        f"Trust with {peer_id} was re-paired during the "
                        "revocation cleanup; the new row is kept (if "
                        "trust_deleted already fired, the local cleanup "
                        "it announced has run)"
                    )
                except DbError:
                    raise
                except Exception as e:
                    logger.error(
                        f"Exception while cleaning up revoked trust with {peer_id}: {e}"
                    )

        # Refresh peer profile if configured (async)
        # Try to use already-synced properties data first to avoid redundant fetch
        actor_config = self._core_actor.config
        actor_id = self._core_actor.id
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_profile_attributes", None)
        ):
            try:
                from ..peer_profile import (
                    fetch_peer_profile_async,
                    get_peer_profile_store,
                )

                # Try to extract profile from synced properties
                profile, profile_extracted = self._extract_profile_from_remote_store(
                    peer_id=peer_id,
                    actor_id=actor_id,
                    actor_config=actor_config,
                )

                # Only fetch if we couldn't extract from synced data
                if not profile_extracted:
                    profile = await fetch_peer_profile_async(
                        actor_id=actor_id,
                        peer_id=peer_id,
                        config=actor_config,
                        attributes=actor_config.peer_profile_attributes,
                    )
                    logger.debug(
                        f"Fetched peer profile for {peer_id} via fallback (extraction failed)"
                    )
                else:
                    logger.debug(
                        f"Extracted peer profile from synced properties for {peer_id}"
                    )

                store = get_peer_profile_store(actor_config)
                store.store_profile(profile)
            except Exception as e:  # folds DbError: best-effort peer profile cache refresh after the sync committed
                logger.warning(
                    f"Failed to refresh peer profile during sync (async): {e}"
                )

        # Refresh peer capabilities if configured (async, with staleness check)
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_capabilities_caching", False)
        ):
            try:
                from ..peer_capabilities import (
                    fetch_peer_methods_and_actions_async,
                    get_cached_capabilities_store,
                )

                store = get_cached_capabilities_store(actor_config)

                # Check cache staleness (skip if force_refresh)
                should_fetch = force_refresh
                if not force_refresh:
                    should_fetch = self._is_capability_cache_stale(
                        store, actor_id, peer_id, actor_config
                    )

                if should_fetch:
                    capabilities = await fetch_peer_methods_and_actions_async(
                        actor_id=actor_id,
                        peer_id=peer_id,
                        config=actor_config,
                    )
                    store.store_capabilities(capabilities)
                    logger.debug(
                        f"Refreshed peer capabilities (async) during sync_peer for {peer_id}"
                    )
                else:
                    logger.debug(
                        f"Using cached capabilities for {peer_id} (cache is fresh, async)"
                    )
            except Exception as e:  # folds DbError: best-effort peer capabilities cache refresh after the sync committed
                logger.warning(
                    f"Failed to refresh peer capabilities during sync (async): {e}"
                )

        # Refresh peer permissions if configured (async)
        # This fetches from the peer's GET /permissions/{actor_id} endpoint
        # to establish initial permission baseline or refresh cached permissions.
        # Complements the reactive callback-based push mechanism.
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_permissions_caching", False)
        ):
            try:
                from ..peer_permissions import (
                    fetch_peer_permissions_async,
                    get_peer_permission_store,
                )

                permissions = await fetch_peer_permissions_async(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                )

                # Only store if fetch was successful (no error)
                # Don't overwrite callback-received permissions with empty data from 404
                if not permissions.fetch_error:
                    from ..replica_revocation import cleanup_after_store

                    store = get_peer_permission_store(actor_config)
                    old_grant = (
                        store.read_stored_permissions(actor_id, peer_id)[1]
                        if getattr(actor_config, "auto_delete_on_revocation", False)
                        else None
                    )
                    if store.store_permissions(permissions):
                        cleanup_after_store(
                            actor_config,
                            self._core_actor,
                            peer_id,
                            old_grant,
                            permissions,
                        )
                    logger.debug(
                        f"Refreshed peer permissions (async) during sync_peer for {peer_id}"
                    )
                else:
                    logger.debug(
                        f"Skipping permission storage during sync - fetch failed: {permissions.fetch_error}"
                    )
            except Exception as e:  # folds DbError: best-effort peer permissions cache refresh after the sync committed
                logger.warning(
                    f"Failed to refresh peer permissions during sync (async): {e}"
                )

        return PeerSyncResult(
            peer_id=peer_id,
            success=all_success,
            subscriptions_synced=len([r for r in results if r.success]),
            total_diffs_processed=total_diffs,
            subscription_results=list(results),
        )
