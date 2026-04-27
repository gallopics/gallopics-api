"""Initial schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-27
"""

from alembic import op
from app.models import event, order, photographer, user  # noqa: F401
from app.models.base import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
