"""Migrate the shared ``public`` schema once for a PostgreSQL test run.

The integration suite migrates its own per-worker prefixed schema
(``tests/integration/conftest.py`` ``setup_database``). Unit tests that touch
PostgreSQL use ``public`` and, before this helper, only found tables there when
CI's workflow had migrated it or an integration fixture had run first in the
same worker. ``ensure_postgresql_schema`` makes a unit run stand on its own.

Raw psycopg on purpose: importing ``actingweb.db.postgresql.connection`` would
build the library's pool before the integration fixture points it at a
prefixed schema.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg

# Same defaults as tests/integration/conftest.py (docker-compose.test.yml).
_DEFAULTS = {
    "PG_DB_HOST": "localhost",
    "PG_DB_PORT": "5433",
    "PG_DB_NAME": "actingweb_test",
    "PG_DB_USER": "actingweb",
    "PG_DB_PASSWORD": "testpassword",
}

# Any fixed 64-bit key; it only has to be the same in every worker.
_ADVISORY_LOCK_KEY = 0x6157_5363_6865_6D61  # "aWSchema"

MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent / "actingweb" / "db" / "postgresql"
)


def _pg_env() -> dict[str, str]:
    return {key: os.environ.get(key, default) for key, default in _DEFAULTS.items()}


def migration_env() -> dict[str, str]:
    """The subprocess environment: ``public``, whatever the shell's prefix."""
    env = os.environ.copy()
    env.update(_pg_env())
    env.pop("PG_DB_PREFIX", None)
    env["PG_DB_SCHEMA"] = "public"
    return env


def head_revisions() -> set[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(MIGRATIONS_DIR / "alembic.ini"))
    return set(ScriptDirectory.from_config(config).get_heads())


def current_revisions(cur: psycopg.Cursor[Any]) -> set[str]:
    """``public.alembic_version``; an absent table (fresh database) is empty.

    The connection is in autocommit, so the failed SELECT leaves no aborted
    transaction behind.
    """
    import psycopg

    try:
        cur.execute("SELECT version_num FROM public.alembic_version")
    except psycopg.errors.UndefinedTable:
        return set()
    return {str(row[0]) for row in cur.fetchall()}


def run_upgrade() -> None:
    try:
        subprocess.run(
            ["poetry", "run", "alembic", "upgrade", "head"],
            cwd=str(MIGRATIONS_DIR),
            env=migration_env(),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        # A public schema migrated by another branch (ahead of this one) ends
        # here with "Can't locate revision"; show alembic's own words.
        stderr = e.stderr.decode("utf-8", "replace") if e.stderr else ""
        raise RuntimeError(
            "alembic upgrade head failed for the public schema of the test "
            f"database:\n{stderr}"
        ) from e


def ensure_postgresql_schema() -> bool:
    """Bring ``public`` to the migration head. True when it ran the upgrade.

    Serialised across xdist workers with an advisory lock, so only the first
    worker migrates and the rest see head.
    """
    import psycopg

    env = _pg_env()
    conninfo = (
        f"host={env['PG_DB_HOST']} port={env['PG_DB_PORT']} "
        f"dbname={env['PG_DB_NAME']} user={env['PG_DB_USER']} "
        f"password={env['PG_DB_PASSWORD']}"
    )
    with psycopg.connect(conninfo, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        try:
            if current_revisions(cur) == head_revisions():
                return False
            run_upgrade()
            return True
        finally:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
