"""Photo prices per quality tier.

Every photo has its own price per tier (`photos.price_web` / `price_high` / `price_commercial`),
set by its photographer; the tier amounts here are the defaults for new and existing photos.
Amounts are in öre (SEK minor units), the unit Stripe and `orders.amount` use.
Keep in sync with the frontend's `src/constants/qualityTiers.ts`.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.exceptions import BadRequestError

if TYPE_CHECKING:
    from app.models.photographer import Photo


@dataclass(frozen=True)
class QualityTier:
    id: str
    label: str
    default_amount: int


QUALITY_TIERS: dict[str, QualityTier] = {
    tier.id: tier
    for tier in (
        QualityTier("web", "Web quality", 49_900),
        QualityTier("high", "High quality", 99_900),
        QualityTier("commercial", "Commercial use", 150_000),
    )
}

CURRENCY = "SEK"

# Limits for a photographer's own prices, in whole SEK
MIN_PRICE_SEK = 49
MAX_PRICE_SEK = 10_000


def get_quality_tier(quality: str) -> QualityTier:
    tier = QUALITY_TIERS.get(quality)
    if not tier:
        raise BadRequestError(f"Unknown photo quality: {quality}")
    return tier


def photo_price(photo: "Photo", tier: QualityTier) -> int:
    """What this photo costs in this tier, in öre."""
    return getattr(photo, f"price_{tier.id}")


def validate_price(amount: int) -> int:
    """A photographer's price in öre: whole SEK within the limits."""
    if amount % 100 or not MIN_PRICE_SEK * 100 <= amount <= MAX_PRICE_SEK * 100:
        raise ValueError(f"Prices must be whole SEK between {MIN_PRICE_SEK} and {MAX_PRICE_SEK}")
    return amount
