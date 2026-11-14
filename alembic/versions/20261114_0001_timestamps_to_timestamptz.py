"""Store every timestamp as timestamptz.

Before this, all datetime columns were `timestamp without time zone` with two meanings:
- created_at / updated_at were filled by Postgres now(), i.e. wall time in the DB server's zone
  (America/New_York on prod and test, whatever the local server uses in dev);
- taken_at / matched_at / equipe_last_seen_at / published_at were written by Python as UTC.
Each column is converted from the zone it was written in. Run this with the server's default
zone (Alembic's own engine; do not set PGTZ): current_setting('TimeZone') is that zone.

Rows written in the repeated hour of a summer-time change in that zone (on prod: 01:00-02:00
America/New_York on 2026-11-01) are ambiguous by 1 hour; Postgres takes the later offset.

Revision ID: 20261114_0001
Revises: 20261112_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20261114_0001"
down_revision = "20261112_0001"
branch_labels = None
depends_on = None

_UTC_COLUMNS = {"taken_at", "matched_at", "equipe_last_seen_at", "published_at"}
_SERVER_ZONE_COLUMNS = {"created_at", "updated_at"}


def _columns(data_type: str) -> list[tuple[str, str]]:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND data_type = :data_type "
            "ORDER BY table_name, column_name"
        ),
        {"data_type": data_type},
    ).all()
    unknown = sorted({column for _table, column in rows} - _UTC_COLUMNS - _SERVER_ZONE_COLUMNS)
    if unknown:
        raise RuntimeError(f"Decide which zone these columns were written in: {unknown}")
    return [(table, column) for table, column in rows]


def _zone(column: str) -> str:
    return "'UTC'" if column in _UTC_COLUMNS else "current_setting('TimeZone')"


def upgrade() -> None:
    for table, column in _columns("timestamp without time zone"):
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE timestamptz '
            f'USING "{column}" AT TIME ZONE {_zone(column)}'
        )


def downgrade() -> None:
    for table, column in _columns("timestamp with time zone"):
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE timestamp '
            f'USING "{column}" AT TIME ZONE {_zone(column)}'
        )
