"""add photographer profile fields

Revision ID: 20260428_0001
Revises:
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20260428_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("photographers", sa.Column("slug", sa.String(), nullable=True))
    op.add_column("photographers", sa.Column("city", sa.String(), nullable=True))
    op.add_column("photographers", sa.Column("country", sa.String(), nullable=True))
    op.add_column("photographers", sa.Column("avatar_url", sa.String(), nullable=True))
    op.add_column("photographers", sa.Column("phone", sa.String(), nullable=True))
    op.add_column(
        "photographers",
        sa.Column("is_available_to_hire", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(
        """
        UPDATE photographers
        SET slug = trim(both '-' from regexp_replace(lower(display_name), '[^a-z0-9]+', '-', 'g')) || '-' || id::text
        WHERE slug IS NULL
        """
    )
    op.alter_column("photographers", "slug", nullable=False)
    op.create_index("ix_photographers_slug", "photographers", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_photographers_slug", table_name="photographers")
    op.drop_column("photographers", "is_available_to_hire")
    op.drop_column("photographers", "phone")
    op.drop_column("photographers", "avatar_url")
    op.drop_column("photographers", "country")
    op.drop_column("photographers", "city")
    op.drop_column("photographers", "slug")
