"""add photo external class fields

Revision ID: 20260511_0001
Revises: 20260510_0001
Create Date: 2026-05-11
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "20260511_0001"
down_revision: Union[str, None] = "20260510_0001"
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
    columns = _columns("photos")
    if not columns:
        return

    if "event_class_id" not in columns:
        op.add_column("photos", sa.Column("event_class_id", sa.String(), nullable=True))
    if "class_name" not in columns:
        op.add_column("photos", sa.Column("class_name", sa.String(), nullable=True))

    indexes = _indexes("photos")
    if "ix_photos_event_class_id" not in indexes:
        op.create_index("ix_photos_event_class_id", "photos", ["event_class_id"])


def downgrade() -> None:
    columns = _columns("photos")
    if not columns:
        return

    indexes = _indexes("photos")
    if "ix_photos_event_class_id" in indexes:
        op.drop_index("ix_photos_event_class_id", table_name="photos")

    if "class_name" in columns:
        op.drop_column("photos", "class_name")
    if "event_class_id" in columns:
        op.drop_column("photos", "event_class_id")
