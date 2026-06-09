from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


@dataclass(frozen=True)
class EquipeSectionStartMatch:
    class_section_id: str
    raw_class_section: dict
    start_match: EquipeStartMatch


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    parsed = parse_date(value)
    return _as_aware_utc(parsed)


def _start_order(start: dict) -> tuple[int, int]:
    start_no = start.get("start_no")
    if start_no is not None and str(start_no).isdigit():
        return (0, int(start_no))
    position = start.get("position")
    if isinstance(position, int):
        return (1, position)
    return (2, 0)


def _result_time_seconds(start: dict) -> Optional[float]:
    for result in start.get("results") or []:
        value = result.get("time")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _estimated_start_from_result(start: dict) -> Optional[datetime]:
    start_at = _parse_datetime(start.get("start_at"))
    if start_at:
        return start_at

    result_at = _parse_datetime(start.get("result_at"))
    result_time = _result_time_seconds(start)
    if result_at and result_time:
        return result_at - timedelta(seconds=result_time)

    return None


def _estimated_start_times(raw_class_section: dict) -> dict[int, datetime]:
    starts = raw_class_section.get("starts") or []
    estimates: dict[int, datetime] = {}
    ordered_starts = sorted(enumerate(starts), key=lambda item: _start_order(item[1]))
    ordered_indexes = [index for index, _start in ordered_starts]

    for index, start in enumerate(starts):
        estimated = _estimated_start_from_result(start)
        if estimated:
            estimates[index] = estimated

    sec_per_start = raw_class_section.get("sec_per_start")
    if not isinstance(sec_per_start, int) or sec_per_start <= 0 or not estimates:
        return estimates

    order_positions = {start_index: order for order, start_index in enumerate(ordered_indexes)}
    for index in range(len(starts)):
        if index in estimates:
            continue

        index_order = order_positions[index]
        nearest_index = min(
            estimates,
            key=lambda estimate_index: abs(order_positions[estimate_index] - index_order),
        )
        order_delta = index_order - order_positions[nearest_index]
        estimates[index] = estimates[nearest_index] + timedelta(
            seconds=order_delta * sec_per_start
        )

    return estimates


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

        start_times = _estimated_start_times(raw_class_section)

        for index, start in enumerate(starts):
            start_at = start_times.get(index) or _parse_datetime(start.get("result_at"))
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

    async def _get_event_schedule(self, event: Event) -> Optional[dict]:
        raw_event = event.raw_equipe_payload or {}
        meeting_id = raw_event.get("id") or event.equipe_id
        if not meeting_id:
            return None

        return await self.equipe_client.get_meeting_schedule(str(meeting_id))

    def _find_schedule_class(self, schedule: dict, class_id: str | None) -> Optional[dict]:
        if not class_id:
            return None

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
            if class_id not in raw_class_ids:
                continue
            return raw_class

        return None

    def _schedule_class_section_ids(self, schedule: dict) -> set[str]:
        return {
            str(section["id"])
            for raw_class in schedule.get("meeting_classes") or []
            for section in raw_class.get("class_sections") or []
            if section.get("id") is not None
        }

    async def _candidate_class_sections(self, photo: Photo, event: Event) -> list[tuple[str, dict]]:
        schedule = await self._get_event_schedule(event)
        if not schedule:
            return []

        schedule_section_ids = self._schedule_class_section_ids(schedule)

        if photo.equipe_class_section_id and photo.equipe_class_section_id in schedule_section_ids:
            return [
                (
                    photo.equipe_class_section_id,
                    await self.equipe_client.get_class_section(photo.equipe_class_section_id),
                )
            ]

        raw_class = self._find_schedule_class(
            schedule,
            photo.equipe_class_section_id or photo.event_class_id,
        )
        if not raw_class:
            return []

        candidates = []
        for section in raw_class.get("class_sections") or []:
            section_id = section.get("id")
            if section_id is None:
                continue
            section_id = str(section_id)
            candidates.append((section_id, await self.equipe_client.get_class_section(section_id)))

        return candidates

    async def _find_best_section_start_match(
        self,
        photo: Photo,
        event: Event,
    ) -> Optional[EquipeSectionStartMatch]:
        if not photo.taken_at:
            return None

        best: Optional[EquipeSectionStartMatch] = None
        for class_section_id, raw_class_section in await self._candidate_class_sections(photo, event):
            match = self.find_nearest_start(photo.taken_at, raw_class_section)
            if not match:
                continue

            candidate = EquipeSectionStartMatch(
                class_section_id=class_section_id,
                raw_class_section=raw_class_section,
                start_match=match,
            )
            if best is None or match.delta_seconds < best.start_match.delta_seconds:
                best = candidate

        return best

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

        section_match = await self._find_best_section_start_match(photo, event)
        if not section_match:
            return None

        match = section_match.start_match
        start = match.start
        photo.equipe_class_section_id = section_match.class_section_id
        photo.equipe_start_id = str(start.get("id") or start.get("equipe_id") or "")
        photo.equipe_rider_id = str(start["rider_id"]) if start.get("rider_id") is not None else None
        photo.equipe_horse_id = str(start["horse_id"]) if start.get("horse_id") is not None else None
        photo.matched_at = datetime.now(timezone.utc).replace(tzinfo=None)
        photo.match_confidence = match.confidence
        photo.match_delta_seconds = match.delta_seconds
        photo.match_source = "equipe_time"

        if match.confidence in {"high", "medium"}:
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
