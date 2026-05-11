"""add photographer highlights

Revision ID: 20260511_0002
Revises: 20260511_0001
Create Date: 2026-05-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

# revision identifiers, used by Alembic.
revision = '20260511_0002'
down_revision = '20260511_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add highlights column to photographers table
    op.add_column('photographers', sa.Column('highlights', sa.ARRAY(sa.String()), nullable=True, server_default='[]'))


def downgrade() -> None:
    op.drop_column('photographers', 'highlights')
