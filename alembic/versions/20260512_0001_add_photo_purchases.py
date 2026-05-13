"""add photo purchases

Revision ID: 20260512_0001
Revises: 20260511_0002
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "20260512_0001"
down_revision: Union[str, None] = "20260511_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "photo_purchases",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("photo_id", sa.Uuid(), nullable=False),
        sa.Column("quality", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["photo_id"], ["photos.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "photo_id", "quality", name="uq_photo_purchase_order_photo_quality"),
    )
    op.create_index("ix_photo_purchases_order_id", "photo_purchases", ["order_id"])
    op.create_index("ix_photo_purchases_photo_id", "photo_purchases", ["photo_id"])
    op.create_index("ix_photo_purchases_user_id", "photo_purchases", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_photo_purchases_user_id", table_name="photo_purchases")
    op.drop_index("ix_photo_purchases_photo_id", table_name="photo_purchases")
    op.drop_index("ix_photo_purchases_order_id", table_name="photo_purchases")
    op.drop_table("photo_purchases")
