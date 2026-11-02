import json
from typing import Optional

import stripe
import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import BadRequestError
from app.integrations.clerk.auth import require_role
from app.integrations.stripe.client import get_stripe_client
from app.models.enums import UserRole
from app.models.photographer import Photographer
from app.models.user import User
from app.schemas.stripe_connect import StripeConnectStatusResponse, StripeLinkResponse, StripeOnboardingRequest
from app.services.photographer_service import PhotographerService
from app.services.stripe_connect_service import PAYOUT_DAY_OF_MONTH, StripeConnectService, connect_status

router = APIRouter(prefix="/api/v1/photographer/stripe", tags=["stripe-connect"])
webhook_router = APIRouter(prefix="/api/v1/stripe/connect", tags=["stripe-connect"])
logger = structlog.get_logger()


def _status_response(photographer: Photographer) -> StripeConnectStatusResponse:
    return StripeConnectStatusResponse(
        status=connect_status(photographer),
        details_submitted=photographer.stripe_details_submitted,
        transfers_enabled=photographer.stripe_transfers_enabled,
        payouts_enabled=photographer.stripe_payouts_enabled,
        payout_day_of_month=PAYOUT_DAY_OF_MONTH,
    )


@router.get("", response_model=StripeConnectStatusResponse)
async def get_connect_status(
    refresh: bool = False,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
):
    """The saved status; `refresh=true` re-reads it from Stripe (after returning from onboarding)."""
    photographer = await PhotographerService(db).get_photographer_for_user(user.id)
    if refresh:
        await StripeConnectService(db, stripe_client, get_settings()).refresh_status(photographer)
    return _status_response(photographer)


@router.post("/onboarding-link", response_model=StripeLinkResponse)
async def create_onboarding_link(
    body: Optional[StripeOnboardingRequest] = None,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
):
    photographer = await PhotographerService(db).get_photographer_for_user(user.id)
    email = user.email or (body.email if body else None)
    url = await StripeConnectService(db, stripe_client, get_settings()).onboarding_link(photographer, email)
    return StripeLinkResponse(url=url)


@router.post("/dashboard-link", response_model=StripeLinkResponse)
async def create_dashboard_link(
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
):
    photographer = await PhotographerService(db).get_photographer_for_user(user.id)
    url = await StripeConnectService(db, stripe_client, get_settings()).dashboard_link(photographer)
    return StripeLinkResponse(url=url)


@webhook_router.post("/webhook")
async def stripe_connect_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
):
    """Events about photographers' Stripe accounts; each one re-reads the account from Stripe.

    Accepts v2 "thin" events (v2.core.account[...]) and classic snapshot events (account.updated).
    """
    settings = get_settings()
    secret = settings.stripe_connect_webhook_secret or settings.stripe_webhook_secret
    if not secret:
        raise BadRequestError("Stripe Connect webhook secret is not configured")

    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        is_thin = json.loads(payload).get("object") == "v2.core.event"
        if is_thin:
            notification = stripe_client.parse_event_notification(payload, signature, secret)
            event_type = notification.type
            related = getattr(notification, "related_object", None)
            account_id = related.id if related and event_type.startswith("v2.core.account") else None
        else:
            event = stripe_client.construct_event(payload, signature, secret)
            event_type = event.type
            account_id = event.data.object.id if event_type == "account.updated" else None
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise BadRequestError("Invalid Stripe webhook signature") from exc

    if not account_id:
        logger.info("stripe_connect_webhook_ignored", event_type=event_type)
        return {"received": True}

    photographer = await StripeConnectService(db, stripe_client, settings).sync_account(account_id)
    if not photographer:
        logger.warning("stripe_connect_unknown_account", account_id=account_id, event_type=event_type)
    return {"received": True}
