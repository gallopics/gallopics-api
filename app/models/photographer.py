from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    OrderStatus,
    PhotographerStatus,
    PhotoStatus,
    PhotoTagType,
    PhotoVisibility,
)

if TYPE_CHECKING:
    from app.models.user import User


class Photographer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "photographers"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    city: Mapped[Optional[str]] = mapped_column(String)
    country: Mapped[Optional[str]] = mapped_column(String)
    avatar_url: Mapped[Optional[str]] = mapped_column(String)
    phone: Mapped[Optional[str]] = mapped_column(String)
    is_available_to_hire: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[PhotographerStatus] = mapped_column(default=PhotographerStatus.PENDING)
    highlights: Mapped[list[str]] = mapped_column(default=list, server_default=text("[]"))

    user: Mapped["User"] = relationship("User", back_populates="photographer")
    photos: Mapped[list["Photo"]] = relationship(back_populates="photographer", cascade="all, delete-orphan")
    event_bookings: Mapped[list["PhotographerEventBooking"]] = relationship(
        back_populates="photographer",
        cascade="all, delete-orphan",
    )


class PhotographerEventBooking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "photographer_event_bookings"
    __table_args__ = (
        UniqueConstraint("photographer_id", "event_id", name="uq_photographer_event_booking"),
    )

    photographer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("photographers.id"), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"), index=True)

    photographer: Mapped["Photographer"] = relationship(back_populates="event_bookings")


class Photo(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "photos"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"), index=True)
    class_id: Mapped[Optional[uuid.UUID]] = mapped_column(index=True)
    class_section_id: Mapped[Optional[uuid.UUID]] = mapped_column(index=True)
    event_class_id: Mapped[Optional[str]] = mapped_column(String, index=True)
    class_name: Mapped[Optional[str]] = mapped_column(String)
    photographer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("photographers.id"), index=True)
    storage_key_original: Mapped[Optional[str]] = mapped_column(String)
    storage_key_preview: Mapped[Optional[str]] = mapped_column(String)
    storage_key_thumbnail: Mapped[Optional[str]] = mapped_column(String)
    price: Mapped[int] = mapped_column()
    currency: Mapped[str] = mapped_column(String, default="SEK")
    status: Mapped[PhotoStatus] = mapped_column(default=PhotoStatus.PROCESSING)
    visibility: Mapped[PhotoVisibility] = mapped_column(default=PhotoVisibility.DRAFT)

    photographer: Mapped["Photographer"] = relationship(back_populates="photos")
    tags: Mapped[list["PhotoTag"]] = relationship(back_populates="photo", cascade="all, delete-orphan")


class PhotoTag(Base):
    __tablename__ = "photo_tags"

    photo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("photos.id"), primary_key=True)
    type: Mapped[PhotoTagType] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(String, primary_key=True)

    photo: Mapped["Photo"] = relationship(back_populates="tags")


class PhotoOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "photo_orders"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    photo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("photos.id"), index=True)
    amount: Mapped[int] = mapped_column()
    currency: Mapped[str] = mapped_column(String, default="SEK")
    klarna_order_id: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[OrderStatus] = mapped_column(default=OrderStatus.PENDING)
