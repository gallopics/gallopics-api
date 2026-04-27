import uuid

import structlog
from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.integrations.tdb.client import TDBClient
from app.integrations.tdb.normalizer import normalize_tdb_event
from app.models.event import Event, EventResult
from app.schemas.event import EventFilters

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

    async def get_event_results(self, event_id: uuid.UUID) -> list[EventResult]:
        await self.get_event(event_id)
        result = await self.db.execute(
            select(EventResult).where(EventResult.event_id == event_id)
        )
        return list(result.scalars().all())

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
        return {"created": created, "updated": updated, "errors": errors}
