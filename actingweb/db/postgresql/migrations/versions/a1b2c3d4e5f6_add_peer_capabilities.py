"""Add peer capability tracking fields to trusts table.

Revision ID: a1b2c3d4e5f6
Revises: 70d60420526
Create Date: 2026-01-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "70d60420526"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add peer capability tracking fields to trusts table."""
    op.add_column("trusts", sa.Column("aw_supported", sa.Text(), nullable=True))
    op.add_column("trusts", sa.Column("aw_version", sa.String(50), nullable=True))
    op.add_column(
        "trusts",
        sa.Column("capabilities_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove peer capability tracking fields from trusts table."""
    op.drop_column("trusts", "capabilities_fetched_at")
    op.drop_column("trusts", "aw_version")
    op.drop_column("trusts", "aw_supported")
