import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace

import pytest
import stripe
from sqlalchemy import select

from app.config import get_settings
from app.integrations.stripe.client import get_stripe_client
from app.main import app
from app.models.enums import PhotographerStatus, UserRole
from app.models.photographer import Photographer
from app.models.user import User

WEBHOOK_SECRET = "whsec_test_connect"


def _account(account_id="acct_test_1", transfers="pending", due="currently_due"):
    """A v2 Account as Stripe returns it with include=[configuration.recipient, requirements]."""
    data = {
        "id": account_id,
        "object": "v2.core.account",
        "configuration": {
            "recipient": {"capabilities": {"stripe_balance": {"stripe_transfers": {"status": transfers}}}}
        },
        "requirements": {"summary": {"minimum_deadline": {"status": due} if due else None}},
    }
    return stripe.StripeObject.construct_from(data, "sk_test_dummy")


class FakeStripe:
    """Fakes Stripe's network calls; webhook signatures are checked by the real library."""

    def __init__(self):
        self.created_accounts = []
        self.account_links = []
        self.login_links = []
        self.account_updates = []
        self.account_state = _account()
        self._real = stripe.StripeClient("sk_test_dummy")
        fake = self

        async def create_account(params, options=None):
            fake.created_accounts.append((params, options))
            return fake.account_state

        async def retrieve_account(account_id, params=None, options=None):
            return fake.account_state

        async def create_account_link(params, options=None):
            fake.account_links.append(params)
            return SimpleNamespace(url="https://connect.stripe.test/setup/abc")

        async def update_v1_account(account_id, params=None, options=None):
            fake.account_updates.append((account_id, params))
            return SimpleNamespace(id=account_id)

        async def create_login_link(account_id, params=None, options=None):
            fake.login_links.append(account_id)
            return SimpleNamespace(url="https://connect.stripe.test/express/login")

        self.v2 = SimpleNamespace(
            core=SimpleNamespace(
                accounts=SimpleNamespace(create_async=create_account, retrieve_async=retrieve_account),
                account_links=SimpleNamespace(create_async=create_account_link),
            )
        )
        self.v1 = SimpleNamespace(
            accounts=SimpleNamespace(
                update_async=update_v1_account,
                login_links=SimpleNamespace(create_async=create_login_link),
            )
        )

    def construct_event(self, payload, sig_header, secret):
        return self._real.construct_event(payload, sig_header, secret)

    def parse_event_notification(self, payload, sig_header, secret):
        return self._real.parse_event_notification(payload, sig_header, secret)


