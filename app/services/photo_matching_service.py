from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog
from dateutil.parser import parse as parse_date
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.equipe.client import EquipeClient
from app.models.enums import PhotoTagType
from app.models.event import Event
from app.models.photographer import Photo, PhotoTag

logger = structlog.get_logger()


@dataclass(frozen=True)
class EquipeStartMatch:
    start: dict
    confidence: str
    delta_seconds: int


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    parsed = parse_date(value)
    return _as_aware_utc(parsed)


def _confidence(delta_seconds: int, sec_per_start: int | None = None) -> str:
    if delta_seconds <= 90:
        return "high"

    if sec_per_start:
        smart_window = min(max(sec_per_start // 2, 60), 300)
        if delta_seconds <= smart_window:
            return "high"

    if delta_seconds <= 300:
        return "medium"
    if delta_seconds <= 600:
        return "low"
    return "none"


class PhotoMatchingService:
    def __init__(self, db: AsyncSession, equipe_client: EquipeClient):
        self.db = db
        self.equipe_client = equipe_client

    def find_nearest_start(
        self,
        taken_at: datetime,
        raw_class_section: dict,
    ) -> Optional[EquipeStartMatch]:
        starts = raw_class_section.get("starts") or []
        if not starts:
            return None

        target = _as_aware_utc(taken_at)
        sec_per_start = raw_class_section.get("sec_per_start")
        best_start = None
        best_delta = None

        for start in starts:
            start_at = _parse_datetime(start.get("start_at"))
            if not start_at:
                continue

            delta = int(abs((target - start_at).total_seconds()))
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_start = start

        if best_start is None or best_delta is None:
            return None

        confidence = _confidence(best_delta, sec_per_start)
        if confidence == "none":
            return None

        return EquipeStartMatch(
            start=best_start,
            confidence=confidence,
            delta_seconds=best_delta,
        )

    async def _resolve_class_section_id(self, photo: Photo, event: Event) -> Optional[str]:
        if photo.equipe_class_section_id:
            return photo.equipe_class_section_id

        raw_event = event.raw_equipe_payload or {}
        meeting_id = raw_event.get("id") or event.equipe_id
        if not meeting_id or not photo.event_class_id:
            return None

        schedule = await self.equipe_client.get_meeting_schedule(str(meeting_id))
        for raw_class in schedule.get("meeting_classes") or []:
            raw_class_ids = {
                str(value)
                for value in (
                    raw_class.get("id"),
                    raw_class.get("equipe_id"),
                    raw_class.get("class_no"),
                )
                if value is not None
            }
            if photo.event_class_id not in raw_class_ids:
                continue

            class_sections = raw_class.get("class_sections") or []
            if class_sections:
                section_id = class_sections[0].get("id")
                return str(section_id) if section_id is not None else None

        return None

    def _apply_match_tags(self, photo: Photo, start: dict) -> None:
        tags = [
            (PhotoTagType.RIDER, start.get("rider_name")),
            (PhotoTagType.HORSE, start.get("horse_name")),
            (PhotoTagType.START_NUMBER, start.get("start_no")),
        ]
        for tag_type, value in tags:
            if value is None or value == "":
                continue
            self.db.add(PhotoTag(photo_id=photo.id, type=tag_type, value=str(value)))

    async def match_photo(self, photo: Photo, event: Event) -> Optional[EquipeStartMatch]:
        if not photo.taken_at:
            return None

        class_section_id = await self._resolve_class_section_id(photo, event)
        if not class_section_id:
            return None

        raw_class_section = await self.equipe_client.get_class_section(class_section_id)
        match = self.find_nearest_start(photo.taken_at, raw_class_section)
        if not match:
            return None

        start = match.start
        photo.equipe_class_section_id = class_section_id
        photo.equipe_start_id = str(start.get("id") or start.get("equipe_id") or "")
        photo.equipe_rider_id = str(start["rider_id"]) if start.get("rider_id") is not None else None
        photo.equipe_horse_id = str(start["horse_id"]) if start.get("horse_id") is not None else None
        photo.matched_at = datetime.now(timezone.utc)
        photo.match_confidence = match.confidence
        photo.match_delta_seconds = match.delta_seconds
        photo.match_source = "equipe_time"

        if match.confidence == "high":
            self._apply_match_tags(photo, start)

        await self.db.flush()
        return match

    async def try_match_photo(self, photo: Photo, event: Event) -> Optional[EquipeStartMatch]:
        try:
            return await self.match_photo(photo, event)
        except Exception as exc:
            logger.warning(
                "photo_equipe_match_failed",
                photo_id=str(photo.id),
                event_id=str(event.id),
                error=str(exc),
            )
            return None
