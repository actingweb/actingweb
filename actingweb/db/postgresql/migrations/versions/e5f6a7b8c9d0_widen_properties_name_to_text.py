"""Widen properties.name from VARCHAR(255) to TEXT.

Removes the 255-byte cap on property names. The v2 fractional-rank-key
list-property storage format (thoughts/plans/2026-08-08-property-list-index-
integrity.md, Phase 4) names item rows "list:{list_name}-#{rank}", where
rank is a generated fractional-indexing key that can grow with repeated
insert-between operations before compact() rebalances it back down (capped
at 180 chars, well past VARCHAR(255) once combined with a long list name).
Metadata-only ALTER on PostgreSQL -- TEXT and VARCHAR(255) share the same
on-disk representation, so this does not rewrite the table.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-08

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen properties.name to TEXT (metadata-only, no table rewrite)."""
    op.execute("ALTER TABLE properties ALTER COLUMN name TYPE TEXT")


def downgrade() -> None:
    """Restore properties.name to VARCHAR(255).

    Fails if any row has a name longer than 255 chars -- expected: a v2
    list with long rank keys must be compacted (or migrated back to v1)
    before downgrading the schema underneath it.
    """
    op.execute("ALTER TABLE properties ALTER COLUMN name TYPE VARCHAR(255)")
