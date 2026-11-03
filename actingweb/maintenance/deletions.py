"""Find and finish actor deletions that stopped part-way: ``actingweb-deletions``.

An actor's wipe (``DELETE /<id>``, a replacement at adoption, a sign-in that
finished a stalled one) is many writes behind a deletion tombstone, and the
actor row goes last. A wipe that stalled (a backend fault, a crashed process)
leaves a live row under a tombstone. The next ``DELETE`` or sign-in finishes
it; this command finds the ones nobody comes back for.

Subcommands (dry run unless ``--apply``):

``report [ACTOR_ID]``
    Tombstones whose actor row still exists, each as ``stalled`` (finish it
    with ``resume``), ``in progress`` (a finisher holds its lease right now)
    or ``legacy, review`` (a tombstone with no recorded reason, written before
    resumable deletion: a stalled ``DELETE``, or a live actor whose create
    failed to clear it; ``resume`` it or ``clear`` it). Also tombstones whose
    row is gone but whose wipe never recorded its end (``unfinished``: client
    index rows may remain). Exit 0 when nothing is stalled, legacy or
    unfinished, 1 otherwise, 2 when the tombstone store cannot be read.
``resume [ACTOR_ID] [--apply]``
    Finish the stalled and unfinished ones (a legacy one only when named).
    Fires **no** application hooks: the finished actor ids are printed as
    their own list, so the application's ``actor_deleted_complete`` cleanup
    can be run for them. Peers are notified as each tombstone recorded
    (``--no-notify-peers`` turns it off for all). With ``--apply`` on
    PostgreSQL it also purges expired rows from the tombstone and
    email-verification index buckets, which nothing else purges (DynamoDB
    reaps them with its native TTL). Dry run: exit 1 when there is work.
``clear ACTOR_ID [--apply]``
    Remove the tombstone of a live actor the operator judges stray (confirmed
    with a strict read).

Run it with the same environment as the application (``DATABASE_BACKEND``,
the database prefix, credentials, ``INDEXED_PROPERTIES``), and pass
``--no-unique-creator`` when the application runs without
``with_unique_creator()``: the creators record of a finished actor is released
only under the setting the application uses.

Cost: one read of the tombstone bucket (every tombstone of the retention
window; on PostgreSQL also expired ones until purged) and one actor-row read
per unfinished tombstone; ``resume`` adds a full wipe per stalled actor.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from actingweb.db.exceptions import DbError, DeletionInProgress

logger = logging.getLogger(__name__)

PROG = "actingweb-deletions"

STALLED = "stalled"
IN_PROGRESS = "in progress"
LEGACY = "legacy, review"
UNFINISHED = "unfinished"


class StoreUnavailable(Exception):
    """The tombstone store or the actor table could not be read."""


@dataclass
class Finding:
    actor_id: str
    state: str
    reason: str | None
    deleted_at: str | None
    data: dict[str, Any] = field(default_factory=dict)


def make_config(args: argparse.Namespace) -> Any:
    """The deployment's config: its backend, its uniqueness setting."""
    from actingweb.config import Config

    return Config(
        database=os.getenv("DATABASE_BACKEND", "dynamodb"),
        unique_creator=bool(args.unique_creator),
        force_email_prop_as_creator=False,
    )


def scan(config: Any, only: str | None = None) -> list[Finding]:
    """Every tombstone that is not a finished wipe, classified."""
    from actingweb import deletion
    from actingweb.constants import DELETED_ACTORS_BUCKET, DELETED_ACTORS_STORE
    from actingweb.db import get_actor, get_attribute

    try:
        if only:
            _, data = deletion.read_tombstone(only, config)
            rows: dict[str, Any] = {only: {"data": data}} if data is not None else {}
        else:
            rows = (
                get_attribute(config).get_bucket(
                    actor_id=DELETED_ACTORS_STORE,
                    bucket=DELETED_ACTORS_BUCKET,
                    strict=True,
                )
                or {}
            )
    except DbError as e:  # folds DbError: reported, exit 2
        raise StoreUnavailable(f"cannot read the deletion tombstones: {e}") from e
    findings: list[Finding] = []
    actors = get_actor(config)
    for actor_id in sorted(rows):
        raw = rows[actor_id].get("data") if isinstance(rows[actor_id], dict) else None
        data = dict(raw) if isinstance(raw, dict) else {}
        finished = bool(data.get("finished_at"))
        if finished and not only:
            continue  # a finished wipe (reading its row would cost one per row)
        resumable = deletion.is_resumable(data)
        try:
            row = actors.get(actor_id=actor_id)
        except DbError as e:  # folds DbError: reported, exit 2
            raise StoreUnavailable(f"cannot read actor {actor_id}: {e}") from e
        if not row:
            if resumable and not finished:
                findings.append(
                    Finding(
                        actor_id,
                        UNFINISHED,
                        data.get("reason"),
                        data.get("deleted_at"),
                        data,
                    )
                )
            continue  # a pre-resumable tombstone of a finished wipe (it has a TTL)
        if not resumable or finished:
            # A finished wipe whose actor row is live again (an id re-created
            # without its tombstone cleared) needs review like a legacy one.
            state = LEGACY
        elif deletion.lease_remaining(data) > 0:
            state = IN_PROGRESS
        else:
            state = STALLED
        findings.append(
            Finding(actor_id, state, data.get("reason"), data.get("deleted_at"), data)
        )
    return findings


