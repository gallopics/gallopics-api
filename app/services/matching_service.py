import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import structlog
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.enums import MatchStatus
from app.models.event import Event

logger = structlog.get_logger()


@dataclass
class MatchCandidate:
    event_id: uuid.UUID
    score: float
    method: str


class MatchingService:
    SCORE_EXACT_ID = 1.00
    SCORE_DATE_STRONG_NAME = 0.85
    SCORE_DATE_PARTIAL = 0.75
    SCORE_THRESHOLD = 0.70

    def __init__(self, db: AsyncSession):
        self.db = db

    def _normalize_name(self, name: str) -> str:
        name = name.lower().strip()
        for prefix in ("tävling:", "competition:", "event:"):
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
        return name

    def _name_similarity(self, a: str, b: str) -> float:
        return fuzz.token_sort_ratio(self._normalize_name(a), self._normalize_name(b)) / 100.0

    def _organizer_similarity(self, a: Optional[str], b: Optional[str]) -> float:
        if not a or not b:
            return 0.0
        return fuzz.ratio(a.lower().strip(), b.lower().strip()) / 100.0

    def _venue_similarity(self, a: Optional[str], b: Optional[str]) -> float:
        if not a or not b:
            return 0.0
        return fuzz.ratio(a.lower().strip(), b.lower().strip()) / 100.0

    async def find_match(self, equipe_meeting: dict) -> Optional[MatchCandidate]:
        # Priority 1: exact tdb_id match
        tdb_id = equipe_meeting.get("tdb_id")
        if tdb_id:
            result = await self.db.execute(select(Event).where(Event.tdb_id == tdb_id))
            event = result.scalar_one_or_none()
            if event:
                return MatchCandidate(
                    event_id=event.id, score=self.SCORE_EXACT_ID, method="exact_tdb_id"
                )

        # Priority 2: date + name similarity
        meeting_date = equipe_meeting.get("start_date")
        meeting_name = equipe_meeting.get("name", "")
        meeting_organizer = equipe_meeting.get("organizer_name")
        meeting_venue = equipe_meeting.get("venue_name")

        if not meeting_date or not meeting_name:
            return None

        result = await self.db.execute(
            select(Event).where(
                Event.start_date == meeting_date,
                Event.match_status.in_([MatchStatus.UNMATCHED, MatchStatus.REJECTED]),
            )
        )
        candidates = list(result.scalars().all())

        best: Optional[MatchCandidate] = None

        for event in candidates:
            name_sim = self._name_similarity(event.name, meeting_name)

            if name_sim >= 0.85:
                score = self.SCORE_DATE_STRONG_NAME
                method = "date_strong_name"
            elif name_sim >= 0.75:
                score = self.SCORE_DATE_PARTIAL
                method = "date_partial"
            else:
                # Try boosting with organizer and venue
                org_sim = self._organizer_similarity(event.organizer_name, meeting_organizer)
                venue_sim = self._venue_similarity(event.venue_name, meeting_venue)
                combined = name_sim * 0.6 + org_sim * 0.25 + venue_sim * 0.15

                if combined >= self.SCORE_THRESHOLD:
                    score = round(combined, 2)
                    method = "combined_fuzzy"
                else:
                    continue

            if best is None or score > best.score:
                best = MatchCandidate(event_id=event.id, score=score, method=method)

        return best

    async def apply_match(
        self,
        event_id: uuid.UUID,
        equipe_id: str,
        score: float,
        method: str,
        raw_payload: dict,
    ) -> Event:
        event = await self.db.get(Event, event_id)
        if not event:
            raise NotFoundError("Event not found")

        event.equipe_id = equipe_id
        event.match_status = MatchStatus.MATCHED
        event.match_score = score
        event.match_method = method
        event.raw_equipe_payload = json.loads(json.dumps(raw_payload, default=str))
        await self.db.flush()
        return event

    async def run_matching_batch(self, equipe_meetings: list[dict]) -> dict:
        matched, unmatched, rejected = 0, 0, 0
        for meeting in equipe_meetings:
            candidate = await self.find_match(meeting)
            if candidate:
                equipe_id = meeting.get("equipe_id", "")
                await self.apply_match(
                    candidate.event_id, equipe_id, candidate.score, candidate.method, meeting
                )
                matched += 1
            else:
                unmatched += 1
        return {"matched": matched, "unmatched": unmatched}

    async def get_unmatched_events(self) -> list[Event]:
        result = await self.db.execute(
            select(Event).where(Event.match_status == MatchStatus.UNMATCHED)
        )
        return list(result.scalars().all())

    async def manual_match(self, event_id: uuid.UUID, equipe_id: str) -> Event:
        event = await self.db.get(Event, event_id)
        if not event:
            raise NotFoundError("Event not found")

        event.equipe_id = equipe_id
        event.match_status = MatchStatus.MANUAL
        event.match_score = 1.0
        event.match_method = "manual"
        await self.db.flush()
        await self.db.refresh(event)
        return event

    async def unmatch(self, event_id: uuid.UUID) -> Event:
        event = await self.db.get(Event, event_id)
        if not event:
            raise NotFoundError("Event not found")

        event.equipe_id = None
        event.match_status = MatchStatus.UNMATCHED
        event.match_score = None
        event.match_method = None
        event.raw_equipe_payload = None
        await self.db.flush()
        await self.db.refresh(event)
        return event
