"""ensure photographer event bookings table

Revision ID: 20260504_0001
Revises: 20260430_0001
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "20260504_0001"
down_revision: Union[str, None] = "20260430_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "photographer_event_bookings"

    if not inspector.has_table(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("photographer_id", sa.UUID(), nullable=False),
            sa.Column("event_id", sa.UUID(), nullable=False),
            sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
            sa.ForeignKeyConstraint(["photographer_id"], ["photographers.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "photographer_id",
                "event_id",
                name="uq_photographer_event_booking",
            ),
        )

    inspector = sa.inspect(bind)
    index_names = {index["name"] for index in inspector.get_indexes(table_name)}
    event_index_name = op.f("ix_photographer_event_bookings_event_id")
    photographer_index_name = op.f("ix_photographer_event_bookings_photographer_id")

    if event_index_name not in index_names:
        op.create_index(
            event_index_name,
            table_name,
            ["event_id"],
            unique=False,
        )
    if photographer_index_name not in index_names:
        op.create_index(
            photographer_index_name,
            table_name,
            ["photographer_id"],
            unique=False,
        )


def downgrade() -> None:
    pass
