from typing import Optional

from pydantic import BaseModel


class TDBEventRaw(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    organizer: Optional[str] = None
    discipline: Optional[str] = None
    horse_type: Optional[str] = None
    district: Optional[str] = None
    venue: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    is_sustainable: Optional[bool] = None
