import uuid
from datetime import date, datetime

from app.models.enums import (
    EventStatus,
    MatchStatus,
    OrderStatus,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PhotoStatus,
    PhotoTagType,
    PhotoVisibility,
)
from app.schemas.event import EventFilters, EventResponse, EventResultResponse
from app.schemas.order import OrderResponse
from app.schemas.photographer import PhotoResponse
from app.schemas.user import UserResponse


class _FakeEvent:
    id = uuid.uuid4()
    tdb_id = "tdb-123"
    equipe_id = None
    name = "Test Event"
    slug = "test-event-2026"
    discipline = "dressage"
    horse_type = None
    organizer_name = "Club A"
    district = None
    venue_name = None
    city = "Stockholm"
    country = "SE"
    start_date = date(2026, 6, 15)
    end_date = None
    status = EventStatus.UPCOMING
    is_sustainable = False
    match_status = MatchStatus.UNMATCHED
    match_score = None
    created_at = datetime(2026, 1, 1)
    updated_at = datetime(2026, 1, 1)


class _FakeUser:
    id = uuid.uuid4()
    clerk_user_id = "clerk_123"
    email = "test@example.com"
    role = "user"
    created_at = datetime(2026, 1, 1)
    updated_at = datetime(2026, 1, 1)


class _FakeTransaction:
    id = uuid.uuid4()
    order_id = uuid.uuid4()
    type = PaymentTransactionType.AUTHORIZATION
    status = PaymentTransactionStatus.SUCCESS
    created_at = datetime(2026, 1, 1)


class _FakeOrder:
    id = uuid.uuid4()
    user_id = uuid.uuid4()
    status = OrderStatus.PENDING
    amount = 5000
    currency = "SEK"
    klarna_order_id = None
    transactions = [_FakeTransaction()]
    created_at = datetime(2026, 1, 1)
    updated_at = datetime(2026, 1, 1)


class _FakeTag:
    type = PhotoTagType.RIDER
    value = "Anna"


class _FakePhoto:
    id = uuid.uuid4()
    event_id = uuid.uuid4()
    class_id = uuid.uuid4()
    class_section_id = class_id
    photographer_id = uuid.uuid4()
    price = 10000
    currency = "SEK"
    status = PhotoStatus.READY
    visibility = PhotoVisibility.PUBLISHED
    tags = [_FakeTag()]
    created_at = datetime(2026, 1, 1)
    updated_at = datetime(2026, 1, 1)


def test_event_response_from_orm():
    resp = EventResponse.model_validate(_FakeEvent(), from_attributes=True)
    assert resp.name == "Test Event"
    assert resp.slug == "test-event-2026"
    assert resp.status == EventStatus.UPCOMING


def test_event_filters_defaults():
    f = EventFilters()
    assert f.date_from is None
    assert f.date_to is None
    assert f.discipline is None
    assert f.search is None


def test_event_filters_with_values():
    f = EventFilters(date_from=date(2026, 1, 1), discipline="dressage")
    assert f.date_from == date(2026, 1, 1)
    assert f.discipline == "dressage"


def test_user_response_from_orm():
    resp = UserResponse.model_validate(_FakeUser(), from_attributes=True)
    assert resp.clerk_user_id == "clerk_123"
    assert resp.email == "test@example.com"


def test_order_response_nests_transactions():
    resp = OrderResponse.model_validate(_FakeOrder(), from_attributes=True)
    assert len(resp.transactions) == 1
    assert resp.transactions[0].type == PaymentTransactionType.AUTHORIZATION


def test_photo_response_includes_tags():
    resp = PhotoResponse.model_validate(_FakePhoto(), from_attributes=True)
    assert len(resp.tags) == 1
    assert resp.tags[0].type == PhotoTagType.RIDER
    assert resp.tags[0].value == "Anna"
    assert resp.class_id == _FakePhoto.class_id
    assert resp.class_section_id == _FakePhoto.class_section_id


def test_event_result_response_from_orm():
    class _FakeResult:
        id = uuid.uuid4()
        event_id = uuid.uuid4()
        class_name = "Class A"
        participant_name = "John"
        horse_name = "Thunder"
        ranking = 1
        score = "72.5"
        published_at = datetime(2026, 6, 15)

    resp = EventResultResponse.model_validate(_FakeResult(), from_attributes=True)
    assert resp.participant_name == "John"
    assert resp.ranking == 1
