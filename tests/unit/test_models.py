from app.models.enums import (
    EventStatus,
    MatchStatus,
    OrderStatus,
    PhotoStatus,
    PhotoTagType,
    PhotoVisibility,
    UserRole,
)
from app.models.event import Event, EventResult
from app.models.order import Order, PaymentTransaction
from app.models.photographer import Photo, Photographer, PhotoOrder, PhotoTag
from app.models.user import User

# --- Enum tests ---


def test_event_status_values():
    assert EventStatus.UPCOMING.value == "upcoming"
    assert EventStatus.COMPLETED.value == "completed"
    assert len(EventStatus) == 4


def test_match_status_values():
    assert MatchStatus.UNMATCHED.value == "unmatched"
    assert MatchStatus.MATCHED.value == "matched"
    assert len(MatchStatus) == 4


def test_user_role_values():
    assert UserRole.USER.value == "user"
    assert UserRole.PHOTOGRAPHER.value == "photographer"
    assert UserRole.ADMIN.value == "admin"


def test_order_status_values():
    assert OrderStatus.PENDING.value == "pending"
    assert OrderStatus.CAPTURED.value == "captured"
    assert len(OrderStatus) == 5


def test_photo_tag_type_values():
    assert PhotoTagType.RIDER.value == "rider"
    assert PhotoTagType.START_NUMBER.value == "start_number"
    assert len(PhotoTagType) == 4


# --- Model table names ---


def test_event_table_name():
    assert Event.__tablename__ == "events"


def test_event_result_table_name():
    assert EventResult.__tablename__ == "event_results"


def test_user_table_name():
    assert User.__tablename__ == "users"


def test_order_table_name():
    assert Order.__tablename__ == "orders"


def test_payment_transaction_table_name():
    assert PaymentTransaction.__tablename__ == "payment_transactions"


def test_photographer_table_name():
    assert Photographer.__tablename__ == "photographers"


def test_photo_table_name():
    assert Photo.__tablename__ == "photos"


def test_photo_tag_table_name():
    assert PhotoTag.__tablename__ == "photo_tags"


def test_photo_order_table_name():
    assert PhotoOrder.__tablename__ == "photo_orders"


# --- Column presence ---


def test_event_columns():
    cols = {c.name for c in Event.__table__.columns}
    expected = {
        "id", "tdb_id", "equipe_id", "name", "slug", "discipline", "horse_type",
        "organizer_name", "district", "venue_name", "city", "country",
        "start_date", "end_date", "status", "is_sustainable",
        "match_status", "match_score", "match_method",
        "raw_tdb_payload", "raw_equipe_payload",
        "created_at", "updated_at",
    }
    assert expected.issubset(cols)


def test_event_result_has_event_fk():
    col = EventResult.__table__.columns["event_id"]
    fk_targets = [fk.target_fullname for fk in col.foreign_keys]
    assert "events.id" in fk_targets


def test_order_has_idempotency_key():
    col = Order.__table__.columns["idempotency_key"]
    assert col.unique is True


def test_photo_tag_composite_pk():
    pk_cols = {c.name for c in PhotoTag.__table__.primary_key.columns}
    assert pk_cols == {"photo_id", "type", "value"}


def test_photo_default_visibility():
    col = Photo.__table__.columns["visibility"]
    assert col.default.arg == PhotoVisibility.DRAFT


def test_photo_default_status():
    col = Photo.__table__.columns["status"]
    assert col.default.arg == PhotoStatus.PROCESSING


def test_photo_has_class_ids():
    cols = {c.name for c in Photo.__table__.columns}
    assert {"class_id", "class_section_id"}.issubset(cols)


def test_event_default_match_status():
    col = Event.__table__.columns["match_status"]
    assert col.default.arg == MatchStatus.UNMATCHED


# --- Table creation test ---


async def test_all_tables_created(db_session):
    from sqlalchemy import inspect

    from tests.conftest import test_engine

    async with test_engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    expected_tables = {
        "events", "event_results", "users", "orders",
        "payment_transactions", "photographers", "photos",
        "photo_tags", "photo_orders",
    }
    assert expected_tables.issubset(set(table_names))
