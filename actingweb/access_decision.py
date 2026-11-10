"""One access decision for a peer on every route (3.16).

``decide()`` answers whether a peer may perform an operation on a path of a
category at an actor, the same way for every caller: the REST handlers, the
property hooks, the pushed and pulled subscription diffs and the developer
views. The order:

1. the actor's trust row for the peer must exist and be approved;
2. the grant is read once (:class:`GrantSnapshot`); an error denies;
3. when the grant **mentions** the category (the key is present, even
   empty) its rule answers: an excluded path or ancestor, an unmatched or
   empty rule, a wrong operation all deny (properties and resources; methods
   and actions keep the access table for an unmatched rule for now);
4. when it does not mention the category, an OAuth2/MCP client is denied
   and a peer is answered by the access table (``config.access``), the
   application's rule per trust level, which denies by default.

An empty path (a listing, a whole-target subscription) is never decided as a
whole by a rule: it goes to the table for a peer, and the caller decides per
name. A storage fault raises ``DbError``.

Imports the evaluator and the access table only, never the actor (``auth``
imports the actor, and the actor imports this module).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .access_table import access_table_admits
from .db.exceptions import DbError
from .identifiers import has_control_characters
from .permission_evaluator import (
    GrantSnapshot,
    PermissionEvaluator,
    PermissionResult,
    PermissionType,
    get_permission_evaluator,
    path_excluded,
)

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

# The access table's method for an operation, when the caller gives none.
_METHOD_FOR = {"read": "GET", "write": "PUT", "delete": "DELETE"}

# Reasons, for the debug log only: a refusal's body never says which.
NOT_APPROVED = "not_approved"
EXCLUDED = "excluded"
NOT_GRANTED = "not_granted"
NO_TABLE_ROW = "no_table_row"
UNAVAILABLE = "unavailable"
ALLOWED = "allowed"


class _PermissionDenied:
    """The property hooks' answer when the caller may not perform the
    operation (3.16): distinct from ``None``, which a hook returns to hide a
    value (404) or reject a write."""

    _instance: _PermissionDenied | None = None

    def __new__(cls) -> _PermissionDenied:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "PERMISSION_DENIED"

    def __bool__(self) -> bool:
        return False


PERMISSION_DENIED = _PermissionDenied()


@dataclass(frozen=True)
class Decision:
    """The answer, why, and the grant it was read from (for reuse in the
    rest of the request)."""

    allowed: bool
    reason: str
    snapshot: GrantSnapshot | None = None

    def __bool__(self) -> bool:
        return self.allowed


def _category(category: str | PermissionType) -> PermissionType:
    return (
        category if isinstance(category, PermissionType) else PermissionType(category)
    )


def grant_snapshot(
    config: Config,
    actor_id: str,
    peer_id: str,
    *,
    evaluator: PermissionEvaluator | None = None,
) -> GrantSnapshot | None:
    """The peer's grant at the actor, or None when it cannot be read for a
    reason other than storage (the caller denies). ``DbError`` raises."""
    try:
        evaluator = evaluator or get_permission_evaluator(config)
        return evaluator.snapshot(actor_id, peer_id)
    except DbError:
        raise
    except Exception as e:
        logger.error(f"Grant for {actor_id}:{peer_id} could not be read: {e}")
        return None


def decide(
    config: Config,
    actor_id: str,
    peer_id: str,
    category: str | PermissionType,
    path: str,
    operation: str,
    *,
    method: str | None = None,
    evaluator: PermissionEvaluator | None = None,
    snapshot: GrantSnapshot | None = None,
    is_client: bool | None = None,
) -> Decision:
    """Whether ``peer_id`` may perform ``operation`` on ``path`` of
    ``category`` at ``actor_id`` (module docstring for the order).

    ``method``: the request's method for the access table (default: from the
    operation). ``evaluator``: the caller's (a handler resolves its own so a
    test's patch on that module applies). ``snapshot``: a grant the caller
    already read. ``is_client``: the caller knows the peer is an OAuth2/MCP
    client (else the trust row says).
    """
    kind = _category(category)
    try:
        evaluator = evaluator or get_permission_evaluator(config)
        if snapshot is None:
            snapshot = evaluator.snapshot(actor_id, peer_id)
    except DbError:
        raise
    except Exception as e:
        logger.error(f"Access decision for {actor_id}:{peer_id} unavailable: {e}")
        return Decision(False, UNAVAILABLE)
    if not snapshot.approved:
        return Decision(False, NOT_APPROVED, snapshot)
    if has_control_characters(path):
        return Decision(False, EXCLUDED, snapshot)
    client = snapshot.is_client if is_client is None else is_client
    if snapshot.mentions(kind) and path:
        try:
            result = evaluator.evaluate_rules_for(
                kind, snapshot.rules(kind), path, operation, suppress_logging=True
            )
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Access decision for {actor_id}:{peer_id} failed: {e}")
            return Decision(False, UNAVAILABLE, snapshot)
        if result == PermissionResult.ALLOWED:
            return Decision(True, ALLOWED, snapshot)
        if result == PermissionResult.DENIED:
            reason = (
                EXCLUDED if path_excluded(snapshot.rules(kind), path) else NOT_GRANTED
            )
            logger.debug(
                f"Denied: {actor_id}:{peer_id} -> {kind.value}:{path!r}:"
                f"{operation} ({reason})"
            )
            return Decision(False, reason, snapshot)
        # NOT_FOUND from a stated rule: methods and actions (for now) fall
        # through to the table, as before.
    if client:
        return Decision(False, NOT_GRANTED, snapshot)
    admitted = access_table_admits(
        config,
        relationship=snapshot.relationship,
        approved=snapshot.approved,
        path=kind.value,
        subpath=path.split("/")[0] if path else "",
        method=method or _METHOD_FOR.get(operation, "GET"),
    )
    return Decision(admitted, ALLOWED if admitted else NO_TABLE_ROW, snapshot)


def forbidden_body(decision: Decision | None) -> dict[str, Any]:
    """The body of a refusal: ``not_approved`` for an unapproved row, else
    ``forbidden``. It never says that an exclusion caused it."""
    if decision is not None and decision.reason == NOT_APPROVED:
        return {"error": "not_approved"}
    return {"error": "forbidden"}
