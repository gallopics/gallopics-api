from typing import Optional

from pydantic import BaseModel


class EquipeMeetingRaw(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    organizer: Optional[str] = None
    venue: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    tdb_id: Optional[str] = None
