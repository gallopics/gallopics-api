from app.integrations.tdb.normalizer import normalize_tdb_event
from app.models.enums import EventStatus


def _raw_event(**overrides):
    base = {
        "id": "tdb-001",
        "name": "Stockholm Dressage Championship",
        "organizer": "Swedish Equestrian Federation",
        "discipline": "dressage",
        "horse_type": "warmblood",
        "district": "Stockholm",
        "venue": "Friends Arena",
        "city": "Stockholm",
        "country": "SE",
        "start_date": "2026-06-15",
        "end_date": "2026-06-17",
        "status": "upcoming",
        "is_sustainable": True,
    }
    return {**base, **overrides}


def test_normalize_full_event():
    result = normalize_tdb_event(_raw_event())
    assert result["tdb_id"] == "tdb-001"
    assert result["name"] == "Stockholm Dressage Championship"
    assert result["organizer_name"] == "Swedish Equestrian Federation"
    assert result["discipline"] == "dressage"
    assert result["venue_name"] == "Friends Arena"
    assert result["is_sustainable"] is True


def test_normalize_minimal_event():
    raw = {"id": "tdb-002", "name": "Small Event", "start_date": "2026-01-01"}
    result = normalize_tdb_event(raw)
    assert result["tdb_id"] == "tdb-002"
    assert result["country"] == "SE"
    assert result["discipline"] is None


def test_slug_generation():
    result = normalize_tdb_event(_raw_event(name="Grand Prix", start_date="2026-06-15"))
    assert "grand-prix" in result["slug"]
    assert "2026-06-15" in result["slug"]
    assert "tdb-001" in result["slug"]


def test_slug_different_for_different_dates():
    r1 = normalize_tdb_event(_raw_event(start_date="2026-06-15"))
    r2 = normalize_tdb_event(_raw_event(start_date="2026-07-20"))
    assert r1["slug"] != r2["slug"]


def test_slug_different_for_same_name_and_date_with_different_tdb_ids():
    r1 = normalize_tdb_event(_raw_event(id="80876", name="Aprilhoppet", start_date="2026-04-25"))
    r2 = normalize_tdb_event(_raw_event(id="81589", name="Aprilhoppet", start_date="2026-04-25"))
    assert r1["slug"] == "aprilhoppet-2026-04-25-80876"
    assert r2["slug"] == "aprilhoppet-2026-04-25-81589"


def test_date_parsing_iso():
    result = normalize_tdb_event(_raw_event(start_date="2026-06-15"))
    from datetime import date
    assert result["start_date"] == date(2026, 6, 15)


def test_date_parsing_end_date():
    result = normalize_tdb_event(_raw_event(end_date="2026-06-17"))
    from datetime import date
    assert result["end_date"] == date(2026, 6, 17)


def test_status_mapping():
    assert normalize_tdb_event(_raw_event(status="upcoming"))["status"] == EventStatus.UPCOMING
    assert normalize_tdb_event(_raw_event(status="completed"))["status"] == EventStatus.COMPLETED
    assert normalize_tdb_event(_raw_event(status="finished"))["status"] == EventStatus.COMPLETED
    assert normalize_tdb_event(_raw_event(status="cancelled"))["status"] == EventStatus.CANCELLED


def test_raw_payload_preserved():
    raw = _raw_event()
    result = normalize_tdb_event(raw)
    assert result["raw_tdb_payload"] == raw
