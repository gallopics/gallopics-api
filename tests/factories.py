import uuid
from datetime import date

from app.models.enums import EventStatus, MatchStatus, OrderStatus, UserRole


def make_event(**overrides) -> dict:
    defaults = {
        "name": "Test Event",
        "slug": f"test-event-{uuid.uuid4().hex[:8]}",
        "start_date": date(2026, 6, 15),
        "status": EventStatus.UPCOMING,
        "country": "SE",
        "is_sustainable": False,
        "match_status": MatchStatus.UNMATCHED,
    }
    return {**defaults, **overrides}


def make_user(**overrides) -> dict:
    defaults = {
        "clerk_user_id": f"clerk_{uuid.uuid4().hex[:8]}",
        "email": "test@example.com",
        "role": UserRole.USER,
    }
    return {**defaults, **overrides}


def make_order(**overrides) -> dict:
    defaults = {
        "amount": 5000,
        "currency": "SEK",
        "status": OrderStatus.PENDING,
    }
    return {**defaults, **overrides}
