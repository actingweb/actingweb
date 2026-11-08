"""Find and remove peer state written before 3.16: ``actingweb-peer-state``.

Before 3.16 a callback was accepted without authentication, and a peer could
reach another peer's paths (``CHANGELOG.rst``, 3.16 ``SECURITY``). What such
requests wrote survives the upgrade: a stored copy of permissions for a peer
the actor has no trust with, permissions stamped in the future (which made
every later update look older), callback state for subscriptions the actor
never made, and peer data stored for a peer it has no trust or subscription
with. This command reports those rows and, with ``--apply``, removes them.
It never rebuilds a replica: removed peer data comes back with the next
subscription callback or sync.

Subcommands (both required to name one; dry run unless ``--apply``):

``report [ACTOR_ID]``
    List, per actor, every row of the kinds below. Exit 0 when nothing
    removable is found (``remote-unknown`` rows are information), 1 when
    something is, 2 when a store could not be read.
``prune [ACTOR_ID] [--apply]``
    The same rows; with ``--apply`` they are deleted. Exit 0 when nothing is
    found, 1 when rows were found (dry run) or removed, 2 when a store could
    not be read, a delete failed, or a removed copy was not rebuilt.

Kinds, per actor (names are compared whole: a peer id may contain ``:``):

``peer-permissions``
    A ``_peer_permissions`` row whose name is not ``<actor>:<peer>`` for a
    peer the actor has a trust row with.
``future-permissions``
    A ``_peer_permissions`` row of a trusted peer whose ``fetched_at`` is more
    than five minutes ahead of now, or does not parse. With ``--apply`` it is
    rebuilt at once, as a ``permissions-copy`` is.
``callback-state``
    A ``_callback_state`` row whose name is not ``state:`` or ``pending:``
    plus ``<peer>:<subid>`` of a subscription this actor made (``callback``
    true).
``permissions-copy`` (only with ``--all-permissions``)
    Every other ``_peer_permissions`` row: a forged copy for a peer the actor
    does trust (a pre-3.16 unauthenticated callback with a current timestamp)
    looks like a real one. With ``--apply`` each removed copy is rebuilt
    right after its removal, before the next one, by a permission query to
    its peer (``rebuilt`` / ``not rebuilt``): without a copy, the peer's next
    callback would be taken for its first, and a pattern revoked in it would
    delete no stored data.
``remote-data``
    A ``remote:<peer>`` bucket (``RemotePeerStore``) for a peer with no trust
    row, or with no subscription this actor made to it. Only bucket names
    ``get_remote_bucket()`` builds for a well-formed peer id are considered;
    any other ``remote:`` bucket is reported as ``remote-unknown`` and never
    removed. Peer data stored for a trusted peer without a subscription this
    actor made (an application writing ``RemotePeerStore`` itself) counts as
    stale: the library removes it too when the last subscription goes.

Run it with the same environment as the application (``DATABASE_BACKEND``,
the database prefix, credentials), after every instance runs 3.16, and in a
quiet period: a row created between this command's read and its delete (a
trust or subscription made at that moment) is misread as stale, and the next
callback writes it again. Application processes keep permissions they cached
until restarted; restart them after ``prune --apply``. It runs no
application hook.

Cost, per actor: one read of its trust rows, one of its subscriptions, one of
its attribute bucket names, one of each of the two buckets; ``--rps`` bounds
reads (and deletes) per second, as ``actingweb-verify-orphans`` does.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from actingweb.constants import PEER_PERMISSIONS_BUCKET
from actingweb.db.exceptions import DbError
from actingweb.maintenance.verify_orphans import RateLimiter

logger = logging.getLogger(__name__)

PROG = "actingweb-peer-state"
CALLBACK_STATE_BUCKET = "_callback_state"
REMOTE_PREFIX = "remote:"
RESERVED_ACTOR_ID_PREFIX = "_actingweb_"
# The receiver's allowance for a sender's clock (handlers/callbacks.py).
FUTURE_SKEW = timedelta(minutes=5)

PEER_PERMISSIONS = "peer-permissions"
FUTURE_PERMISSIONS = "future-permissions"
CALLBACK_STATE = "callback-state"
PERMISSIONS_COPY = "permissions-copy"
REMOTE_DATA = "remote-data"
REMOTE_UNKNOWN = "remote-unknown"
# A trusted peer's copy: re-fetched from the peer right after removal.
REBUILT_KINDS = frozenset({FUTURE_PERMISSIONS, PERMISSIONS_COPY})


class StoreUnavailable(Exception):
    """A store could not be read, or a delete failed."""


@dataclass(frozen=True)
class Finding:
    actor_id: str
    kind: str
    bucket: str
    name: str  # the row's name; "" for a whole bucket

    @property
    def prunable(self) -> bool:
        return self.kind != REMOTE_UNKNOWN


def make_config() -> Any:
    """The deployment's config: its backend (from the environment)."""
    from actingweb.config import Config

    return Config(database=os.getenv("DATABASE_BACKEND", "dynamodb"))


