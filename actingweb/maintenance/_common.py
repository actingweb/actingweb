"""What every operator command does before its first read.

The library defaults ``AWS_DB_PREFIX`` to ``demo_actingweb``, and a real
populated deployment can live under that prefix. A command run from a shell
without the application's environment would read the wrong tables and report
them clean, or write to them. So each command prints the store it is about to
read (on stdout: a production ``LOG_LEVEL=WARNING`` must not hide it), and a
command in a writing mode on DynamoDB refuses when the prefix is not set
explicitly. Dry runs and PostgreSQL are not refused: a dry run changes
nothing, and PostgreSQL has no default deployment name.

The banner is built from the environment only, with the defaults the
DynamoDB models use (no ``DescribeTable``), so it costs no read.
"""

from __future__ import annotations

import os
import sys

DEFAULT_DYNAMODB_PREFIX = "demo_actingweb"
DEFAULT_DYNAMODB_REGION = "us-west-1"

#: Exit status of a refused write, as for an unreadable store.
REFUSED = 2


def backend() -> str:
    """The backend the command will use (``DATABASE_BACKEND``, as ``Config``)."""
    return os.getenv("DATABASE_BACKEND", "dynamodb") or "dynamodb"


def _prefix_is_set() -> bool:
    return bool(os.getenv("AWS_DB_PREFIX"))


def store_line(database: str) -> str:
    """One line naming the store, from the environment."""
    if database == "postgresql":
        return (
            f"backend=postgresql "
            f"host={os.getenv('PG_DB_HOST', 'localhost')} "
            f"db={os.getenv('PG_DB_NAME', 'actingweb')} "
            f"schema={os.getenv('PG_DB_SCHEMA', 'public')} "
            f"prefix={os.getenv('PG_DB_PREFIX', '') or '(none)'}"
        )
    prefix = os.getenv("AWS_DB_PREFIX", DEFAULT_DYNAMODB_PREFIX)
    return (
        f"backend={database} "
        f"prefix={prefix if prefix else '(empty)'} "
        f"endpoint={os.getenv('AWS_DB_HOST') or '(aws)'} "
        f"region={os.getenv('AWS_DEFAULT_REGION', DEFAULT_DYNAMODB_REGION)}"
    )


def print_store(prog: str, database: str) -> None:
    """Print the store (stdout), and a warning when the prefix is the
    library's default."""
    print(f"{prog}: store: {store_line(database)}", flush=True)
    if database != "postgresql" and not _prefix_is_set():
        print(
            f"{prog}: AWS_DB_PREFIX is not set; the library default "
            f"'{DEFAULT_DYNAMODB_PREFIX}' is used. If the application runs with "
            "another prefix, this reads the wrong tables. Run with the "
            "application's environment.",
            flush=True,
        )


def refuse_unprefixed_write(prog: str, database: str) -> bool:
    """Whether a write must be refused: DynamoDB with ``AWS_DB_PREFIX``
    unset or empty. Prints the refusal to stderr."""
    if database == "postgresql" or _prefix_is_set():
        return False
    resolved = os.getenv("AWS_DB_PREFIX", DEFAULT_DYNAMODB_PREFIX)
    print(
        f"{prog}: refusing to write: AWS_DB_PREFIX is "
        f"{'empty' if 'AWS_DB_PREFIX' in os.environ else 'not set'}, so the "
        f"tables resolve to the prefix '{resolved}' (the library default is "
        f"'{DEFAULT_DYNAMODB_PREFIX}'). Set AWS_DB_PREFIX to the application's "
        "prefix explicitly, even when it is the default, and run again. "
        "Nothing was read or written.",
        file=sys.stderr,
        flush=True,
    )
    return True


def preflight(prog: str, *, writing: bool, database: str | None = None) -> int | None:
    """Print the store; return :data:`REFUSED` when a write must not run,
    else ``None``. Called by every command before its first read."""
    database = database or backend()
    print_store(prog, database)
    if writing and refuse_unprefixed_write(prog, database):
        return REFUSED
    return None
