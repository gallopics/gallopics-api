"""Photo prices per quality tier.

Amounts are in öre (SEK minor units), the unit Stripe and `orders.amount` use.
Keep in sync with the frontend's `src/constants/qualityTiers.ts`.
"""

from dataclasses import dataclass

from app.exceptions import BadRequestError


@dataclass(frozen=True)
class QualityTier:
    id: str
    label: str
    amount: int


QUALITY_TIERS: dict[str, QualityTier] = {
    tier.id: tier
    for tier in (
        QualityTier("web", "Web quality", 49_900),
        QualityTier("high", "High quality", 99_900),
        QualityTier("commercial", "Commercial use", 150_000),
    )
}

CURRENCY = "SEK"


def get_quality_tier(quality: str) -> QualityTier:
    tier = QUALITY_TIERS.get(quality)
    if not tier:
        raise BadRequestError(f"Unknown photo quality: {quality}")
    return tier
