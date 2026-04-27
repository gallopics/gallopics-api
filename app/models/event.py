import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EventStatus, MatchStatus


class Event(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "events"

    tdb_id: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True)
    equipe_id: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    discipline: Mapped[Optional[str]] = mapped_column(String)
    horse_type: Mapped[Optional[str]] = mapped_column(String)
    organizer_name: Mapped[Optional[str]] = mapped_column(String)
    district: Mapped[Optional[str]] = mapped_column(String)
    venue_name: Mapped[Optional[str]] = mapped_column(String)
    city: Mapped[Optional[str]] = mapped_column(String)
    country: Mapped[str] = mapped_column(String, default="SE")
    start_date: Mapped[date] = mapped_column()
    end_date: Mapped[Optional[date]] = mapped_column()
    status: Mapped[EventStatus] = mapped_column(default=EventStatus.UPCOMING)
    is_sustainable: Mapped[bool] = mapped_column(default=False)
    match_status: Mapped[MatchStatus] = mapped_column(default=MatchStatus.UNMATCHED)
    match_score: Mapped[Optional[float]] = mapped_column()
    match_method: Mapped[Optional[str]] = mapped_column(String)
    raw_tdb_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    raw_equipe_payload: Mapped[Optional[dict]] = mapped_column(JSON)

    results: Mapped[list["EventResult"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class EventResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_results"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"), index=True)
    class_name: Mapped[Optional[str]] = mapped_column(String)
    participant_name: Mapped[str] = mapped_column(String)
    horse_name: Mapped[Optional[str]] = mapped_column(String)
    ranking: Mapped[Optional[int]] = mapped_column()
    score: Mapped[Optional[str]] = mapped_column(String)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    published_at: Mapped[Optional[datetime]] = mapped_column()

    event: Mapped["Event"] = relationship(back_populates="results")
