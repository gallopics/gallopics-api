"""add stripe checkout to orders

Revision ID: 20261019_0001
Revises: 20260608_0001
Create Date: 2026-10-19
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261019_0001"
down_revision: Union[str, None] = "20260608_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    columns = _columns("orders")
    if not columns:
        return

    if "customer_email" not in columns:
        op.add_column("orders", sa.Column("customer_email", sa.String(), nullable=True))
    if "line_items" not in columns:
        op.add_column("orders", sa.Column("line_items", sa.JSON(), nullable=True))
    if "stripe_checkout_session_id" not in columns:
        op.add_column("orders", sa.Column("stripe_checkout_session_id", sa.String(), nullable=True))
    if "stripe_payment_intent_id" not in columns:
        op.add_column("orders", sa.Column("stripe_payment_intent_id", sa.String(), nullable=True))

    indexes = _indexes("orders")
    if "ix_orders_stripe_checkout_session_id" not in indexes:
        op.create_index(
            "ix_orders_stripe_checkout_session_id",
            "orders",
            ["stripe_checkout_session_id"],
            unique=True,
        )
    if "ix_orders_stripe_payment_intent_id" not in indexes:
        op.create_index(
            "ix_orders_stripe_payment_intent_id",
            "orders",
            ["stripe_payment_intent_id"],
        )


def downgrade() -> None:
    columns = _columns("orders")
    if not columns:
        return

    indexes = _indexes("orders")
    for index_name in ("ix_orders_stripe_payment_intent_id", "ix_orders_stripe_checkout_session_id"):
        if index_name in indexes:
            op.drop_index(index_name, table_name="orders")

    for column_name in (
        "stripe_payment_intent_id",
        "stripe_checkout_session_id",
        "line_items",
        "customer_email",
    ):
        if column_name in columns:
            op.drop_column("orders", column_name)
