import uuid
from datetime import date

import structlog
from dateutil.parser import parse as parse_date
from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.integrations.equipe.client import EquipeClient
from app.integrations.equipe.normalizer import normalize_equipe_meeting
from app.integrations.tdb.client import TDBClient
from app.integrations.tdb.normalizer import normalize_tdb_event
from app.models.event import Event, EventResult
from app.schemas.event import EventFilters, EventScheduleResponse

logger = structlog.get_logger()


class EventService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_events(
        self, filters: EventFilters, page: int = 1, page_size: int = 20
    ) -> tuple[list[Event], int]:
        query = select(Event)

        if filters.date_from:
            query = query.where(Event.start_date >= filters.date_from)
        if filters.date_to:
            query = query.where(Event.start_date <= filters.date_to)
        if filters.discipline:
            query = query.where(Event.discipline == filters.discipline)
        if filters.horse_type:
            query = query.where(Event.horse_type == filters.horse_type)
        if filters.district:
            query = query.where(Event.district == filters.district)
        if filters.organizer:
            query = query.where(Event.organizer_name == filters.organizer)
        if filters.status:
            query = query.where(Event.status == filters.status)
        if filters.is_sustainable is not None:
            query = query.where(Event.is_sustainable == filters.is_sustainable)
        if filters.search:
            query = query.where(Event.name.ilike(f"%{filters.search}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = query.order_by(Event.start_date.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def get_event(self, event_id: uuid.UUID) -> Event:
        event = await self.db.get(Event, event_id)
        if not event:
            raise NotFoundError("Event not found")
        return event

    async def get_event_by_slug(self, slug: str) -> Event:
        result = await self.db.execute(select(Event).where(Event.slug == slug))
        event = result.scalar_one_or_none()
        if not event:
            raise NotFoundError("Event not found")
        return event

    async def create_event(self, data: dict) -> Event:
        if "slug" not in data or not data["slug"]:
            name = data.get("name", "event")
            start = data.get("start_date", "")
            data["slug"] = slugify(f"{name}-{start}")

        event = Event(**data)
        self.db.add(event)
        await self.db.flush()
        return event

    async def update_event(self, event_id: uuid.UUID, data: dict) -> Event:
        event = await self.get_event(event_id)
        for key, value in data.items():
            setattr(event, key, value)
        await self.db.flush()
        return event

    async def upsert_event_by_tdb_id(self, tdb_id: str, data: dict) -> tuple[Event, bool]:
        result = await self.db.execute(select(Event).where(Event.tdb_id == tdb_id))
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in data.items():
                if key != "tdb_id":
                    setattr(existing, key, value)
            await self.db.flush()
            return existing, False
        else:
            data["tdb_id"] = tdb_id
            event = await self.create_event(data)
            return event, True

    async def upsert_event_by_equipe_id(self, equipe_id: str, data: dict) -> tuple[Event, bool]:
        result = await self.db.execute(select(Event).where(Event.equipe_id == equipe_id))
        existing = result.scalar_one_or_none()

        if not existing and data.get("tdb_id"):
            result = await self.db.execute(select(Event).where(Event.tdb_id == data["tdb_id"]))
            existing = result.scalar_one_or_none()

        if existing:
            for key, value in data.items():
                if key != "equipe_id":
                    setattr(existing, key, value)
            existing.equipe_id = equipe_id
            await self.db.flush()
            return existing, False

        data["equipe_id"] = equipe_id
        event = await self.create_event(data)
        return event, True

    async def get_event_results(self, event_id: uuid.UUID) -> list[EventResult]:
        await self.get_event(event_id)
        result = await self.db.execute(
            select(EventResult).where(EventResult.event_id == event_id)
        )
        return list(result.scalars().all())

    def _get_equipe_meeting_id(self, event: Event) -> str | None:
        raw_payload = event.raw_equipe_payload or {}
        raw_meeting_id = raw_payload.get("id")
        if raw_meeting_id is not None:
            return str(raw_meeting_id)
        return event.equipe_id

    def _normalize_schedule_date(self, value: str | None, fallback: date) -> date:
        if not value:
            return fallback
        return parse_date(value).date()

    def _normalize_schedule_time(self, raw_class: dict) -> str | None:
        if raw_class.get("display_time"):
            return raw_class["display_time"]
        start_at = raw_class.get("start_at")
        if not start_at:
            return None
        return parse_date(start_at).strftime("%H:%M")

    def normalize_equipe_schedule(self, event: Event, raw_schedule: dict) -> EventScheduleResponse:
        fallback_date = event.start_date
        classes_by_date: dict[date, list[dict]] = {}

        for raw_class in raw_schedule.get("meeting_classes") or []:
            if (
                not raw_class.get("name")
                or "id" not in raw_class
                or raw_class.get("divider") is True
                or raw_class.get("excluded_from_total") is True
                or raw_class.get("discipline") == "list"
            ):
                continue

            class_date = self._normalize_schedule_date(
                raw_class.get("date") or raw_class.get("start_at"),
                fallback_date,
            )
            class_no = raw_class.get("class_no")
            name = raw_class["name"]
            display_name = f"{class_no} · {name}" if class_no else name
            class_item = {
                "id": str(raw_class["id"]),
                "name": display_name,
                "class_no": str(class_no) if class_no is not None else None,
                "date": class_date,
                "start_time": self._normalize_schedule_time(raw_class),
                "arena": raw_class.get("arena") or "Main Arena",
                "discipline": raw_class.get("discipline") or raw_schedule.get("discipline"),
                "position": raw_class.get("position") or 0,
            }
            classes_by_date.setdefault(class_date, []).append(class_item)

        days = [
            {
                "date": class_date,
                "classes": sorted(classes, key=lambda item: item["position"]),
            }
            for class_date, classes in sorted(classes_by_date.items())
        ]
        equipe_meeting_id = self._get_equipe_meeting_id(event)

        return EventScheduleResponse(
            event_id=event.id,
            equipe_meeting_id=equipe_meeting_id or "",
            classes_count=sum(len(day["classes"]) for day in days),
            days=days,
        )

    async def get_event_schedule(
        self, event_id: uuid.UUID, equipe_client: EquipeClient
    ) -> EventScheduleResponse:
        event = await self.get_event(event_id)
        equipe_meeting_id = self._get_equipe_meeting_id(event)
        if not equipe_meeting_id:
            raise NotFoundError("Event does not have an Equipe meeting id")

        raw_schedule = await equipe_client.get_meeting_schedule(equipe_meeting_id)
        return self.normalize_equipe_schedule(event, raw_schedule)

    async def upsert_event_results(
        self, event_id: uuid.UUID, results: list[dict]
    ) -> list[EventResult]:
        await self.get_event(event_id)
        created = []
        for r in results:
            er = EventResult(event_id=event_id, **r)
            self.db.add(er)
            created.append(er)
        await self.db.flush()
        return created

    async def sync_from_tdb(self, tdb_client: TDBClient) -> dict:
        raw_events = await tdb_client.search_events()
        created, updated, errors = 0, 0, 0
        error_samples = []
        for raw in raw_events:
            try:
                async with self.db.begin_nested():
                    normalized = normalize_tdb_event(raw)
                    tdb_id = normalized.pop("tdb_id", None)
                    if not tdb_id:
                        errors += 1
                        continue
                    event, is_new = await self.upsert_event_by_tdb_id(tdb_id, normalized)
                if is_new:
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                logger.error("tdb_sync_error", raw_event=raw, error=str(e))
                errors += 1
                if len(error_samples) < 5:
                    error_samples.append(
                        {
                            "tdb_id": raw.get("id"),
                            "name": raw.get("name"),
                            "error": str(e),
                        }
                    )
        return {"created": created, "updated": updated, "errors": errors, "error_samples": error_samples}

    async def sync_from_equipe(self, equipe_client: EquipeClient, country: str = "swe") -> dict:
        raw_meetings = await equipe_client.get_meetings(params={"country": country})
        created, updated, skipped, errors = 0, 0, 0, 0
        error_samples = []
        accepted_countries = {country.lower()}
        if country.lower() == "swe":
            accepted_countries.add("se")

        for raw in raw_meetings:
            venue_country = (raw.get("venue_country") or raw.get("country") or "").lower()
            if country and venue_country and venue_country not in accepted_countries:
                skipped += 1
                continue

            try:
                async with self.db.begin_nested():
                    normalized = normalize_equipe_meeting(raw)
                    equipe_id = normalized.pop("equipe_id", None)
                    if not equipe_id or not normalized.get("start_date"):
                        errors += 1
                        continue
                    event, is_new = await self.upsert_event_by_equipe_id(equipe_id, normalized)
                if is_new:
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                logger.error("equipe_sync_error", raw_meeting=raw, error=str(e))
                errors += 1
                if len(error_samples) < 5:
                    error_samples.append(
                        {
                            "equipe_id": raw.get("equipe_id") or raw.get("id"),
                            "name": raw.get("display_name") or raw.get("name"),
                            "error": str(e),
                        }
                    )

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "error_samples": error_samples,
        }
