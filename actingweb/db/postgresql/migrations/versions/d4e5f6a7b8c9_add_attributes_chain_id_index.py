"""Add partial expression index on attributes.data->>'chain_id'.

Backs O(chain) refresh-token family revocation: ``revoke_token_chain`` deletes
every SPA token sharing a ``chain_id`` (RFC 6819 token-family revocation). Without
this index the delete scans every token in the shared OAUTH2_SYSTEM_ACTOR
partition; with it, the delete touches only the ~handful of rows in the chain.
Partial (``WHERE data->>'chain_id' IS NOT NULL``) so it covers only token rows and
stays small relative to the table.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-21

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the partial expression index on (data->>'chain_id')."""
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_attributes_chain_id "
        "ON attributes ((data ->> 'chain_id')) "
        "WHERE (data ->> 'chain_id') IS NOT NULL"
    )


def downgrade() -> None:
    """Drop the chain_id expression index."""
    op.execute("DROP INDEX IF EXISTS idx_attributes_chain_id")
