import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def test_linked_price_migration_upgrade_and_downgrade():
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set MIGRATION_TEST_DATABASE_URL to a disposable local test database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.endswith("_test")
    engine = create_engine(url)
    schema = f"migration_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location("linked_prices_migration", Path(__file__).parents[2] / "alembic/versions/20261112_0001_add_linked_photographer_prices.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text("CREATE TABLE photographers (id integer PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE photos (id serial PRIMARY KEY, price_web integer NOT NULL DEFAULT 49900, price_high integer NOT NULL DEFAULT 99900, price_commercial integer NOT NULL DEFAULT 150000)"))
            conn.execute(text("INSERT INTO photos (price_web,price_high,price_commercial) VALUES (49900,99900,150000),(7900,99900,200000)"))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            assert conn.execute(text("SELECT price_web,price_high,price_commercial FROM photos ORDER BY id")).all() == [(None,None,None),(7900,None,200000)]
            columns = inspect(conn).get_columns("photos", schema=schema)
            assert all(column["nullable"] and column["default"] is None for column in columns if column["name"].startswith("price_"))
            assert {column["name"] for column in inspect(conn).get_columns("photographers",schema=schema)} == {"id","default_price_web","default_price_high","default_price_commercial"}
            migration.downgrade()
            assert conn.execute(text("SELECT price_web,price_high,price_commercial FROM photos ORDER BY id")).all() == [(49900,99900,150000),(7900,99900,200000)]
            assert {column["name"] for column in inspect(conn).get_columns("photographers",schema=schema)} == {"id"}
            assert all(not column["nullable"] and column["default"] is not None for column in inspect(conn).get_columns("photos",schema=schema) if column["name"].startswith("price_"))
            migration.upgrade()
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()
