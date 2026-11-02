"""add photographers' own photo folders

Revision ID: 20261102_0001
Revises: 20261101_0001
Create Date: 2026-11-02
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261102_0001"
down_revision: Union[str, None] = "20261101_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _columns("photo_folders"):
        op.create_table(
            "photo_folders",
            sa.Column("photographer_id", sa.Uuid(), nullable=False),
            sa.Column("event_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
            sa.ForeignKeyConstraint(["photographer_id"], ["photographers.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_photo_folders_event_id", "photo_folders", ["event_id"])
        op.create_index("ix_photo_folders_photographer_id", "photo_folders", ["photographer_id"])

    # Existing photos get no folder, i.e. Uncategorised
    photo_columns = _columns("photos")
    if photo_columns and "folder_id" not in photo_columns:
        op.add_column("photos", sa.Column("folder_id", sa.Uuid(), nullable=True))
        op.create_index("ix_photos_folder_id", "photos", ["folder_id"])
        op.create_foreign_key(
            "fk_photos_folder_id_photo_folders",
            "photos",
            "photo_folders",
            ["folder_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if "folder_id" in _columns("photos"):
        op.drop_constraint("fk_photos_folder_id_photo_folders", "photos", type_="foreignkey")
        op.drop_index("ix_photos_folder_id", table_name="photos")
        op.drop_column("photos", "folder_id")
    if _columns("photo_folders"):
        op.drop_index("ix_photo_folders_photographer_id", table_name="photo_folders")
        op.drop_index("ix_photo_folders_event_id", table_name="photo_folders")
        op.drop_table("photo_folders")
