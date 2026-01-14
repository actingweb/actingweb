"""Add property_lookup table for reverse lookups

Revision ID: 70d60420526
Revises: 3307e3616c5e
Create Date: 2026-01-14 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '70d60420526'
down_revision: str | Sequence[str] | None = '3307e3616c5e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create property_lookup table for reverse lookups without size limits."""
    op.create_table(
        'property_lookup',
        sa.Column('property_name', sa.String(length=255), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('actor_id', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ['actor_id'],
            ['actors.id'],
            name='fk_property_lookup_actor',
            ondelete='CASCADE',
            deferrable=True,
            initially='DEFERRED'
        ),
        sa.PrimaryKeyConstraint('property_name', 'value')
    )

    # Index for actor_id lookups (for cleanup on actor delete)
    op.create_index(
        'idx_property_lookup_actor_id',
        'property_lookup',
        ['actor_id'],
        unique=False
    )


def downgrade() -> None:
    """Drop property_lookup table."""
    op.drop_index('idx_property_lookup_actor_id', table_name='property_lookup')
    op.drop_table('property_lookup')
