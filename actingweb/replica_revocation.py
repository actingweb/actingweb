"""What a changed grant takes away from a peer's replica (3.16).

With ``auto_delete_on_revocation`` on, a permission change from a peer whose
whole ``properties`` target this actor subscribes to deletes what the peer
no longer lets it read: every replica name (scalar or list) the new grant's
patterns do not grant ``read`` for, or that an exclusion covers, and inside
a kept object every excluded descendant. The decision is the publisher's own
(``permission_evaluator``'s matcher and path rules), computed from the stored
grant, never from which patterns changed: an exclusion added, ``read``
dropped and a pattern removed all count.

A grant whose shape this cannot evaluate deletes nothing and says why
(``NotEvaluated``). Names are enumerated without their values; an object's
value is read only when the grant excludes something.

A subscription below the whole target (a subtarget or a resource) is not
covered: the replica does not record which subscription stored a key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .permission_evaluator import drop_excluded, glob_match, path_excluded

if TYPE_CHECKING:
    from .peer_permissions import PeerPermissions
    from .remote_storage import RemotePeerStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RevokedNames:
    """What to take out of a replica: names to delete, and objects to
    rewrite without their excluded descendants (name to the kept value)."""

    scalars: list[str] = field(default_factory=list)
    lists: list[str] = field(default_factory=list)
    rewrites: dict[str, Any] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return [*self.scalars, *self.lists, *self.rewrites]


@dataclass(frozen=True)
class NotEvaluated:
    """A grant this cannot evaluate: nothing is deleted."""

    why: str


def _property_rules(grant: PeerPermissions | None) -> dict[str, Any] | NotEvaluated:
    props = grant.properties if grant is not None else None
    if not props:
        return NotEvaluated("the grant has no property rules")
    if not isinstance(props, dict):
        return NotEvaluated("the property rules are not an object")
    if "allowed" in props or "denied" in props:
        return NotEvaluated("the property rules use the allowed/denied shape")
    if "patterns" not in props or "operations" not in props:
        return NotEvaluated(
            "the property rules carry no patterns or no operations (an "
            "override without its base)"
        )
    if not isinstance(props.get("patterns"), list) or not isinstance(
        props.get("operations"), list
    ):
        return NotEvaluated("the property patterns or operations are not lists")
    return props


def readable(rules: dict[str, Any], name: str) -> bool:
    """Whether ``rules`` let the peer's subscriber read the name ``name``."""
    operations = {str(o) for o in rules.get("operations") or []}
    if "read" not in operations and "*" not in operations:
        return False
    if not any(glob_match(name, str(p)) for p in rules.get("patterns") or []):
        return False
    return not path_excluded(rules, name)


def still_readable(grant: PeerPermissions | None, names: list[str]) -> list[str]:
    """The ``names`` ``grant`` (a stored copy, or None) lets the subscriber
    read: what a losing callback's restore fetches again."""
    rules = _property_rules(grant)
    if isinstance(rules, NotEvaluated) or not names:
        return []
    return list(dict.fromkeys(n for n in names if readable(rules, n)))


def revoked_replica_names(
    store: RemotePeerStore, grant: PeerPermissions | None
) -> RevokedNames | NotEvaluated:
    """What ``grant`` no longer lets this replica hold."""
    rules = _property_rules(grant)
    if isinstance(rules, NotEvaluated):
        return rules
    scalars = [n for n in store.list_scalar_names() if not n.startswith("list:")]
    lists = store.list_all_lists(strict=True)
    revoked = RevokedNames(
        scalars=[n for n in scalars if not readable(rules, n)],
        lists=[n for n in lists if not readable(rules, n)],
    )
    if not (rules.get("excluded_patterns") or rules.get("denied")):
        return revoked
    for name in scalars:
        if name in revoked.scalars:
            continue
        value = store.get_value(name)
        if not isinstance(value, dict):
            continue
        if set(value) == {"value"} and not isinstance(value["value"], dict):
            # A value that is not an object, stored wrapped by the receiver:
            # the publisher sends it whole (an exclusion has no part of it to
            # name), so it is kept whole.
            continue
        kept = drop_excluded(rules, name, value)
        if kept != value:
            revoked.rewrites[name] = kept
    return revoked


def apply_revoked(store: RemotePeerStore, revoked: RevokedNames) -> list[str]:
    """Delete (and rewrite) what ``revoked`` names; the names touched."""
    for name in revoked.scalars:
        store.delete_value(name)
    for name in revoked.lists:
        store.delete_list(name)
    for name, kept in revoked.rewrites.items():
        if kept:
            store.set_value(name, kept)
        else:
            store.delete_value(name)
    for name in revoked.names:
        logger.info(
            "Deleted revoked peer data %r from the replica of peer %s",
            name,
            store._peer_id,  # noqa: SLF001
        )
    return revoked.names


def subscribes_to_whole_properties(config: Any, actor_id: str, peer_id: str) -> bool:
    """Whether ``actor_id`` holds a subscription to ``peer_id``'s whole
    ``properties`` target (the only kind the cleanup covers). One read of
    the actor's subscriptions; a fault raises ``DbError``."""
    from .db import get_subscription_list

    subscriptions = get_subscription_list(config).fetch(actor_id, strict=True) or []
    return any(
        s.get("peerid") == peer_id
        and s.get("callback")
        and s.get("target") == "properties"
        and not s.get("subtarget")
        and not s.get("resource")
        for s in subscriptions
        if isinstance(s, dict)
    )