@pytest.fixture
def fake_stripe(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_CONNECT_WEBHOOK_SECRET", "")  # ignore a local .env value
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://gallopics.test")
    get_settings.cache_clear()
    fake = FakeStripe()
    app.dependency_overrides[get_stripe_client] = lambda: fake
    yield fake
    get_settings.cache_clear()


async def _make_photographer(db_session, user, status=PhotographerStatus.APPROVED, **fields):
    photographer = Photographer(
        user_id=user.id,
        slug="connect-test",
        display_name="Connect Test",
        status=status,
        **fields,
    )
    db_session.add(photographer)
    await db_session.flush()
    return photographer


async def _reload(db_session, photographer):
    result = await db_session.execute(
        select(Photographer).where(Photographer.id == photographer.id).execution_options(populate_existing=True)
    )
    return result.scalar_one()


def _signed(payload, secret):
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    return {"stripe-signature": f"t={timestamp},v1={signature}", "content-type": "application/json"}


async def _send_webhook(async_client, event_type, obj, secret=WEBHOOK_SECRET):
    """A classic snapshot event (account.updated)."""
    payload = json.dumps({"id": "evt_connect_1", "object": "event", "type": event_type, "data": {"object": obj}})
    return await async_client.post("/api/v1/stripe/connect/webhook", content=payload, headers=_signed(payload, secret))


async def _send_thin_event(async_client, event_type, account_id, secret=WEBHOOK_SECRET):
    """A v2 "thin" event: names the changed account, without its data."""
    payload = json.dumps(
        {
            "id": "evt_thin_1",
            "object": "v2.core.event",
            "type": event_type,
            "created": "2026-10-19T10:00:00.000Z",
            "livemode": False,
            "related_object": {
                "id": account_id,
                "type": "v2.core.account",
                "url": f"/v2/core/accounts/{account_id}",
            },
        }
    )
    return await async_client.post("/api/v1/stripe/connect/webhook", content=payload, headers=_signed(payload, secret))


async def test_status_not_connected(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    await _make_photographer(db_session, photographer_user)
    response = await async_client.get("/api/v1/photographer/stripe", headers=photographer_auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "not_connected"
    assert response.json()["payout_day_of_month"] == 15


async def test_status_requires_photographer(async_client, auth_headers, fake_stripe):
    response = await async_client.get("/api/v1/photographer/stripe", headers=auth_headers)
    assert response.status_code == 403


async def test_onboarding_creates_account_once(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    photographer = await _make_photographer(db_session, photographer_user)

    first = await async_client.post("/api/v1/photographer/stripe/onboarding-link", headers=photographer_auth_headers)
    second = await async_client.post("/api/v1/photographer/stripe/onboarding-link", headers=photographer_auth_headers)

    assert first.status_code == 200
    assert first.json()["url"] == "https://connect.stripe.test/setup/abc"
    assert second.status_code == 200
    assert len(fake_stripe.created_accounts) == 1

    params, options = fake_stripe.created_accounts[0]
    assert params["identity"] == {"country": "se"}
    assert params["contact_email"] == "photo@example.com"
    assert params["dashboard"] == "express"
    assert params["defaults"]["responsibilities"] == {
        "fees_collector": "application",
        "losses_collector": "application",
    }
    assert params["configuration"] == {
        "recipient": {"capabilities": {"stripe_balance": {"stripe_transfers": {"requested": True}}}}
    }
    assert options["idempotency_key"] == f"connect-account-{photographer.id}"
    assert fake_stripe.account_updates == [
        ("acct_test_1", {"settings": {"payouts": {"schedule": {"interval": "monthly", "monthly_anchor": 15}}}})
    ]

    link = fake_stripe.account_links[0]
    onboarding = link["use_case"]["account_onboarding"]
    assert link["account"] == "acct_test_1"
    assert link["use_case"]["type"] == "account_onboarding"
    assert onboarding["return_url"] == "https://gallopics.test/pg/billing?stripe=return"
    assert onboarding["refresh_url"] == "https://gallopics.test/pg/billing?stripe=refresh"

    saved = await _reload(db_session, photographer)
    assert saved.stripe_account_id == "acct_test_1"
    status = await async_client.get("/api/v1/photographer/stripe", headers=photographer_auth_headers)
    assert status.json()["status"] == "action_needed"


async def test_onboarding_requires_approved_photographer(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    await _make_photographer(db_session, photographer_user, status=PhotographerStatus.PENDING)
    response = await async_client.post("/api/v1/photographer/stripe/onboarding-link", headers=photographer_auth_headers)
    assert response.status_code == 403
    assert fake_stripe.created_accounts == []


async def test_refresh_reads_account_from_stripe(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    await _make_photographer(db_session, photographer_user, stripe_account_id="acct_test_1")
    fake_stripe.account_state = _account(transfers="pending", due=None)
    response = await async_client.get("/api/v1/photographer/stripe?refresh=true", headers=photographer_auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


async def test_dashboard_link_needs_finished_onboarding(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    await _make_photographer(db_session, photographer_user, stripe_account_id="acct_test_1")
    response = await async_client.post("/api/v1/photographer/stripe/dashboard-link", headers=photographer_auth_headers)
    assert response.status_code == 409
    assert fake_stripe.login_links == []


async def test_dashboard_link(async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe):
    await _make_photographer(
        db_session, photographer_user, stripe_account_id="acct_test_1", stripe_details_submitted=True
    )
    response = await async_client.post("/api/v1/photographer/stripe/dashboard-link", headers=photographer_auth_headers)
    assert response.status_code == 200
    assert response.json()["url"] == "https://connect.stripe.test/express/login"
    assert fake_stripe.login_links == ["acct_test_1"]


async def test_thin_event_activates_photographer(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    photographer = await _make_photographer(db_session, photographer_user, stripe_account_id="acct_test_1")
    fake_stripe.account_state = _account(transfers="active", due=None)
    response = await _send_thin_event(
        async_client, "v2.core.account[configuration.recipient].capability_status_updated", "acct_test_1"
    )
    assert response.status_code == 200
    saved = await _reload(db_session, photographer)
    assert saved.stripe_transfers_enabled is True
    assert saved.stripe_payouts_enabled is True

    status = await async_client.get("/api/v1/photographer/stripe", headers=photographer_auth_headers)
    assert status.json()["status"] == "active"


async def test_snapshot_account_updated_needs_action(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    await _make_photographer(
        db_session,
        photographer_user,
        stripe_account_id="acct_test_1",
        stripe_details_submitted=True,
        stripe_transfers_enabled=True,
        stripe_payouts_enabled=True,
    )
    fake_stripe.account_state = _account(transfers="active", due="currently_due")
    response = await _send_webhook(async_client, "account.updated", {"id": "acct_test_1", "object": "account"})
    assert response.status_code == 200
    status = await async_client.get("/api/v1/photographer/stripe", headers=photographer_auth_headers)
    assert status.json()["status"] == "action_needed"


async def test_webhook_rejects_bad_signature(async_client, fake_stripe):
    thin = await _send_thin_event(
        async_client, "v2.core.account[requirements].updated", "acct_test_1", secret="whsec_wrong"
    )
    snapshot = await _send_webhook(async_client, "account.updated", {"id": "acct_x"}, secret="whsec_wrong")
    assert thin.status_code == 400
    assert snapshot.status_code == 400


async def test_webhook_unknown_account_is_acknowledged(async_client, fake_stripe):
    response = await _send_thin_event(async_client, "v2.core.account[requirements].updated", "acct_unknown")
    assert response.status_code == 200


async def test_onboarding_uses_fallback_email(async_client, db_session, make_jwt, fake_stripe):
    # A user record without email (e.g. no Clerk secret key locally): the frontend sends it
    headers = {"Authorization": f"Bearer {make_jwt({'sub': 'clerk_no_email'})}"}
    me = await async_client.get("/api/v1/me", headers=headers)
    user = await db_session.get(User, uuid.UUID(me.json()["id"]))
    user.role = UserRole.PHOTOGRAPHER
    await _make_photographer(db_session, user)

    missing = await async_client.post("/api/v1/photographer/stripe/onboarding-link", headers=headers)
    assert missing.status_code == 400
    assert fake_stripe.created_accounts == []

    response = await async_client.post(
        "/api/v1/photographer/stripe/onboarding-link", headers=headers, json={"email": "pg@example.com"}
    )
    assert response.status_code == 200
    params, _ = fake_stripe.created_accounts[0]
    assert params["contact_email"] == "pg@example.com"
