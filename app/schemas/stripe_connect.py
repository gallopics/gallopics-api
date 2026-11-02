import re
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class StripeConnectStatusResponse(BaseModel):
    # not_connected → action_needed (form unfinished / Stripe needs more) → pending (being verified) → active
    status: Literal["not_connected", "action_needed", "pending", "active"]
    details_submitted: bool
    transfers_enabled: bool
    payouts_enabled: bool
    payout_day_of_month: int


class StripeLinkResponse(BaseModel):
    url: str


class StripeOnboardingRequest(BaseModel):
    # Fallback contact email (the signed-in Clerk email) when the user record has none
    email: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Invalid email")
        return value
