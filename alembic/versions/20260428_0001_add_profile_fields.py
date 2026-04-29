"""baseline schema

Revision ID: 20260428_0001
Revises:
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa

from app.models import *  # noqa: F401, F403
from app.models.base import Base
from app.models.enums import EventStatus, MatchStatus


revision = "20260428_0001"
down_revision = None
branch_labels = None
depends_on = None


event_status = sa.Enum(EventStatus, name="eventstatus")
match_status = sa.Enum(MatchStatus, name="matchstatus")


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    event_status.create(bind, checkfirst=True)
    match_status.create(bind, checkfirst=True)

    _add_column_if_missing("events", sa.Column("tdb_id", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("equipe_id", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("discipline", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("horse_type", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("organizer_name", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("district", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("venue_name", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("city", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("country", sa.String(), nullable=False, server_default="SE"))
    _add_column_if_missing("events", sa.Column("end_date", sa.Date(), nullable=True))
    _add_column_if_missing("events", sa.Column("status", event_status, nullable=False, server_default="UPCOMING"))
    _add_column_if_missing("events", sa.Column("is_sustainable", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing(
        "events",
        sa.Column("match_status", match_status, nullable=False, server_default="UNMATCHED"),
    )
    _add_column_if_missing("events", sa.Column("match_score", sa.Float(), nullable=True))
    _add_column_if_missing("events", sa.Column("match_method", sa.String(), nullable=True))
    _add_column_if_missing("events", sa.Column("raw_tdb_payload", sa.JSON(), nullable=True))
    _add_column_if_missing("events", sa.Column("raw_equipe_payload", sa.JSON(), nullable=True))

    op.alter_column("events", "country", server_default=None)
    op.alter_column("events", "status", server_default=None)
    op.alter_column("events", "is_sustainable", server_default=None)
    op.alter_column("events", "match_status", server_default=None)

    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_events_tdb_id ON events (tdb_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_events_equipe_id ON events (equipe_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_events_slug ON events (slug)")

    photographer_columns = _columns("photographers")
    if "slug" not in photographer_columns:
        op.add_column("photographers", sa.Column("slug", sa.String(), nullable=True))
        op.execute(
            """
            UPDATE photographers
            SET slug = trim(both '-' from regexp_replace(lower(display_name), '[^a-z0-9]+', '-', 'g')) || '-' || id::text
            WHERE slug IS NULL
            """
        )
        op.alter_column("photographers", "slug", nullable=False)
    _add_column_if_missing("photographers", sa.Column("city", sa.String(), nullable=True))
    _add_column_if_missing("photographers", sa.Column("country", sa.String(), nullable=True))
    _add_column_if_missing("photographers", sa.Column("avatar_url", sa.String(), nullable=True))
    _add_column_if_missing("photographers", sa.Column("phone", sa.String(), nullable=True))
    _add_column_if_missing(
        "photographers",
        sa.Column("is_available_to_hire", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_photographers_slug ON photographers (slug)")


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
