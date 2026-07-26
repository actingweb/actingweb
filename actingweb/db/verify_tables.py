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
    "lookup_mode_enabled",
    "required_models",
    "required_table_names",
    "verify_tables",
    "main",
]


def lookup_mode_enabled() -> bool:
    """Whether property reverse lookup uses the lookup table (the default).

    Mirrors ``Config.use_lookup_table`` for callers that only have the
    environment (a CLI has no ``ActingWebApp`` instance to ask).
    """
    return os.getenv("USE_PROPERTY_LOOKUP_TABLE", "true").strip().lower() not in (
        "false",
        "0",
        "no",
    )


def required_models(use_lookup_table: bool | None = None) -> list[type[Model]]:
    """The DynamoDB model classes whose tables must exist for this config.

    This is the single source of truth for "which tables does ActingWeb need"
    — :meth:`ActingWebApp._prewarm_dynamodb_tables` consumes the same list, so
    the documented set and the created set cannot drift apart.

    Args:
        use_lookup_table: Reverse-lookup mode. ``None`` reads the environment.

    Returns:
        Model classes, in a stable order.
    """
    if use_lookup_table is None:
        use_lookup_table = lookup_mode_enabled()

    from .dynamodb.actor import Actor
    from .dynamodb.attribute import Attribute
    from .dynamodb.peertrustee import PeerTrustee
    from .dynamodb.property import Property, PropertyLegacy
    from .dynamodb.subscription import Subscription
    from .dynamodb.subscription_diff import SubscriptionDiff
    from .dynamodb.subscription_suspension import SubscriptionSuspension
    from .dynamodb.trust import Trust

    models: list[type[Model]] = [
        Actor,
        Attribute,
        PeerTrustee,
        # Same table name either way; the schemas differ (lookup mode creates
        # it without the legacy value-keyed GSI).
        Property if use_lookup_table else PropertyLegacy,
        Subscription,
        SubscriptionDiff,
        SubscriptionSuspension,
        Trust,
    ]
    # The v2 lookup table exists only in lookup mode. The deprecated v1 table
    # is read-only fallback and never required.
    if use_lookup_table:
        from .dynamodb.property_lookup import PropertyLookupV2

        models.append(PropertyLookupV2)
    return models


def required_table_names(use_lookup_table: bool | None = None) -> list[str]:
    """Resolved table names (``AWS_DB_PREFIX`` applied) that must exist."""
    return [str(m.Meta.table_name) for m in required_models(use_lookup_table)]


def verify_tables(
    use_lookup_table: bool | None = None,
) -> tuple[list[str], list[str]]:
    """Check each required table for existence.

    Issues one ``DescribeTable`` per model. Never creates anything.

    Args:
        use_lookup_table: Reverse-lookup mode. ``None`` reads the environment.

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
    for model in required_models(use_lookup_table):
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--lookup-table",
        dest="use_lookup_table",
        action="store_true",
        default=None,
        help="Assume lookup-table reverse lookup (the 3.13 default).",
    )
    mode.add_argument(
        "--legacy",
        dest="use_lookup_table",
        action="store_false",
        help="Assume deprecated legacy GSI reverse lookup.",
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
        names = required_table_names(args.use_lookup_table)
    except ImportError as e:
        print(f"Could not load the DynamoDB backend: {e}", file=sys.stderr)
        return 2

    use_lookup = (
        lookup_mode_enabled()
        if args.use_lookup_table is None
        else args.use_lookup_table
    )
    mode_label = "lookup-table" if use_lookup else "legacy (deprecated)"
    prefix = os.getenv("AWS_DB_PREFIX", "demo_actingweb")
    print(f"Reverse-lookup mode: {mode_label}")
    print(f"Table prefix:        {prefix}")
    print(f"Required tables:     {len(names)}")

    if args.list:
        for name in names:
            print(f"  {name}")
        return 0

    try:
        present, missing = verify_tables(args.use_lookup_table)
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
