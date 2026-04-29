from typing import Optional

from dateutil.parser import parse as parse_date
from slugify import slugify

from app.models.enums import EventStatus

_STATUS_MAP = {
    "upcoming": EventStatus.UPCOMING,
    "ongoing": EventStatus.ONGOING,
    "completed": EventStatus.COMPLETED,
    "cancelled": EventStatus.CANCELLED,
    "finished": EventStatus.COMPLETED,
    "national": EventStatus.UPCOMING,
    "international": EventStatus.UPCOMING,
}


def _first(value: Optional[list[str]]) -> Optional[str]:
    if isinstance(value, list) and value:
        return value[0]
    return None


def normalize_equipe_meeting(raw: dict) -> dict:
    start_date_str = raw.get("start_on") or raw.get("start_date") or raw.get("startDate")
    start_date = parse_date(start_date_str).date() if start_date_str else None

    end_date_str = raw.get("end_on") or raw.get("end_date") or raw.get("endDate")
    end_date = parse_date(end_date_str).date() if end_date_str else None

    equipe_id = raw.get("equipe_id") or raw.get("id")
    tdb_id = raw.get("tdb_id")
    name = (raw.get("display_name") or raw.get("name") or "").strip()
    raw_status = (raw.get("status") or _first(raw.get("statuses")) or "upcoming").lower().strip()
    status = _STATUS_MAP.get(raw_status, EventStatus.UPCOMING)
    country = raw.get("venue_country") or raw.get("country") or "SWE"

    if name and start_date and equipe_id:
        slug = slugify(f"{name}-{start_date}-equipe-{equipe_id}")
    elif name and start_date:
        slug = slugify(f"{name}-{start_date}")
    else:
        slug = slugify(name or f"equipe-{equipe_id}" or "event")

    return {
        "equipe_id": str(equipe_id) if equipe_id is not None else None,
        "tdb_id": str(tdb_id) if tdb_id is not None else None,
        "name": name,
        "slug": slug,
        "discipline": raw.get("discipline") or _first(raw.get("disciplines")),
        "horse_type": raw.get("horse_type") or _first(raw.get("horse_ponies")),
        "organizer_name": raw.get("organizer") or raw.get("organizer_name"),
        "district": raw.get("district"),
        "venue_name": raw.get("venue"),
        "city": raw.get("city"),
        "country": str(country).upper(),
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "is_sustainable": raw.get("is_sustainable", False),
        "raw_equipe_payload": raw,
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
