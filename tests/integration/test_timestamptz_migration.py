import importlib.util
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _load_migration():
    path = Path(__file__).parents[2] / "alembic/versions/20261114_0001_timestamps_to_timestamptz.py"
    spec = importlib.util.spec_from_file_location("timestamptz_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_timestamptz_migration_converts_each_column_from_its_own_zone():
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set MIGRATION_TEST_DATABASE_URL to a disposable local test database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.endswith("_test")
    engine = create_engine(url)
    schema = f"migration_{uuid.uuid4().hex}"
    migration = _load_migration()
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            # Same situation as prod: the server's zone is New York
            conn.execute(text("SET LOCAL TimeZone TO 'America/New_York'"))
            conn.execute(
                text(
                    "CREATE TABLE photos (id integer PRIMARY KEY, created_at timestamp NOT NULL DEFAULT now(), "
                    "updated_at timestamp NOT NULL DEFAULT now(), taken_at timestamp, matched_at timestamp)"
                )
            )
            # 15:56 New York wall time and 20:56 UTC are the same moment
            conn.execute(
                text(
                    "INSERT INTO photos VALUES "
                    "(1, '2026-11-09 15:56:00', '2026-11-09 15:56:00', '2026-11-09 20:56:00', NULL)"
                )
            )
            migration.op = Operations(MigrationContext.configure(conn))

            migration.upgrade()

            moment = datetime(2026, 11, 9, 20, 56, tzinfo=timezone.utc)
            row = conn.execute(text("SELECT created_at, updated_at, taken_at, matched_at FROM photos")).one()
            assert row == (moment, moment, moment, None)
            assert conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND data_type = 'timestamp with time zone'"
                )
            ).scalar() == 4
            # The default still works
            conn.execute(text("INSERT INTO photos (id) VALUES (2)"))

            migration.downgrade()

            row = conn.execute(text("SELECT created_at, updated_at, taken_at FROM photos WHERE id = 1")).one()
            assert row == (datetime(2026, 11, 9, 15, 56), datetime(2026, 11, 9, 15, 56), datetime(2026, 11, 9, 20, 56))
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()


def test_timestamptz_migration_refuses_unknown_columns():
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set MIGRATION_TEST_DATABASE_URL to a disposable local test database")
    engine = create_engine(url)
    schema = f"migration_{uuid.uuid4().hex}"
    migration = _load_migration()
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text("CREATE TABLE things (id integer PRIMARY KEY, expires_at timestamp)"))
            migration.op = Operations(MigrationContext.configure(conn))
            with pytest.raises(RuntimeError, match="expires_at"):
                migration.upgrade()
            trans.rollback()
    finally:
        engine.dispose()
