from functools import lru_cache

import stripe

from app.config import get_settings
from app.exceptions import ExternalServiceError


@lru_cache
def _stripe_client(secret_key: str) -> stripe.StripeClient:
    return stripe.StripeClient(secret_key)


def get_stripe_client() -> stripe.StripeClient:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise ExternalServiceError("Stripe is not configured")
    return _stripe_client(settings.stripe_secret_key)


def stripe_error(exc: Exception, action: str) -> ExternalServiceError:
    message = getattr(exc, "user_message", None) or str(exc)
    return ExternalServiceError(f"Stripe {action} failed: {message}")
