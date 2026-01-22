"""Add subscription_suspensions table.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create subscription_suspensions table."""
    op.create_table(
        'subscription_suspensions',
        sa.Column('id', sa.String(255), nullable=False),
        sa.Column('target', sa.String(255), nullable=False),
        sa.Column('subtarget', sa.String(255), nullable=False, server_default=''),
        sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', 'target', 'subtarget')
    )


def downgrade() -> None:
    """Drop subscription_suspensions table."""
    op.drop_table('subscription_suspensions')
