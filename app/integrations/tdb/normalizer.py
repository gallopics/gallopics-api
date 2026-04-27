from dateutil.parser import parse as parse_date
from slugify import slugify

from app.models.enums import EventStatus

_STATUS_MAP = {
    "upcoming": EventStatus.UPCOMING,
    "ongoing": EventStatus.ONGOING,
    "completed": EventStatus.COMPLETED,
    "cancelled": EventStatus.CANCELLED,
    "finished": EventStatus.COMPLETED,
    "planned": EventStatus.UPCOMING,
    "öppen": EventStatus.UPCOMING,
    "oppen": EventStatus.UPCOMING,
    "stängd": EventStatus.UPCOMING,
    "stangd": EventStatus.UPCOMING,
    "resultat": EventStatus.COMPLETED,
    "inställd": EventStatus.CANCELLED,
    "installd": EventStatus.CANCELLED,
}


def normalize_tdb_event(raw: dict) -> dict:
    tdb_id = raw.get("id")
    name = (raw.get("name") or "").strip()
    start_date_str = raw.get("start_date") or raw.get("startDate")
    start_date = parse_date(start_date_str).date() if start_date_str else None

    end_date_str = raw.get("end_date") or raw.get("endDate")
    end_date = parse_date(end_date_str).date() if end_date_str else None

    raw_status = (raw.get("status") or "upcoming").lower().strip()
    status = _STATUS_MAP.get(raw_status, EventStatus.UPCOMING)

    if name and start_date and tdb_id:
        slug = slugify(f"{name}-{start_date}-{tdb_id}")
    elif name and start_date:
        slug = slugify(f"{name}-{start_date}")
    else:
        slug = slugify(name or "event")

    return {
        "tdb_id": tdb_id,
        "name": name,
        "slug": slug,
        "discipline": raw.get("discipline"),
        "horse_type": raw.get("horse_type") or raw.get("horseType"),
        "organizer_name": raw.get("organizer"),
        "district": raw.get("district"),
        "venue_name": raw.get("venue"),
        "city": raw.get("city"),
        "country": raw.get("country") or "SE",
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "is_sustainable": raw.get("is_sustainable", False),
        "raw_tdb_payload": raw,
    }
