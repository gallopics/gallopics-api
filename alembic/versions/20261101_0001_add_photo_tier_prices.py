"""add per-tier prices to photos

Revision ID: 20261101_0001
Revises: 20261019_0003
Create Date: 2026-11-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261101_0001"
down_revision: Union[str, None] = "20261019_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default price per tier in öre; existing photos get these
_PRICE_COLUMNS = {
    "price_web": 49_900,
    "price_high": 99_900,
    "price_commercial": 150_000,
}


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    columns = _columns("photos")
    if not columns:
        return

    for name, default in _PRICE_COLUMNS.items():
        if name not in columns:
            op.add_column(
                "photos",
                sa.Column(name, sa.Integer(), nullable=False, server_default=str(default)),
            )


def downgrade() -> None:
    columns = _columns("photos")
    for name in _PRICE_COLUMNS:
        if name in columns:
            op.drop_column("photos", name)
