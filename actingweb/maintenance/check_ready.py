"""``actingweb-check-ready``: what the application's start-up check would
say about this store, without starting the application (4.0).

Run with the application's environment before a deploy. Each gate
``ActingWebApp.check_ready()`` applies is reported in one of three states:

- ``ready``;
- ``ready at first start``: the store holds no user actors, and the first
  start makes it ready itself (creator uniqueness enables itself, reverse
  lookup and the email marker mark themselves);
- ``REFUSED``, with the fix line.

The command reads only: it writes nothing, creates no table and never
calls ``check_ready()``. It cannot see what the application sets in its
builder, so it takes flags for those settings and prints what it assumed:

- ``--properties a,b`` for ``with_indexed_properties()`` (default:
  ``INDEXED_PROPERTIES``, else the library default);
- ``--no-unique-creator`` for ``with_unique_creator(False)``;
- ``--email-as-creator`` for ``with_email_as_creator()``.

Exit status 0 when every gate is ready (or ready at first start), 1 when a
gate refuses, 2 when the store could not be read.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from actingweb.maintenance._common import backend, preflight

PROG = "actingweb-check-ready"
logger = logging.getLogger(PROG)

READY = "ready"
FIRST_START = "ready at first start"


# -- the probes (read-only; patched by the tests) ------------------------------


def _lookup_attention(database: str, names: list[str]) -> list[str]:
    """The names that are not ready. A missing lookup (or marker) table is
    an answer, not a fault: no name is marked yet (the first start, or the
    backfill, creates it)."""
    from actingweb.db.exceptions import DbError
    from actingweb.interface.app import _store_answered
    from actingweb.maintenance.property_lookup import read_readiness

    try:
        return list(read_readiness(database, names).attention)
    except DbError as e:
        if "lookup table missing" in str(e) or _store_answered(e):
            return list(names)
        raise


def _uniqueness_missing(config: Any) -> str | None:
    from actingweb.maintenance.unique_creators import missing_enforcement

    return missing_enforcement(config)


def _store_empty(config: Any) -> bool:
    """No user actor (a missing actor table reads as empty: a fresh store)."""
    from actingweb.interface.app import _store_answered
    from actingweb.maintenance.unique_creators import no_actors

    try:
        return no_actors(config, strict=True)
    except Exception as e:  # folds DbError: a missing table is an answer
        if _store_answered(e):
            return True
        raise


def _schema_problems(database: str) -> list[str]:
    if database != "postgresql":
        return []
    from actingweb.db.postgresql.attribute import attribute_schema_problems

    return attribute_schema_problems()


def _email_marker(config: Any) -> dict[str, Any] | None:
    """The email-as-creator marker, read without constructing the backend
    (on DynamoDB its constructor creates a missing table)."""
    from actingweb.constants import READINESS_BUCKET, READINESS_STORE
    from actingweb.interface.app import _store_answered
    from actingweb.maintenance.email_as_creator import MARKER_NAME

    try:
        if config.database == "postgresql":
            from actingweb.db import get_attribute

            row = get_attribute(config).get_attr_strict(
                READINESS_STORE, READINESS_BUCKET, MARKER_NAME
            )
        else:
            from actingweb.db.dynamodb.attribute import DbAttribute

            row = DbAttribute.get_attr_strict(
                READINESS_STORE, READINESS_BUCKET, MARKER_NAME
            )
    except Exception as e:  # folds DbError: a missing table is no marker
        if _store_answered(e):
            return None
        raise
    data = row.get("data") if isinstance(row, dict) else None
    return data if isinstance(data, dict) else None


# -- the command ------------------------------------------------------------


def _names(args: argparse.Namespace, config: Any) -> tuple[list[str], str]:
    if args.properties is not None:
        names = [n.strip() for n in args.properties.split(",") if n.strip()]
        return list(dict.fromkeys(names)), "--properties"
    source = (
        "INDEXED_PROPERTIES"
        if os.getenv("INDEXED_PROPERTIES", "").strip()
        else "the library default"
    )
    return list(dict.fromkeys(config.indexed_properties)), source


def run(args: argparse.Namespace) -> int:
    from actingweb.config import Config

    database = backend()
    config = Config(
        database=database,
        unique_creator=not args.no_unique_creator,
        force_email_prop_as_creator=args.email_as_creator,
    )
    names, source = _names(args, config)
    print("Assumed configuration (the command cannot see the application's builder):")
    print(f"  indexed properties: {', '.join(names) or '(none)'} (from {source})")
    print(
        "  creator uniqueness: "
        + ("off (--no-unique-creator)" if args.no_unique_creator else "on")
    )
    print(
        "  email as creator: "
        + ("on (--email-as-creator)" if args.email_as_creator else "off")
    )

    empty: list[bool] = []

    def store_empty() -> bool:
        if not empty:
            empty.append(_store_empty(config))
        return empty[0]

    results: list[tuple[str, str, str]] = []
    unreadable = False

    def gate(name: str, decide: Any) -> None:
        nonlocal unreadable
        try:
            state, fix = decide()
        except Exception as e:  # folds DbError: exit 2
            unreadable = True
            results.append((name, "could not be read", f"{type(e).__name__}: {e}"))
            return
        results.append((name, state, fix))

    def lookup() -> tuple[str, str]:
        if not names:
            return READY, "(reverse lookup off)"
        attention = _lookup_attention(database, names)
        if not attention:
            return READY, ""
        if store_empty():
            return FIRST_START, "(empty store: the first start marks every name)"
        return "REFUSED", (
            f"{', '.join(attention)} not backfilled. Run 'actingweb-property-lookup "
            f"backfill --apply --properties {','.join(names)}'"
        )

    def uniqueness() -> tuple[str, str]:
        if args.no_unique_creator:
            return READY, "(off)"
        missing = _uniqueness_missing(config)
        if not missing:
            return READY, ""
        if store_empty():
            if database != "postgresql" and not os.getenv("AWS_DB_PREFIX"):
                return "REFUSED", (
                    f"{missing}; the store is empty, but AWS_DB_PREFIX is not "
                    "set, so the first start would refuse. Set AWS_DB_PREFIX "
                    "or run 'actingweb-unique-creators enable --apply'"
                )
            return FIRST_START, (
                f"({missing}; the store is empty: the first start enables it"
                + (
                    ", with a role that may create an index)"
                    if database == "postgresql"
                    else ")"
                )
            )
        return "REFUSED", (
            f"{missing}. Run 'actingweb-unique-creators report', then "
            "'resolve --apply' and 'enable --apply'"
        )

    def schema() -> tuple[str, str]:
        problems = _schema_problems(database)
        if not problems:
            return READY, ""
        return "REFUSED", f"{'; '.join(problems)}. Run 'alembic upgrade head'"

    def email() -> tuple[str, str]:
        if not args.email_as_creator:
            return READY, "(off)"
        marker = _email_marker(config)
        if marker and marker.get("state") == "synced":
            return READY, ""
        if store_empty():
            return FIRST_START, "(empty store: the first start writes the marker)"
        return "REFUSED", (
            "the actors were not moved to their stored email. Run "
            "'actingweb-unique-creators creator-to-email', then its --apply"
        )

    gate("reverse lookup", lookup)
    gate("creator uniqueness", uniqueness)
    gate("attribute lists", schema)
    gate("email as creator", email)

    print("Gates:")
    for name, state, fix in results:
        print(f"  {name}: {state}" + (f" -- {fix}" if fix else ""))
    if unreadable:
        print("The store could not be read for every gate; nothing is decided.")
        return 2
    return 1 if any(state == "REFUSED" for _, state, _ in results) else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description=(__doc__ or "").strip().split("\n\n")[0]
    )
    parser.add_argument(
        "--properties",
        default=None,
        help="the application's indexed property names, comma-separated "
        "(with_indexed_properties(); '' for none)",
    )
    parser.add_argument(
        "--no-unique-creator",
        action="store_true",
        help="the application calls with_unique_creator(False)",
    )
    parser.add_argument(
        "--email-as-creator",
        action="store_true",
        help="the application calls with_email_as_creator()",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "WARNING"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _build_parser().parse_args(argv)
    preflight(PROG, writing=False)
    try:
        return run(args)
    finally:
        if backend() == "postgresql":
            from actingweb.db.postgresql.connection import close_pool

            close_pool()


if __name__ == "__main__":
    sys.exit(main())
