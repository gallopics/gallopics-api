import uuid
from datetime import date

import pytest

from app.models.enums import EventStatus, MatchStatus
from app.models.event import Event
from app.services.matching_service import MatchingService
from tests.factories import make_event


@pytest.fixture
def service(db_session):
    return MatchingService(db_session)


async def _seed_event(db_session, **overrides) -> Event:
    data = make_event(**overrides)
    event = Event(**data)
    db_session.add(event)
    await db_session.flush()
    return event


# --- Name normalization ---

def test_normalize_name_lowercase():
    ms = MatchingService.__new__(MatchingService)
    assert ms._normalize_name("STOCKHOLM OPEN") == "stockholm open"


def test_normalize_name_strips_whitespace():
    ms = MatchingService.__new__(MatchingService)
    assert ms._normalize_name("  Stockholm Open  ") == "stockholm open"


def test_normalize_name_removes_prefix():
    ms = MatchingService.__new__(MatchingService)
    assert ms._normalize_name("Tävling: Grand Prix") == "grand prix"


# --- Similarity scoring ---

def test_name_similarity_identical():
    ms = MatchingService.__new__(MatchingService)
    assert ms._name_similarity("Stockholm Open", "Stockholm Open") == 1.0


def test_name_similarity_very_similar():
    ms = MatchingService.__new__(MatchingService)
    score = ms._name_similarity("Gothenburg Horse Show", "Horse Show Gothenburg")
    assert score >= 0.85


def test_name_similarity_partial():
    ms = MatchingService.__new__(MatchingService)
    score = ms._name_similarity("Gothenburg Spring", "Gothenburg Spring Championship")
    assert score >= 0.70


def test_name_similarity_different():
    ms = MatchingService.__new__(MatchingService)
    score = ms._name_similarity("Stockholm Dressage", "Malmö Jumping")
    assert score < 0.70


def test_organizer_similarity():
    ms = MatchingService.__new__(MatchingService)
    assert ms._organizer_similarity("Swedish Federation", "Swedish Federation") == 1.0
    assert ms._organizer_similarity(None, "Something") == 0.0


def test_venue_similarity():
    ms = MatchingService.__new__(MatchingService)
    assert ms._venue_similarity("Friends Arena", "Friends Arena") == 1.0
    assert ms._venue_similarity("Friends Arena", None) == 0.0


# --- Matching priority chain ---

async def test_exact_tdb_id_match(service, db_session):
    event = await _seed_event(db_session, tdb_id="tdb-100", name="Some Event")
    meeting = {"tdb_id": "tdb-100", "name": "Different Name", "start_date": date(2026, 6, 15)}
    candidate = await service.find_match(meeting)
    assert candidate is not None
    assert candidate.score == 1.0
    assert candidate.method == "exact_tdb_id"
    assert candidate.event_id == event.id


async def test_date_plus_strong_name_match(service, db_session):
    await _seed_event(
        db_session, name="Stockholm Dressage Championship", start_date=date(2026, 6, 15)
    )
    meeting = {
        "name": "Stockholm Dressage Championship",
        "start_date": date(2026, 6, 15),
    }
    candidate = await service.find_match(meeting)
    assert candidate is not None
    assert candidate.score == 0.85
    assert candidate.method == "date_strong_name"


async def test_date_plus_partial_name_match(service, db_session):
    await _seed_event(
        db_session, name="Gothenburg Spring Event", start_date=date(2026, 3, 10)
    )
    meeting = {
        "name": "Gothenburg Spring Championship Event",
        "start_date": date(2026, 3, 10),
    }
    candidate = await service.find_match(meeting)
    assert candidate is not None
    assert candidate.score >= 0.75


async def test_below_threshold_rejected(service, db_session):
    await _seed_event(db_session, name="Stockholm Dressage", start_date=date(2026, 6, 15))
    meeting = {"name": "Malmö Jumping", "start_date": date(2026, 6, 15)}
    candidate = await service.find_match(meeting)
    assert candidate is None


async def test_no_date_overlap_no_match(service, db_session):
    await _seed_event(db_session, name="Stockholm Open", start_date=date(2026, 6, 15))
    meeting = {"name": "Stockholm Open", "start_date": date(2026, 12, 1)}
    candidate = await service.find_match(meeting)
    assert candidate is None


async def test_best_match_wins(service, db_session):
    await _seed_event(db_session, name="Stockholm Spring Open", start_date=date(2026, 6, 15))
    e2 = await _seed_event(
        db_session, name="Stockholm Grand Championship", start_date=date(2026, 6, 15)
    )
    meeting = {"name": "Stockholm Grand Championship", "start_date": date(2026, 6, 15)}
    candidate = await service.find_match(meeting)
    assert candidate is not None
    assert candidate.event_id == e2.id


# --- Apply / unmatch / manual ---

async def test_apply_match_updates_event(service, db_session):
    event = await _seed_event(db_session, name="Test")
    updated = await service.apply_match(event.id, "equipe-1", 0.85, "date_strong_name", {"raw": True})
    assert updated.equipe_id == "equipe-1"
    assert updated.match_status == MatchStatus.MATCHED
    assert updated.match_score == 0.85
    assert updated.match_method == "date_strong_name"


async def test_manual_match(service, db_session):
    event = await _seed_event(db_session, name="Test")
    updated = await service.manual_match(event.id, "equipe-manual")
    assert updated.match_status == MatchStatus.MANUAL
    assert updated.match_score == 1.0
    assert updated.equipe_id == "equipe-manual"


async def test_unmatch_resets_fields(service, db_session):
    event = await _seed_event(db_session, name="Test")
    await service.apply_match(event.id, "equipe-1", 0.85, "test", {})
    unmatched = await service.unmatch(event.id)
    assert unmatched.equipe_id is None
    assert unmatched.match_status == MatchStatus.UNMATCHED
    assert unmatched.match_score is None


async def test_get_unmatched_events(service, db_session):
    await _seed_event(db_session, name="Unmatched One")
    e2 = await _seed_event(db_session, name="Matched One")
    await service.apply_match(e2.id, "eq-1", 1.0, "exact", {})

    unmatched = await service.get_unmatched_events()
    assert len(unmatched) == 1
    assert unmatched[0].name == "Unmatched One"


async def test_run_matching_batch(service, db_session):
    await _seed_event(
        db_session, tdb_id="tdb-batch-1", name="Event A", start_date=date(2026, 6, 15)
    )
    await _seed_event(db_session, name="Event B", start_date=date(2026, 7, 1))

    meetings = [
        {"tdb_id": "tdb-batch-1", "equipe_id": "eq-1", "name": "Event A", "start_date": date(2026, 6, 15)},
        {"equipe_id": "eq-2", "name": "Totally Different", "start_date": date(2026, 9, 1)},
    ]
    result = await service.run_matching_batch(meetings)
    assert result["matched"] == 1
    assert result["unmatched"] == 1
