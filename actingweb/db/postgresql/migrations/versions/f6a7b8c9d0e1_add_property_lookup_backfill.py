"""Add the property_lookup_backfill marker table.

Records, per indexed property name, that the reverse-lookup table was
backfilled for it (``kind = 'name'``), plus the indexed-name set the last
passing startup check saw (``kind = 'configured'``). The startup check
refuses a store whose configured names are not all marked, naming the
``actingweb-property-lookup`` command that makes it ready.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the marker table."""
    op.create_table(
        "property_lookup_backfill",
        sa.Column("property_name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="name"),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("property_name", "kind"),
    )


def downgrade() -> None:
    """Drop the marker table (the startup check then reports it missing)."""
    op.drop_table("property_lookup_backfill")
