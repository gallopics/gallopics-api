"""add photo equipe matching fields

Revision ID: 20260605_0001
Revises: 20260512_0001
Create Date: 2026-06-05
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260605_0001"
down_revision: Union[str, None] = "20260512_0001"
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


def _add_column_if_missing(columns: set[str], name: str, column: sa.Column) -> None:
    if name not in columns:
        op.add_column("photos", column)
        columns.add(name)


def _create_index_if_missing(indexes: set[str], name: str, columns: list[str]) -> None:
    if name not in indexes:
        op.create_index(name, "photos", columns)
        indexes.add(name)


def upgrade() -> None:
    columns = _columns("photos")
    if not columns:
        return

    _add_column_if_missing(
        columns,
        "equipe_class_section_id",
        sa.Column("equipe_class_section_id", sa.String(), nullable=True),
    )
    _add_column_if_missing(columns, "taken_at", sa.Column("taken_at", sa.DateTime(), nullable=True))
    _add_column_if_missing(columns, "equipe_start_id", sa.Column("equipe_start_id", sa.String(), nullable=True))
    _add_column_if_missing(columns, "equipe_rider_id", sa.Column("equipe_rider_id", sa.String(), nullable=True))
    _add_column_if_missing(columns, "equipe_horse_id", sa.Column("equipe_horse_id", sa.String(), nullable=True))
    _add_column_if_missing(columns, "matched_at", sa.Column("matched_at", sa.DateTime(), nullable=True))
    _add_column_if_missing(columns, "match_confidence", sa.Column("match_confidence", sa.String(), nullable=True))
    _add_column_if_missing(
        columns,
        "match_delta_seconds",
        sa.Column("match_delta_seconds", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(columns, "match_source", sa.Column("match_source", sa.String(), nullable=True))

    indexes = _indexes("photos")
    _create_index_if_missing(indexes, "ix_photos_equipe_class_section_id", ["equipe_class_section_id"])
    _create_index_if_missing(indexes, "ix_photos_equipe_start_id", ["equipe_start_id"])
    _create_index_if_missing(indexes, "ix_photos_equipe_rider_id", ["equipe_rider_id"])
    _create_index_if_missing(indexes, "ix_photos_equipe_horse_id", ["equipe_horse_id"])


def downgrade() -> None:
    columns = _columns("photos")
    if not columns:
        return

    indexes = _indexes("photos")
    for index_name in (
        "ix_photos_equipe_horse_id",
        "ix_photos_equipe_rider_id",
        "ix_photos_equipe_start_id",
        "ix_photos_equipe_class_section_id",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name="photos")

    for column_name in (
        "match_source",
        "match_delta_seconds",
        "match_confidence",
        "matched_at",
        "equipe_horse_id",
        "equipe_rider_id",
        "equipe_start_id",
        "taken_at",
        "equipe_class_section_id",
    ):
        if column_name in columns:
            op.drop_column("photos", column_name)
