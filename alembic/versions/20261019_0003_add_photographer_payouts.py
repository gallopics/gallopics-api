"""add photographer payouts to photo purchases

Revision ID: 20261019_0003
Revises: 20261019_0002
Create Date: 2026-10-19
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261019_0003"
down_revision: Union[str, None] = "20261019_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PURCHASE_COLUMNS = {
    "photographer_amount": sa.Integer(),
    "platform_fee": sa.Integer(),
    "payout_status": sa.String(),
    "stripe_transfer_id": sa.String(),
}
_PURCHASE_INDEXES = {
    "ix_photo_purchases_photographer_id": "photographer_id",
    "ix_photo_purchases_payout_status": "payout_status",
    "ix_photo_purchases_stripe_transfer_id": "stripe_transfer_id",
}


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    order_columns = _columns("orders")
    if order_columns and "stripe_charge_id" not in order_columns:
        op.add_column("orders", sa.Column("stripe_charge_id", sa.String(), nullable=True))

    columns = _columns("photo_purchases")
    if not columns:
        return

    if "photographer_id" not in columns:
        op.add_column(
            "photo_purchases",
            sa.Column("photographer_id", sa.Uuid(), sa.ForeignKey("photographers.id"), nullable=True),
        )
    for name, type_ in _PURCHASE_COLUMNS.items():
        if name not in columns:
            op.add_column("photo_purchases", sa.Column(name, type_, nullable=True))

    indexes = _indexes("photo_purchases")
    for index_name, column in _PURCHASE_INDEXES.items():
        if index_name not in indexes:
            op.create_index(index_name, "photo_purchases", [column])


def downgrade() -> None:
    columns = _columns("photo_purchases")
    if columns:
        indexes = _indexes("photo_purchases")
        for index_name in _PURCHASE_INDEXES:
            if index_name in indexes:
                op.drop_index(index_name, table_name="photo_purchases")
        for name in (*_PURCHASE_COLUMNS, "photographer_id"):
            if name in columns:
                op.drop_column("photo_purchases", name)

    if "stripe_charge_id" in _columns("orders"):
        op.drop_column("orders", "stripe_charge_id")
