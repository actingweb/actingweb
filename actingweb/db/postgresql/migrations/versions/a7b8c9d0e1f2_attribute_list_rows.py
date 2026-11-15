"""Widen attributes.bucket_name and name to TEXT; index list rows by bytes.

Attribute lists (thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase
2) take the property list's row layout: item rows are named
``list:{name}-#{rank}`` (a rank key of up to 180 characters) and the
composite key ``bucket:name`` grows with them, past ``VARCHAR(255)``. TEXT
and VARCHAR share their on-disk form, so the ALTER rewrites no rows; it
does take an ACCESS EXCLUSIVE lock, bounded here by ``lock_timeout`` (retry
the upgrade if it times out behind a long transaction).

The list reads are range and prefix reads by byte order within one bucket:
``ix_attributes_list_rows`` on ``(id, bucket, name COLLATE "C")``, partial
on ``starts_with(name, 'list:')`` because ``attributes`` also holds tokens
and sessions written at a high rate. On a table that holds rows it is built
CONCURRENTLY, outside the migration's transaction, with no lock timeout: a
concurrent build waits for every transaction older than it in the database
to finish. A failed build leaves an INVALID index, which ``check_ready()``
refuses and a second ``alembic upgrade head`` rebuilds (the DROP INDEX IF
EXISTS first). An empty table (a new deployment, a test schema) is indexed
inside the migration's transaction instead: nothing to wait for.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_attributes_list_rows"


INDEX_DEFINITION = (
    "ON attributes (id, bucket, name COLLATE \"C\") WHERE starts_with(name, 'list:')"
)


def upgrade() -> None:
    """Widen the two columns, then (re)build the list-row index."""
    op.execute("SET lock_timeout = '10s'")
    op.execute(
        "ALTER TABLE attributes "
        "ALTER COLUMN bucket_name TYPE TEXT, "
        "ALTER COLUMN name TYPE TEXT"
    )
    op.execute("SET lock_timeout = 0")
    # Offline (--sql) there is no table to look at: emit the concurrent build.
    populated = op.get_context().as_sql or (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM attributes)"))
        .scalar()
    )
    if not populated:
        op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
        op.execute(f"CREATE INDEX {INDEX_NAME} {INDEX_DEFINITION}")
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
        op.execute(f"CREATE INDEX CONCURRENTLY {INDEX_NAME} {INDEX_DEFINITION}")


def downgrade() -> None:
    """Drop the index and restore VARCHAR(255).

    Fails if any row's ``bucket_name`` or ``name`` is longer than 255
    characters: an attribute list with long rank keys must be deleted (or
    compacted) before the schema goes back underneath it.
    """
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.execute("SET lock_timeout = '10s'")
    op.execute(
        "ALTER TABLE attributes "
        "ALTER COLUMN bucket_name TYPE VARCHAR(255), "
        "ALTER COLUMN name TYPE VARCHAR(255)"
    )
    op.execute("SET lock_timeout = 0")
