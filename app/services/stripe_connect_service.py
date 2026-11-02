"""Stripe Connect for photographers: their own Stripe account receives their earnings.

Accounts are created with Stripe's Accounts v2 API (required for new Connect platforms) as
*recipients*: Gallopics collects each payment, then transfers the photographer's share to
their account (Phase 3). Stripe runs onboarding and identity checks, the photographer gets
the Express dashboard, and Gallopics pays Stripe's fees and is liable for losses. Their
Stripe balance is paid out to their bank monthly, on the 15th.
"""

from typing import Any, Literal, Optional

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import BadRequestError, ConflictError, ForbiddenError
from app.integrations.stripe.client import stripe_error
from app.models.enums import PhotographerStatus
from app.models.photographer import Photographer

logger = structlog.get_logger()

ConnectStatus = Literal["not_connected", "action_needed", "pending", "active"]

PAYOUT_DAY_OF_MONTH = 15
# Parts of a v2 Account we read; Stripe leaves them out unless asked for
_ACCOUNT_INCLUDE = ["configuration.recipient", "requirements"]
_DUE_NOW = {"currently_due", "past_due"}


def connect_status(photographer: Photographer) -> ConnectStatus:
    if not photographer.stripe_account_id:
        return "not_connected"
    if not photographer.stripe_details_submitted or photographer.stripe_requirements_due:
        return "action_needed"
    if photographer.stripe_transfers_enabled and photographer.stripe_payouts_enabled:
        return "active"
    # Details sent, Stripe is still verifying them
    return "pending"


def _get(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


class StripeConnectService:
    def __init__(self, db: AsyncSession, stripe_client: Optional[stripe.StripeClient], settings: Settings):
        self.db = db
        self.stripe = stripe_client
        self.settings = settings

    async def onboarding_link(self, photographer: Photographer, email: Optional[str]) -> str:
        """A one-time link to Stripe's onboarding form (creates the account on first use)."""
        if photographer.status != PhotographerStatus.APPROVED:
            raise ForbiddenError("Your photographer account must be approved before connecting Stripe")

        if not photographer.stripe_account_id and not email:
            # Stripe requires a contact email on recipient accounts
            raise BadRequestError("An email address is needed to connect Stripe")
        account_id = await self._ensure_account(photographer, email)
        billing_url = f"{self.settings.frontend_base_url.rstrip('/')}/pg/billing"
        try:
            link = await self._stripe().v2.core.account_links.create_async(
                {
                    "account": account_id,
                    "use_case": {
                        "type": "account_onboarding",
                        "account_onboarding": {
                            # Expired or reused link: the billing page asks for a fresh one
                            "refresh_url": f"{billing_url}?stripe=refresh",
                            "return_url": f"{billing_url}?stripe=return",
                        },
                    },
                }
            )
        except stripe.StripeError as exc:
            raise stripe_error(exc, "onboarding link") from exc
        return link.url

    async def dashboard_link(self, photographer: Photographer) -> str:
        """A one-time login link to the photographer's Stripe Express dashboard."""
        if not photographer.stripe_account_id or not photographer.stripe_details_submitted:
            raise ConflictError("Finish connecting Stripe first")
        try:
            link = await self._stripe().v1.accounts.login_links.create_async(photographer.stripe_account_id)
        except stripe.StripeError as exc:
            raise stripe_error(exc, "dashboard link") from exc
        return link.url

    async def refresh_status(self, photographer: Photographer) -> Photographer:
        """Re-read the account from Stripe and save its state on the photographer."""
        if not photographer.stripe_account_id:
            return photographer
        try:
            account = await self._stripe().v2.core.accounts.retrieve_async(
                photographer.stripe_account_id, {"include": _ACCOUNT_INCLUDE}
            )
        except stripe.StripeError as exc:
            raise stripe_error(exc, "account lookup") from exc
        self.apply_account(photographer, account)
        await self.db.flush()
        if connect_status(photographer) == "active":
            # Imported here: the payout service depends on this module
            from app.services.payout_service import PayoutService

            # Shares from sales made before they connected
            await PayoutService(self.db, self.stripe, self.settings).settle_photographer(photographer)
        return photographer

    async def sync_account(self, account_id: str) -> Optional[Photographer]:
        """A webhook said this account changed: refresh its photographer, if it's one of ours."""
        result = await self.db.execute(select(Photographer).where(Photographer.stripe_account_id == account_id))
        photographer = result.scalar_one_or_none()
        if photographer:
            await self.refresh_status(photographer)
        return photographer

    @staticmethod
    def apply_account(photographer: Photographer, account: Any) -> None:
        """Copy a v2 Account's state (fetched with `_ACCOUNT_INCLUDE`) onto the photographer."""
        data = account.to_dict() if hasattr(account, "to_dict") else account
        balance = _get(data, "configuration", "recipient", "capabilities", "stripe_balance") or {}
        transfers_active = _get(balance, "stripe_transfers", "status") == "active"
        payouts_status = _get(balance, "payouts", "status")
        due_now = _get(data, "requirements", "summary", "minimum_deadline", "status") in _DUE_NOW

        photographer.stripe_requirements_due = due_now
        # v2 has no "details submitted" flag: nothing due now means the form is done
        photographer.stripe_details_submitted = not due_now
        photographer.stripe_transfers_enabled = transfers_active
        # Recipient accounts may not list a separate payouts capability
        photographer.stripe_payouts_enabled = (
            payouts_status == "active" if payouts_status is not None else transfers_active
        )

    async def _ensure_account(self, photographer: Photographer, email: Optional[str]) -> str:
        # Lock the row so a double click can't create two Stripe accounts
        result = await self.db.execute(
            select(Photographer)
            .where(Photographer.id == photographer.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        photographer = result.scalar_one()
        if photographer.stripe_account_id:
            return photographer.stripe_account_id

        params: dict[str, Any] = {
            "display_name": photographer.display_name,
            "dashboard": "express",
            "identity": {"country": "se"},
            "configuration": {
                # Earnings arrive as transfers from Gallopics; no card payments of their own
                "recipient": {"capabilities": {"stripe_balance": {"stripe_transfers": {"requested": True}}}},
            },
            "defaults": {
                "currency": "sek",
                "responsibilities": {"fees_collector": "application", "losses_collector": "application"},
            },
            "metadata": {"photographer_id": str(photographer.id)},
            "include": _ACCOUNT_INCLUDE,
        }
        if email:
            params["contact_email"] = email
        try:
            account = await self._stripe().v2.core.accounts.create_async(
                params, {"idempotency_key": f"connect-account-{photographer.id}"}
            )
        except stripe.StripeError as exc:
            raise stripe_error(exc, "account creation") from exc

        photographer.stripe_account_id = account.id
        self.apply_account(photographer, account)
        await self.db.flush()
        await self._set_monthly_payouts(account.id)
        return account.id

    async def _set_monthly_payouts(self, account_id: str) -> None:
        """Pay the balance out on the 15th of each month (a v1 setting; works on v2 accounts)."""
        try:
            await self._stripe().v1.accounts.update_async(
                account_id,
                {"settings": {"payouts": {"schedule": {"interval": "monthly", "monthly_anchor": PAYOUT_DAY_OF_MONTH}}}},
            )
        except stripe.StripeError as exc:
            # Onboarding can go on; Stripe's default schedule applies until this is fixed
            logger.error("stripe_payout_schedule_failed", account_id=account_id, error=str(exc))

    def _stripe(self) -> stripe.StripeClient:
        if self.stripe is None:
            raise BadRequestError("Stripe is not configured")
        return self.stripe
