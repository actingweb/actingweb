"""One finisher for an actor's deletion wipe, resumable from its tombstone.

Every path that wipes an actor goes through :func:`finish_deletion`: a
``DELETE /<id>`` (first or repeated), the replacement of an actor at adoption
and the factory-sibling sweep, a sign-in that meets a stalled wipe, and the
``actingweb-deletions`` operator command. A programmatic ``Actor.delete()``
stays a plain wipe with no hooks; calling it again is its resume.

The wipe has many writes and no transaction, so it can stop part-way. What
makes it resumable:

- **The tombstone says why.** The first write records the ``reason``,
  whether peers are notified, the ``actor_deleted`` kwargs, the actor's OAuth2
  client ids (their bucket goes with the wipe) and whether ``actor_deleted``
  has run. A resume uses what was recorded, so a replacement victim's peers,
  whose URLs a squatter chose, are never sent a DELETE, and ``actor_deleted``
  runs at least once per registered hook, again only after a ``DbError``.
- **One finisher at a time.** A finisher takes the tombstone's lease
  (:data:`~actingweb.constants.DELETION_LEASE`); another one that meets a
  live lease raises :class:`~actingweb.db.exceptions.DeletionInProgress`
  (503 with ``Retry-After``). A lease that lapsed is taken over.
- **Every step is idempotent, the row goes last**, and the tombstone gets its
  retention TTL only once the row delete is confirmed, so a stalled wipe stays
  visible to ``actingweb-deletions report``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from . import deletion
from .constants import DELETION_LEASE
from .db.exceptions import DbError, DeletionInProgress

if TYPE_CHECKING:
    from .actor import Actor
    from .config import Config
    from .interface.hooks import HookRegistry

logger = logging.getLogger(__name__)

__all__ = ["finish_deletion", "REASON_DELETED", "REASON_REPLACED"]

REASON_DELETED = "deleted"
REASON_REPLACED = "replaced_at_adoption"


def finish_deletion(
    actor: Actor,
    *,
    config: Config,
    hooks: HookRegistry | None,
    origin: str,
    reason: str = REASON_DELETED,
    notify_peers: bool = True,
    hook_kwargs: dict[str, Any] | None = None,
    spa_revoked: bool = False,
    fire_complete: bool = True,
    pre_reads: tuple[Any, Any] | None = None,
    client_ids: list[str] | None = None,
) -> int | None:
    """Start or resume the wipe of ``actor``; the tokens revoked when its row is gone.

    Args:
        actor: The actor to wipe (loaded; its row may already be gone on a
            resume).
        config: ActingWeb configuration.
        hooks: Lifecycle hooks; ``None`` fires none (the operator command).
        origin: Who finishes it (``delete``, ``sign_in``, ``replacement``,
            ``sweep``, ``operator``), for the logs.
        reason: Recorded on a first write; a resume keeps the recorded one.
        notify_peers: Recorded on a first write; a resume uses
            ``notify_peers and`` the recorded value.
        hook_kwargs: The ``actor_deleted`` kwargs, recorded on a first write.
        spa_revoked: The caller already revoked the actor's SPA tokens (a
            replacement revokes them for the victim and its siblings in one
            pass).
        fire_complete: Fire ``actor_deleted_complete`` when the row is gone.
        pre_reads: The ``(Trusts, Subscriptions)`` wrappers the caller already
            fetched strictly; read here otherwise.
        client_ids: Client ids the caller already read (merged with the
            ones read here and the ones a tombstone recorded).

    Returns:
        The number of tokens revoked when the actor row is gone (0 is a
        success); None when the backend did not confirm the row removal
        (the tombstone stays; the next finisher resumes).

    Raises:
        DeletionInProgress: another finisher holds the tombstone's lease.
        DbError: on a fault, before anything is removed when it is a read,
            or part-way, in which case the tombstone records what a resume
            needs.
    """
    actor_id = actor.id or ""
    if not actor_id:
        raise DbError("actor deletion without an id")
    _, data = deletion.read_tombstone(actor_id, config)
    if data is not None:
        data = deletion.claim_lease(actor_id, config, data)
        resumed = True
    else:
        resumed = False
    try:
        if pre_reads is None:
            pre_reads = _pre_read(actor_id, config)
        client_ids_all = set(client_ids or [])
        client_ids_all.update(
            _client_ids_if_readable(config, actor_id, strict=not resumed)
        )
        if data is None:
            data = deletion.create_leased_tombstone(
                actor_id,
                config,
                reason=reason,
                notify_peers=notify_peers,
                hook_kwargs=hook_kwargs or {},
                client_ids=sorted(client_ids_all),
            )
        else:
            recorded = data.get("client_ids")
            if isinstance(recorded, list):
                client_ids_all.update(str(c) for c in recorded)
        effective_peers = notify_peers and data.get("notify_peers") is not False
        if not deletion.is_resumable(data):
            # A tombstone from before resumable deletion: whether
            # actor_deleted ran then is not knowable. A DELETE /<id> of the
            # live actor is the user asking now, so it fires (at least once
            # per hook, as documented: handlers are idempotent) and the
            # tombstone records this deletion. Elsewhere (the operator
            # command) the common case is that it ran right after the
            # tombstone, and it is not fired again.
            if origin == "delete":
                data = _update(
                    actor_id,
                    config,
                    data,
                    {
                        "reason": reason,
                        "notify_peers": bool(notify_peers),
                        "hook_kwargs": dict(hook_kwargs or {}),
                        "client_ids": sorted(client_ids_all),
                        "hook_fired": False,
                    },
                )
            else:
                data = _update(actor_id, config, data, {"hook_fired": True})
        if hooks is not None and not data.get("hook_fired"):
            kwargs = data.get("hook_kwargs")
            _fire(
                hooks,
                "actor_deleted",
                actor,
                config,
                **(kwargs if isinstance(kwargs, dict) else {}),
            )
            data = _update(actor_id, config, data, {"hook_fired": True})
        # Renew the lease after the hook (which can be slow) and check it is
        # still ours: a finisher whose lease lapsed and was taken over stops
        # here (DeletionInProgress) instead of wiping beside the new one.
        data = _update(actor_id, config, data, deletion.lease_fields())
        from .oauth2 import _delete_actor_clients, _revoke_all_actor_tokens

        revoked = _revoke_all_actor_tokens(config, actor_id, spa=not spa_revoked)
        _delete_actor_clients(
            config, actor_id, sorted(client_ids_all), actor_deleted=True
        )
        gone = bool(
            actor.delete(
                notify_peers=effective_peers,
                _pre_reads=pre_reads,
                _between_steps=_lease_keeper(actor_id, config, data),
            )
        )
    except BaseException:
        if data is not None:
            deletion.release_lease(actor_id, config, data)
        raise
    if not gone:
        logger.error(
            f"Deletion of actor {actor_id} ({origin}): the backend did not "
            "confirm the row removed; the next finisher resumes it"
        )
        deletion.release_lease(actor_id, config, data)
        return None
    announce = deletion.mark_finished(actor_id, config, data)
    if fire_complete and hooks is not None and announce:
        kwargs = data.get("hook_kwargs")
        _fire(
            hooks,
            "actor_deleted_complete",
            None,
            config,
            actor_id=actor_id,
            **(kwargs if isinstance(kwargs, dict) else {}),
        )
    logger.info(
        f"Deletion of actor {actor_id} finished ({origin}"
        f"{', resumed' if resumed else ''})"
    )
    return revoked


def _pre_read(actor_id: str, config: Config) -> tuple[Any, Any]:
    """Strict trust and subscription reads, before anything is written."""
    from . import subscription as subscription_module
    from . import trust as trust_module

    trusts = trust_module.Trusts(actor_id=actor_id, config=config)
    trusts.fetch()  # strict: raises DbError
    subs = subscription_module.Subscriptions(actor_id=actor_id, config=config)
    subs.fetch()  # strict: raises DbError
    return trusts, subs


def _client_ids_if_readable(
    config: Config, actor_id: str, *, strict: bool
) -> list[str]:
    """The actor's OAuth2 client ids. On a first attempt a fault raises (the
    ids must be recorded before any bucket goes); on a resume the bucket may
    already be gone, so the recorded ids are the source and a fault here is
    folded."""
    from .oauth2 import _actor_client_ids

    if strict:
        return _actor_client_ids(config, actor_id)
    try:
        return _actor_client_ids(config, actor_id)
    except DbError as e:  # folds DbError: resume; the tombstone's ids cover it
        logger.warning(
            f"Resuming deletion of actor {actor_id}: its client bucket could not "
            f"be read ({e}); using the client ids its tombstone recorded"
        )
        return []


def _lease_keeper(
    actor_id: str, config: Config, data: dict[str, Any] | None
) -> Callable[[], None]:
    """A callback ``Actor.delete`` runs before each peer-notifying step: it
    renews this finisher's lease once a third of it has passed, so a wipe
    whose peer DELETEs are slow (each up to the proxy timeout) does not
    outlive the lease and get a second finisher beside it. A lease another
    finisher took over raises ``DeletionInProgress``, which stops this one."""
    lease_id = (data or {}).get("lease_id")
    last = [time.monotonic()]

    def keep() -> None:
        if time.monotonic() - last[0] < DELETION_LEASE / 3:
            return
        deletion.renew_lease(actor_id, config, lease_id)
        last[0] = time.monotonic()

    return keep


def _update(
    actor_id: str, config: Config, data: dict[str, Any], changes: dict[str, Any]
) -> dict[str, Any]:
    """Change the tombstone under the lease this finisher holds."""
    changed = deletion.update_tombstone(actor_id, config, data, changes)
    if changed is None:
        # Someone took the lease from under us (ours lapsed): stop, the
        # other finisher carries on.
        raise DeletionInProgress(actor_id, 1)
    return changed


def _fire(
    hooks: HookRegistry,
    event: str,
    actor: Actor | None,
    config: Config,
    **kwargs: Any,
) -> None:
    from .oauth2 import _fire_lifecycle

    _fire_lifecycle(hooks, event, actor, config, **kwargs)
