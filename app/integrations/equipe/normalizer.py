from typing import Optional

from dateutil.parser import parse as parse_date


def normalize_equipe_meeting(raw: dict) -> dict:
    start_date_str = raw.get("start_date") or raw.get("startDate")
    start_date = parse_date(start_date_str).date() if start_date_str else None

    end_date_str = raw.get("end_date") or raw.get("endDate")
    end_date = parse_date(end_date_str).date() if end_date_str else None

    return {
        "equipe_id": str(raw.get("id")) if raw.get("id") is not None else None,
        "tdb_id": raw.get("tdb_id"),
        "name": (raw.get("name") or "").strip(),
        "organizer_name": raw.get("organizer"),
        "venue_name": raw.get("venue"),
        "city": raw.get("city"),
        "country": raw.get("country") or "SE",
        "start_date": start_date,
        "end_date": end_date,
    }


def normalize_equipe_results(raw_results: list[dict]) -> list[dict]:
    results = []
    for raw in raw_results:
        results.append({
            "class_name": raw.get("class_name") or raw.get("className"),
            "participant_name": raw.get("participant_name") or raw.get("participantName") or "",
            "horse_name": raw.get("horse_name") or raw.get("horseName"),
            "ranking": raw.get("ranking") or raw.get("rank"),
            "score": raw.get("score"),
            "payload": raw,
        })
    return results
