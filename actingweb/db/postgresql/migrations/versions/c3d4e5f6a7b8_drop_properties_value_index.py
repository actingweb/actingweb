"""Drop idx_properties_value B-tree index.

The B-tree index on properties.value blocks storage of large values
(embeddings, JSON blobs) that exceed the B-tree page size limit (~2700 bytes).
This index was planned for removal since the property_lookup table provides
targeted reverse-index lookups for the few properties that need value-based search.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-17

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the B-tree index on properties.value."""
    op.drop_index("idx_properties_value", table_name="properties")


def downgrade() -> None:
    """Re-create the B-tree index on properties.value."""
    op.create_index("idx_properties_value", "properties", ["value"], unique=False)