def _future_or_unparsable(fetched_at: Any, now: datetime) -> bool:
    if not isinstance(fetched_at, str) or not fetched_at:
        return True
    try:
        parsed = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    except (ValueError, OverflowError):
        return True
    return parsed > now + FUTURE_SKEW


def _row_data(row: Any) -> dict[str, Any]:
    data = row.get("data") if isinstance(row, dict) else None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return {}
    return data if isinstance(data, dict) else {}


def _remote_peer(bucket: str) -> str | None:
    """The peer id of a ``remote:`` bucket ``get_remote_bucket()`` builds for
    a well-formed peer id, or None for any other bucket."""
    from actingweb.remote_storage import PERMISSIVE_PEER_ID_PATTERN, get_remote_bucket

    peer = bucket[len(REMOTE_PREFIX) :]
    if not PERMISSIVE_PEER_ID_PATTERN.fullmatch(peer):
        return None
    return peer if get_remote_bucket(peer) == bucket else None


def scan_actor(
    config: Any,
    actor_id: str,
    limiter: RateLimiter,
    now: datetime | None = None,
    *,
    all_permissions: bool = False,
) -> list[Finding]:
    """Every stale row of one actor. Reads strictly: a fault raises
    ``StoreUnavailable`` (nothing is pruned on a guess)."""
    from actingweb.db import (
        get_attribute,
        get_attribute_bucket_list,
        get_subscription_list,
        get_trust_list,
    )

    now = now or datetime.now(UTC)
    attributes = get_attribute(config)
    try:
        limiter.wait()
        trusts = get_trust_list(config).fetch(actor_id, strict=True) or []
        limiter.wait()
        subscriptions = get_subscription_list(config).fetch(actor_id, strict=True) or []
        limiter.wait()
        buckets = (
            get_attribute_bucket_list(config).fetch_timestamps(actor_id, strict=True)
            or {}
        )
        limiter.wait()
        permissions = (
            attributes.get_bucket(
                actor_id=actor_id, bucket=PEER_PERMISSIONS_BUCKET, strict=True
            )
            or {}
        )
        limiter.wait()
        states = (
            attributes.get_bucket(
                actor_id=actor_id, bucket=CALLBACK_STATE_BUCKET, strict=True
            )
            or {}
        )
    except DbError as e:  # folds DbError: reported, exit 2
        raise StoreUnavailable(f"cannot read actor {actor_id}: {e}") from e

    trusted = {str(t.get("peerid")) for t in trusts if t.get("peerid")}
    made = [s for s in subscriptions if s.get("callback")]
    subscribed_to = {str(s.get("peerid")) for s in made}
    permission_names = {f"{actor_id}:{peer}" for peer in trusted}
    state_names = {
        f"{prefix}:{s.get('peerid')}:{s.get('subscriptionid')}"
        for s in made
        for prefix in ("state", "pending")
    }

    findings: list[Finding] = []
    for name in sorted(permissions):
        if name not in permission_names:
            findings.append(
                Finding(actor_id, PEER_PERMISSIONS, PEER_PERMISSIONS_BUCKET, name)
            )
        elif _future_or_unparsable(_row_data(permissions[name]).get("fetched_at"), now):
            findings.append(
                Finding(actor_id, FUTURE_PERMISSIONS, PEER_PERMISSIONS_BUCKET, name)
            )
        elif all_permissions:
            # A live peer's copy: a forged one (a pre-3.16 unauthenticated
            # callback with a current timestamp) looks like any other.
            findings.append(
                Finding(actor_id, PERMISSIONS_COPY, PEER_PERMISSIONS_BUCKET, name)
            )
    for name in sorted(states):
        if name not in state_names:
            findings.append(
                Finding(actor_id, CALLBACK_STATE, CALLBACK_STATE_BUCKET, name)
            )
    for bucket in sorted(b for b in buckets if b.startswith(REMOTE_PREFIX)):
        peer = _remote_peer(bucket)
        if peer is None:
            findings.append(Finding(actor_id, REMOTE_UNKNOWN, bucket, ""))
        elif peer not in trusted or peer not in subscribed_to:
            findings.append(Finding(actor_id, REMOTE_DATA, bucket, ""))
    return findings


def _actor_ids(config: Any, only: str | None) -> list[str]:
    from actingweb.db import get_actor_list

    if only:
        return [only]
    try:
        fetched = get_actor_list(config).fetch(strict=True)
        rows = fetched if isinstance(fetched, list) else []
    except DbError as e:  # folds DbError: reported, exit 2
        raise StoreUnavailable(f"cannot list actors: {e}") from e
    ids = [str(r.get("id")) for r in rows if isinstance(r, dict) and r.get("id")]
    return sorted(i for i in ids if not i.startswith(RESERVED_ACTOR_ID_PREFIX))


def scan(
    config: Any, only: str | None, limiter: RateLimiter, all_permissions: bool = False
) -> list[Finding]:
    findings: list[Finding] = []
    for actor_id in _actor_ids(config, only):
        findings.extend(
            scan_actor(config, actor_id, limiter, all_permissions=all_permissions)
        )
    return findings


