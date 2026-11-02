"""add stripe connect to photographers

Revision ID: 20261019_0002
Revises: 20261019_0001
Create Date: 2026-10-19
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261019_0002"
down_revision: Union[str, None] = "20261019_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FLAGS = (
    "stripe_details_submitted",
    "stripe_transfers_enabled",
    "stripe_payouts_enabled",
    "stripe_requirements_due",
)


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
    columns = _columns("photographers")
    if not columns:
        return

    if "stripe_account_id" not in columns:
        op.add_column("photographers", sa.Column("stripe_account_id", sa.String(), nullable=True))
    for flag in _FLAGS:
        if flag not in columns:
            op.add_column(
                "photographers",
                sa.Column(flag, sa.Boolean(), server_default=sa.false(), nullable=False),
            )

    if "ix_photographers_stripe_account_id" not in _indexes("photographers"):
        op.create_index(
            "ix_photographers_stripe_account_id",
            "photographers",
            ["stripe_account_id"],
            unique=True,
        )


def downgrade() -> None:
    columns = _columns("photographers")
    if not columns:
        return

    if "ix_photographers_stripe_account_id" in _indexes("photographers"):
        op.drop_index("ix_photographers_stripe_account_id", table_name="photographers")
    for column_name in (*_FLAGS, "stripe_account_id"):
        if column_name in columns:
            op.drop_column("photographers", column_name)
