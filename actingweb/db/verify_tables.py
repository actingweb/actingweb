"""Verify that every DynamoDB table ActingWeb needs already exists.

Deployments that manage tables via infrastructure-as-code set
``AWS_DB_AUTO_CREATE_TABLES=false`` and drop ``CreateTable``/``DescribeTable``
from the runtime IAM role. That is the recommended production posture, but it
makes "all required tables exist" a *precondition* the library can no longer
check for itself: with auto-creation off, :func:`~actingweb.db.dynamodb._ensure.ensure_table`
deliberately skips ``exists()`` so a locked-down role never pays (or leaks) an
``AccessDenied`` per accessor construction.

This module is the out-of-band answer. Run it from an operator shell — with
credentials that *do* have ``DescribeTable`` — before or after flipping the
flag::

    AWS_DB_PREFIX=myapp poetry run python -m actingweb.db.verify_tables

It only ever reads: no table is created, and nothing here runs at request time,
so the runtime ``DescribeTable`` count stays at zero.

Exit codes: ``0`` all required tables present, ``1`` one or more missing,
``2`` the check could not be performed (wrong backend, bad credentials).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pynamodb.models import Model

__all__ = [
    "required_models",
    "required_table_names",
    "verify_tables",
    "main",
]


def required_models(unique_creator: bool = False) -> list[type[Model]]:
    """The DynamoDB model classes whose tables must exist for this config.

    This is the single source of truth for "which tables does ActingWeb need"
    — :meth:`ActingWebApp._prewarm_dynamodb_tables` consumes the same list, so
    the documented set and the created set cannot drift apart.

    Args:
        unique_creator: ``with_unique_creator()`` is on, which needs the
            ``creators`` table.

    Returns:
        Model classes, in a stable order.
    """
    from .dynamodb.actor import Actor
    from .dynamodb.attribute import Attribute
    from .dynamodb.peertrustee import PeerTrustee
    from .dynamodb.property import Property
    from .dynamodb.property_lookup import PropertyLookupV2
    from .dynamodb.subscription import Subscription
    from .dynamodb.subscription_diff import SubscriptionDiff
    from .dynamodb.subscription_suspension import SubscriptionSuspension
    from .dynamodb.trust import Trust

    models: list[type[Model]] = [
        Actor,
        Attribute,
        PeerTrustee,
        Property,
        Subscription,
        SubscriptionDiff,
        SubscriptionSuspension,
        Trust,
        PropertyLookupV2,
    ]
    if unique_creator:
        from .dynamodb.creator import Creator

        models.append(Creator)
    return models


def required_table_names(unique_creator: bool = False) -> list[str]:
    """Resolved table names (``AWS_DB_PREFIX`` applied) that must exist."""
    return [str(m.Meta.table_name) for m in required_models(unique_creator)]


def verify_tables(unique_creator: bool = False) -> tuple[list[str], list[str]]:
    """Check each required table for existence.

    Issues one ``DescribeTable`` per model. Never creates anything.

    Returns:
        ``(present, missing)`` — resolved table names, each list sorted as in
        :func:`required_models`.

    Raises:
        Exception: Propagates credential/permission errors from botocore, so a
            role lacking ``DescribeTable`` fails loudly instead of reporting
            every table as missing.
    """
    present: list[str] = []
    missing: list[str] = []
    for model in required_models(unique_creator):
        name = str(model.Meta.table_name)
        if model.exists():
            present.append(name)
        else:
            missing.append(name)
    return present, missing


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — see the module docstring for exit codes."""
    parser = argparse.ArgumentParser(
        prog="python -m actingweb.db.verify_tables",
        description=(
            "Verify that every DynamoDB table ActingWeb requires exists. "
            "Reads only; never creates. Run with credentials that have "
            "dynamodb:DescribeTable (an operator role, not the slimmed "
            "runtime role)."
        ),
    )
    parser.add_argument(
        "--unique-creator",
        action="store_true",
        help=(
            "The app runs with_unique_creator(), which needs the creators "
            "table (actingweb-unique-creators enable creates and fills it)."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the required table names and exit without querying AWS.",
    )
    args = parser.parse_args(argv)

    backend = os.getenv("DATABASE_BACKEND", "dynamodb").strip().lower()
    if backend != "dynamodb":
        print(
            f"DATABASE_BACKEND={backend}: this check is DynamoDB-only. "
            "PostgreSQL schemas are managed by Alembic — run "
            "'alembic current' / 'alembic upgrade head' instead.",
            file=sys.stderr,
        )
        return 2

    try:
        names = required_table_names(args.unique_creator)
    except ImportError as e:
        print(f"Could not load the DynamoDB backend: {e}", file=sys.stderr)
        return 2

    prefix = os.getenv("AWS_DB_PREFIX", "demo_actingweb")
    print(f"Table prefix:        {prefix}")
    print(f"Required tables:     {len(names)}")

    if args.list:
        for name in names:
            print(f"  {name}")
        return 0

    try:
        present, missing = verify_tables(args.unique_creator)
    except Exception as e:  # credentials, permissions, endpoint
        print(f"\nCheck could not be performed: {e}", file=sys.stderr)
        print(
            "Ensure credentials are valid and the role has "
            "dynamodb:DescribeTable, and that AWS_DEFAULT_REGION / "
            "AWS_DB_HOST match the target deployment.",
            file=sys.stderr,
        )
        return 2

    print()
    for name in present:
        print(f"  OK       {name}")
    for name in missing:
        print(f"  MISSING  {name}")

    if missing:
        print(
            f"\n{len(missing)} required table(s) missing. With "
            "AWS_DB_AUTO_CREATE_TABLES=false the library will not create "
            "them; declare them in your infrastructure-as-code (see "
            "docs/reference/database-backends.rst for key schemas) before "
            "the next deploy.",
            file=sys.stderr,
        )
        return 1

    print(f"\nAll {len(present)} required tables exist.")
    return 0


def _cli() -> Any:
    raise SystemExit(main())


if __name__ == "__main__":
    _cli()