def stores_another_target(config: Any, actor_id: str, peer_id: str) -> bool:
    """Whether ``actor_id`` holds a callback subscription to ``peer_id`` for
    a target other than ``properties``: its data is auto-stored in the same
    replica bucket, so no property grant or baseline decides what that
    bucket may hold. One read; a fault raises ``DbError``."""
    from .db import get_subscription_list

    subscriptions = get_subscription_list(config).fetch(actor_id, strict=True) or []
    return any(
        s.get("peerid") == peer_id
        and s.get("callback")
        and s.get("target") not in (None, "", "properties")
        for s in subscriptions
        if isinstance(s, dict)
    )


def subscribes_to_properties(config: Any, actor_id: str, peer_id: str) -> bool:
    """Whether ``actor_id`` holds a callback subscription to ``peer_id``'s
    ``properties`` target at any level. One read; a fault raises."""
    from .db import get_subscription_list

    subscriptions = get_subscription_list(config).fetch(actor_id, strict=True) or []
    return any(
        s.get("peerid") == peer_id
        and s.get("callback")
        and s.get("target") == "properties"
        for s in subscriptions
        if isinstance(s, dict)
    )


def _patterns(grant: PeerPermissions | None) -> set[str]:
    props = grant.properties if grant is not None else None
    if not isinstance(props, dict):
        return set()
    patterns = props.get("patterns")
    return {str(p) for p in patterns} if isinstance(patterns, list) else set()


def revoked_by_patterns(
    store: RemotePeerStore,
    old_grant: PeerPermissions | None,
    new_grant: PeerPermissions | None,
) -> RevokedNames:
    """For a replica bucket another target also stores into: only the names
    matching a pattern the grant dropped, and that the new grant does not
    let the subscriber read (what pre-3.16 deleted); names nothing of the
    property grant decides are kept."""
    gone = _patterns(old_grant) - _patterns(new_grant)
    if not gone:
        return RevokedNames()
    rules = _property_rules(new_grant)

    def revoked(name: str) -> bool:
        if not any(glob_match(name, p) for p in gone):
            return False
        return isinstance(rules, NotEvaluated) or not readable(rules, name)

    scalars = [n for n in store.list_scalar_names() if not n.startswith("list:")]
    lists = store.list_all_lists(strict=True)
    return RevokedNames(
        scalars=[n for n in scalars if revoked(n)],
        lists=[n for n in lists if revoked(n)],
    )


def plan_cleanup(
    config: Any,
    actor_id: str,
    store: RemotePeerStore,
    old_grant: PeerPermissions | None,
    new_grant: PeerPermissions,
) -> RevokedNames | NotEvaluated | None:
    """What a grant change takes from the replica, or None when there is
    nothing to evaluate. In order, each ending the work: the flag off (no
    read); no subscription to the peer's whole ``properties`` target; the
    grant's property rules unchanged (no replica read). A replica that also
    holds another target's data (``stores_another_target``) loses only the
    names matching a dropped pattern (``revoked_by_patterns``): the property
    grant does not decide the other target's names."""
    if not getattr(config, "auto_delete_on_revocation", False):
        return None
    if not subscribes_to_properties(config, actor_id, store._peer_id):  # noqa: SLF001
        return None
    if old_grant is not None and old_grant.properties == new_grant.properties:
        return None
    if stores_another_target(config, actor_id, store._peer_id):  # noqa: SLF001
        return revoked_by_patterns(store, old_grant, new_grant)
    return revoked_replica_names(store, new_grant)


def cleanup_after_store(
    config: Any,
    actor: Any,
    peer_id: str,
    old_grant: PeerPermissions | None,
    stored_grant: PeerPermissions,
) -> list[str]:
    """For a grant writer outside the permission callback's compare-and-swap
    (a query's refresh, a sync, the operator rebuild): after storing
    ``stored_grant``, read the stored copy back and clean the replica only
    when it is the copy evaluated. A newer copy stored meanwhile (a
    callback) decides instead, so a writer whose fetched grant is older
    deletes nothing. Returns the names touched; a fault raises
    ``DbError``."""
    from .peer_permissions import get_peer_permission_store
    from .remote_storage import RemotePeerStore

    if not getattr(config, "auto_delete_on_revocation", False):
        return []
    actor_id = str(getattr(actor, "id", "") or "")
    _, now = get_peer_permission_store(config).read_stored_permissions(
        actor_id, peer_id
    )
    if now is None or now.properties != stored_grant.properties:
        return []
    store = RemotePeerStore(actor, peer_id, validate_peer_id=False)
    plan = plan_cleanup(config, actor_id, store, old_grant, stored_grant)
    if plan is None:
        return []
    if isinstance(plan, NotEvaluated):
        logger.warning(f"Revoked data of peer {peer_id} not deleted: {plan.why}")
        return []
    return apply_revoked(store, plan)
