"""add event equipe active tracking

Revision ID: 20260608_0001
Revises: 20260605_0001
Create Date: 2026-06-08
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260608_0001"
down_revision: Union[str, None] = "20260605_0001"
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
    columns = _columns("events")
    if not columns:
        return

    if "is_active_from_equipe" not in columns:
        op.add_column(
            "events",
            sa.Column(
                "is_active_from_equipe",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            ),
        )
    if "equipe_last_seen_at" not in columns:
        op.add_column("events", sa.Column("equipe_last_seen_at", sa.DateTime(), nullable=True))

    indexes = _indexes("events")
    if "ix_events_is_active_from_equipe" not in indexes:
        op.create_index(
            "ix_events_is_active_from_equipe",
            "events",
            ["is_active_from_equipe"],
        )


def downgrade() -> None:
    columns = _columns("events")
    if not columns:
        return

    indexes = _indexes("events")
    if "ix_events_is_active_from_equipe" in indexes:
        op.drop_index("ix_events_is_active_from_equipe", table_name="events")

    for column_name in ("equipe_last_seen_at", "is_active_from_equipe"):
        if column_name in columns:
            op.drop_column("events", column_name)
