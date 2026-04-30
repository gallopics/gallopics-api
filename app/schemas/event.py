import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import EventStatus, MatchStatus


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tdb_id: Optional[str] = None
    equipe_id: Optional[str] = None
    name: str
    slug: str
    discipline: Optional[str] = None
    horse_type: Optional[str] = None
    organizer_name: Optional[str] = None
    district: Optional[str] = None
    venue_name: Optional[str] = None
    city: Optional[str] = None
    country: str
    start_date: date
    end_date: Optional[date] = None
    status: EventStatus
    is_sustainable: bool
    match_status: MatchStatus
    match_score: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class EventFilters(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    discipline: Optional[str] = None
    horse_type: Optional[str] = None
    district: Optional[str] = None
    organizer: Optional[str] = None
    status: Optional[EventStatus] = None
    is_sustainable: Optional[bool] = None
    search: Optional[str] = None


class EventResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    class_name: Optional[str] = None
    participant_name: str
    horse_name: Optional[str] = None
    ranking: Optional[int] = None
    score: Optional[str] = None
    published_at: Optional[datetime] = None


class EventClassResponse(BaseModel):
    id: str
    name: str
    class_no: Optional[str] = None
    date: date
    start_time: Optional[str] = None
    arena: str
    discipline: Optional[str] = None
    position: int = 0


class EventScheduleDayResponse(BaseModel):
    date: date
    classes: list[EventClassResponse]


class EventScheduleResponse(BaseModel):
    event_id: uuid.UUID
    equipe_meeting_id: str
    classes_count: int
    days: list[EventScheduleDayResponse]