def _print(findings: list[Finding]) -> None:
    if not findings:
        print("No unfinished deletions.")
        return
    for f in findings:
        print(
            f"{f.actor_id}\t{f.state}\treason={f.reason or '-'}\t"
            f"deleted_at={f.deleted_at or '-'}"
        )


def cmd_report(args: argparse.Namespace) -> int:
    findings = scan(make_config(args), args.actor_id)
    _print(findings)
    return 1 if any(f.state != IN_PROGRESS for f in findings) else 0


def _finish_one(config: Any, finding: Finding, notify_peers: bool) -> None:
    from actingweb import actor as actor_module
    from actingweb import deletion
    from actingweb.deletion_finish import finish_deletion

    if finding.state == UNFINISHED:
        # The row is gone; what can remain is the client index rows the
        # tombstone recorded. Remove them and record the end.
        from actingweb.oauth2 import _delete_actor_clients

        ids = finding.data.get("client_ids")
        _delete_actor_clients(
            config,
            finding.actor_id,
            [str(c) for c in ids] if isinstance(ids, list) else [],
            actor_deleted=True,
        )
        deletion.mark_finished(finding.actor_id, config, None)
        return
    target = actor_module.Actor(actor_id=finding.actor_id, config=config)
    if not target.id:
        raise DbError("actor read", finding.actor_id)
    if (
        finish_deletion(
            target,
            config=config,
            hooks=None,
            origin="operator",
            notify_peers=notify_peers,
        )
        is None
    ):
        raise DbError("actor row delete", finding.actor_id)


def cmd_resume(args: argparse.Namespace) -> int:
    config = make_config(args)
    findings = scan(config, args.actor_id)
    todo = [
        f
        for f in findings
        if f.state in (STALLED, UNFINISHED) or (f.state == LEGACY and args.actor_id)
    ]
    if not args.apply:
        for f in todo:
            print(f"would finish {f.actor_id} ({f.state})")
        for f in findings:
            if f not in todo:
                print(f"skipping {f.actor_id} ({f.state})")
        print(f"Dry run: would finish {len(todo)}. Re-run with --apply.")
        return 1 if todo else 0
    finished: list[str] = []
    failed = 0
    for f in todo:
        try:
            _finish_one(config, f, notify_peers=not args.no_notify_peers)
        except DeletionInProgress as e:
            print(f"{f.actor_id}: in progress, skipped (retry in {e.retry_after} s)")
            failed += 1
            continue
        except DbError as e:  # folds DbError: reported per actor, exit 1
            print(f"{f.actor_id}: failed: {e}")
            failed += 1
            continue
        finished.append(f.actor_id)
        print(f"{f.actor_id}: finished")
    if config.database == "postgresql":
        _purge_expired(config)
    if finished:
        print(
            "Finished (no application hooks ran; run your actor_deleted_complete "
            "cleanup for these):"
        )
        for actor_id in finished:
            print(actor_id)
    remaining = [f for f in findings if f not in todo and f.state != IN_PROGRESS]
    return 1 if failed or remaining else 0


def _purge_expired(config: Any) -> None:
    from actingweb.constants import (
        DELETED_ACTORS_BUCKET,
        EMAIL_VERIFY_TOKEN_INDEX_BUCKET,
    )
    from actingweb.db import get_attribute

    try:
        purged = get_attribute(config).delete_expired(
            buckets=[DELETED_ACTORS_BUCKET, EMAIL_VERIFY_TOKEN_INDEX_BUCKET]
        )
        print(f"Purged {purged} expired tombstone and verification-index rows.")
    except Exception as e:  # folds DbError: purge after resumes; next run retries
        print(f"Could not purge expired rows: {e}")


def cmd_clear(args: argparse.Namespace) -> int:
    from actingweb import deletion

    config = make_config(args)
    findings = scan(config, args.actor_id)
    if not findings:
        print(f"{args.actor_id}: no tombstone on a live actor; nothing to clear")
        return 0
    if not args.apply:
        print(f"would clear the tombstone of {args.actor_id} ({findings[0].state})")
        return 1
    try:
        deletion.clear_actor_tombstone(args.actor_id, config, strict=True)
    except DbError as e:  # folds DbError: reported, exit 1
        print(f"{args.actor_id}: failed: {e}")
        return 1
    print(f"{args.actor_id}: tombstone cleared")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description=(__doc__ or "").strip().split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--no-unique-creator",
            dest="unique_creator",
            action="store_false",
            help="the application runs without with_unique_creator()",
        )

    rep = sub.add_parser("report", help="list unfinished deletions")
    rep.add_argument("actor_id", nargs="?", default=None)
    common(rep)

    res = sub.add_parser("resume", help="finish stalled deletions")
    res.add_argument("actor_id", nargs="?", default=None)
    res.add_argument("--apply", action="store_true", help="write (default: dry run)")
    res.add_argument(
        "--no-notify-peers",
        action="store_true",
        help="send no peer a DELETE, whatever the tombstones recorded",
    )
    common(res)

    clr = sub.add_parser("clear", help="remove a stray tombstone from a live actor")
    clr.add_argument("actor_id")
    clr.add_argument("--apply", action="store_true", help="write (default: dry run)")
    common(clr)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _build_parser().parse_args(argv)
    handlers = {"report": cmd_report, "resume": cmd_resume, "clear": cmd_clear}
    try:
        return handlers[args.command](args)
    except StoreUnavailable as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
