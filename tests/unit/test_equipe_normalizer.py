from datetime import date

from app.integrations.equipe.normalizer import normalize_equipe_meeting, normalize_equipe_results


def test_normalize_meeting_full():
    raw = {
        "id": "eq-001",
        "name": "Stockholm Open",
        "organizer": "SWE Fed",
        "venue": "Arena A",
        "city": "Stockholm",
        "country": "SE",
        "start_date": "2026-06-15",
        "end_date": "2026-06-17",
        "tdb_id": "tdb-123",
    }
    result = normalize_equipe_meeting(raw)
    assert result["equipe_id"] == "eq-001"
    assert result["name"] == "Stockholm Open"
    assert result["tdb_id"] == "tdb-123"
    assert result["start_date"] == date(2026, 6, 15)


def test_normalize_meeting_minimal():
    raw = {"id": "eq-002", "name": "Small Meet", "start_date": "2026-01-01"}
    result = normalize_equipe_meeting(raw)
    assert result["equipe_id"] == "eq-002"
    assert result["country"] == "SWE"


def test_normalize_online_equipe_meeting_shape():
    raw = {
        "id": 78298,
        "display_name": "Swedish Dressage",
        "start_on": "2026-05-13",
        "end_on": "2026-05-14",
        "equipe_id": 90019,
        "tdb_id": "8223",
        "discipline": "dressage",
        "disciplines": ["dressage"],
        "statuses": ["national"],
        "horse_ponies": ["horse"],
        "venue_country": "SWE",
    }
    result = normalize_equipe_meeting(raw)
    assert result["equipe_id"] == "90019"
    assert result["tdb_id"] == "8223"
    assert result["name"] == "Swedish Dressage"
    assert result["start_date"] == date(2026, 5, 13)
    assert result["end_date"] == date(2026, 5, 14)
    assert result["country"] == "SWE"
    assert result["discipline"] == "dressage"
    assert result["horse_type"] == "horse"
    assert "swedish-dressage" in result["slug"]
    assert result["raw_equipe_payload"] == raw


def test_normalize_results():
    raw = [
        {"participantName": "Alice", "horseName": "Thunder", "rank": 1, "score": "72.5", "className": "Class A"},
        {"participantName": "Bob", "horseName": "Storm", "rank": 2, "score": "70.0"},
    ]
    results = normalize_equipe_results(raw)
    assert len(results) == 2
    assert results[0]["participant_name"] == "Alice"
    assert results[0]["ranking"] == 1
    assert results[1]["horse_name"] == "Storm"


def test_handles_missing_optional_fields():
    raw = [{"participantName": "Charlie"}]
    results = normalize_equipe_results(raw)
    assert results[0]["participant_name"] == "Charlie"
    assert results[0]["horse_name"] is None
    assert results[0]["ranking"] is None