def prune(
    config: Any,
    findings: list[Finding],
    limiter: RateLimiter,
    not_rebuilt: list[Finding] | None = None,
) -> int:
    """Delete the prunable findings; the number removed. A trusted peer's
    copy is rebuilt right after its removal; one that is not is appended to
    ``not_rebuilt``. A fault raises ``StoreUnavailable`` after printing what
    was removed so far."""
    from actingweb.db import get_attribute

    attributes = get_attribute(config)
    removed = 0
    for f in findings:
        if not f.prunable:
            continue
        limiter.wait()
        try:
            if f.name:
                ok = attributes.delete_attr(
                    actor_id=f.actor_id, bucket=f.bucket, name=f.name
                )
            else:
                ok = attributes.delete_bucket(actor_id=f.actor_id, bucket=f.bucket)
        except DbError as e:  # folds DbError: reported, exit 2
            raise StoreUnavailable(
                f"removed {removed}, then could not remove {f.bucket} {f.name}: {e}"
            ) from e
        if ok is False:
            raise StoreUnavailable(
                f"removed {removed}, then could not remove {f.bucket} {f.name}"
            )
        removed += 1
        print(f"removed\t{f.actor_id}\t{f.kind}\t{f.bucket}\t{f.name or '-'}")
        if (
            f.kind in REBUILT_KINDS
            and f.name
            and not _rebuild_copy(config, f, limiter)
            and not_rebuilt is not None
        ):
            not_rebuilt.append(f)
    return removed


def _print(findings: list[Finding]) -> None:
    if not findings:
        print("No peer state to remove.")
        return
    for f in findings:
        note = (
            "" if f.prunable else "\t(never removed: not a bucket this library names)"
        )
        print(f"{f.actor_id}\t{f.kind}\t{f.bucket}\t{f.name or '-'}{note}")


def cmd_report(args: argparse.Namespace) -> int:
    findings = scan(
        make_config(), args.actor_id, RateLimiter(args.rps), args.all_permissions
    )
    _print(findings)
    # Only what prune would remove counts: an unknown bucket is information.
    return 1 if any(f.prunable for f in findings) else 0


def cmd_prune(args: argparse.Namespace) -> int:
    config = make_config()
    limiter = RateLimiter(args.rps)
    findings = scan(config, args.actor_id, limiter, args.all_permissions)
    _print(findings)
    if not any(f.prunable for f in findings):
        return 0
    if not args.apply:
        count = sum(1 for f in findings if f.prunable)
        print(f"Dry run: would remove {count}. Re-run with --apply.")
        return 1
    not_rebuilt: list[Finding] = []
    removed = prune(config, findings, limiter, not_rebuilt)
    print(
        f"Removed {removed}. Restart the application's processes: they keep "
        "permissions they cached until then."
    )
    if not_rebuilt:
        # A removed copy that was not rebuilt leaves the peer's next callback
        # taken for its first: exit as a failure, so a script notices.
        print(
            f"Not rebuilt: {len(not_rebuilt)}. Run the permission query for "
            "each once its peer answers."
        )
        return 2
    return 1


def _rebuild_copy(config: Any, f: Finding, limiter: RateLimiter) -> bool:
    """Query the peer whose copy was just removed (a ``permissions-copy``, or
    a ``future-permissions`` row of a trusted peer) and store its answer,
    before the next removal: without a copy, the peer's next callback is
    taken for its first, and a pattern revoked in it would delete no stored
    data. A peer that does not answer, or a store fault, is listed (``not
    rebuilt``); its next callback or query rebuilds the copy."""
    from actingweb.peer_permissions import (
        fetch_peer_permissions,
        get_peer_permission_store,
    )

    peer_id = f.name[len(f.actor_id) + 1 :]
    limiter.wait()
    try:
        # The query reads the trust row first (strict), then stores.
        perms = fetch_peer_permissions(f.actor_id, peer_id, config)
        why = perms.fetch_error
        if not why and not get_peer_permission_store(config).store_permissions(perms):
            why = "store refused"
    except DbError:  # folds DbError: listed, the next query rebuilds it
        why = "store fault"
    if why:
        print(f"not rebuilt\t{f.actor_id}\t{peer_id}\t{why}")
        return False
    print(f"rebuilt\t{f.actor_id}\t{peer_id}")
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description=(__doc__ or "").strip().split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("actor_id", nargs="?", default=None, help="one actor only")
        p.add_argument(
            "--rps",
            type=float,
            default=10.0,
            help="reads and deletes per second (default 10, as "
            "actingweb-verify-orphans; 0 = unlimited)",
        )
        p.add_argument(
            "--all-permissions",
            action="store_true",
            help="also every live peer's stored permission copy; with --apply, "
            "each is rebuilt at once by a permission query to the peer",
        )

    common(sub.add_parser("report", help="list stale peer state"))
    prune_parser = sub.add_parser("prune", help="remove stale peer state")
    common(prune_parser)
    prune_parser.add_argument(
        "--apply", action="store_true", help="delete (default: dry run)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _build_parser().parse_args(argv)
    handlers = {"report": cmd_report, "prune": cmd_prune}
    try:
        return handlers[args.command](args)
    except StoreUnavailable as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
