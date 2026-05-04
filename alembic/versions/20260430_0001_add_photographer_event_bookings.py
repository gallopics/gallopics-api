"""add photographer event bookings

Revision ID: 20260430_0001
Revises: 20260428_0001
Create Date: 2026-04-30
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260430_0001"
down_revision: Union[str, None] = "20260428_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "photographer_event_bookings",
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
    op.create_index(
        op.f("ix_photographer_event_bookings_event_id"),
        "photographer_event_bookings",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_photographer_event_bookings_photographer_id"),
        "photographer_event_bookings",
        ["photographer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_photographer_event_bookings_photographer_id"),
        table_name="photographer_event_bookings",
    )
    op.drop_index(
        op.f("ix_photographer_event_bookings_event_id"),
        table_name="photographer_event_bookings",
    )
    op.drop_table("photographer_event_bookings")
