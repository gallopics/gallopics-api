"""Link unset photo prices to photographer defaults.

Revision ID: 20261112_0001
Revises: 20261102_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20261112_0001"
down_revision = "20261102_0001"
branch_labels = None
depends_on = None

_DEFAULTS = {"web": 49_900, "high": 99_900, "commercial": 150_000}


def upgrade() -> None:
    for tier, default in _DEFAULTS.items():
        op.add_column("photographers", sa.Column(f"default_price_{tier}", sa.Integer(), nullable=True))
        op.alter_column("photos", f"price_{tier}", existing_type=sa.Integer(), nullable=True, server_default=None)
        op.execute(sa.text(f"UPDATE photos SET price_{tier} = NULL WHERE price_{tier} = :default").bindparams(default=default))


def downgrade() -> None:
    for tier, default in _DEFAULTS.items():
        op.execute(sa.text(f"UPDATE photos SET price_{tier} = :default WHERE price_{tier} IS NULL").bindparams(default=default))
        op.alter_column("photos", f"price_{tier}", existing_type=sa.Integer(), nullable=False, server_default=str(default))
        op.drop_column("photographers", f"default_price_{tier}")
