import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import stripe
from sqlalchemy import select

from app.config import get_settings
from app.integrations.stripe.client import get_stripe_client
from app.main import app
from app.models.enums import PhotographerStatus, PhotoStatus, PhotoVisibility, UserRole
from app.models.event import Event
from app.models.photographer import Photo, Photographer, PhotoPurchase
from app.models.user import User
from app.services.payout_service import split_amount
from tests.factories import make_event

WEBHOOK_SECRET = "whsec_test_payouts"
RECEIPT_PATH = "app.services.checkout_service.TransactionalEmailService.send_purchase_receipt"
CONNECTED = {
    "stripe_details_submitted": True,
    "stripe_transfers_enabled": True,
    "stripe_payouts_enabled": True,
    "stripe_requirements_due": False,
}


class FakeStripe:
    """Fakes Stripe's network calls; webhook signatures are checked by the real library."""

    def __init__(self):
        self.sessions = []
        self.transfers = []
        self.reversals = []
        self.refunds = []
        self.fail_transfers = False
        self.account_state = None
        self._real = stripe.StripeClient("sk_test_dummy")
        fake = self

        async def create_session(params, options=None):
            fake.sessions.append(params)
            session_id = f"cs_test_{len(fake.sessions)}"
            return SimpleNamespace(id=session_id, url=f"https://checkout.stripe.test/{session_id}")

        async def retrieve_payment_intent(intent_id, params=None, options=None):
            return SimpleNamespace(id=intent_id, latest_charge="ch_test_1")

        async def create_transfer(params, options=None):
            if fake.fail_transfers:
                raise stripe.InvalidRequestError("Insufficient funds", None)
            fake.transfers.append((params, options))
            return SimpleNamespace(id=f"tr_test_{len(fake.transfers)}")

        async def create_reversal(transfer_id, params=None, options=None):
            fake.reversals.append(transfer_id)
            return SimpleNamespace(id=f"trr_{transfer_id}")

        async def create_refund(params, options=None):
            fake.refunds.append(params)
            return SimpleNamespace(id="re_test_1")

        async def retrieve_account(account_id, params=None, options=None):
            return fake.account_state

        self.v1 = SimpleNamespace(
            checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create_session)),
            payment_intents=SimpleNamespace(retrieve_async=retrieve_payment_intent),
            transfers=SimpleNamespace(
                create_async=create_transfer,
                reversals=SimpleNamespace(create_async=create_reversal),
            ),
            refunds=SimpleNamespace(create_async=create_refund),
        )
        self.v2 = SimpleNamespace(core=SimpleNamespace(accounts=SimpleNamespace(retrieve_async=retrieve_account)))

    def construct_event(self, payload, sig_header, secret):
        return self._real.construct_event(payload, sig_header, secret)


@pytest.fixture
def fake_stripe(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_CONNECT_WEBHOOK_SECRET", "")  # ignore a local .env value
    monkeypatch.setenv("PLATFORM_COMMISSION_PERCENT", "25")
    get_settings.cache_clear()
    fake = FakeStripe()
    app.dependency_overrides[get_stripe_client] = lambda: fake
    with patch(RECEIPT_PATH, new_callable=AsyncMock, return_value={"status": "skipped"}):
        yield fake
    get_settings.cache_clear()


async def _photographer(db_session, user=None, slug="pg-one", **fields):
    if user is None:
        user = User(clerk_user_id=f"clerk_{slug}", email=f"{slug}@example.com", role=UserRole.PHOTOGRAPHER)
        db_session.add(user)
        await db_session.flush()
    photographer = Photographer(
        user_id=user.id,
        slug=slug,
        display_name=slug,
        status=PhotographerStatus.APPROVED,
        **fields,
    )
    db_session.add(photographer)
    await db_session.flush()
    return photographer


async def _photo(db_session, photographer, event=None):
    if event is None:
        event = Event(**make_event(name="Payout Event"))
        db_session.add(event)
        await db_session.flush()
    photo = Photo(
        event_id=event.id,
        photographer_id=photographer.id,
        storage_key_original="originals/photo.jpg",
        price=10000,
        status=PhotoStatus.READY,
        visibility=PhotoVisibility.PUBLISHED,
    )
    db_session.add(photo)
    await db_session.flush()
    return photo


async def _buy(async_client, photos, quality="high"):
    """Checkout + the paid webhook; returns the order id."""
    response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={
            "items": [{"photo_id": str(photo.id), "quality": quality} for photo in photos],
            "customer_email": "buyer@example.com",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    amount = 99900 * len(photos)
    payload = json.dumps(
        {
            "id": "evt_paid",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": data["session_id"],
                    "object": "checkout.session",
                    "payment_status": "paid",
                    "amount_total": amount,
                    "currency": "sek",
                    "payment_intent": "pi_test_1",
                }
            },
        }
    )
    timestamp = int(time.time())
    signature = hmac.new(WEBHOOK_SECRET.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    webhook = await async_client.post(
        "/api/v1/checkout/webhook/stripe",
        content=payload,
        headers={"stripe-signature": f"t={timestamp},v1={signature}", "content-type": "application/json"},
    )
    assert webhook.status_code == 200
    return data["order_id"]


async def _purchases(db_session):
    result = await db_session.execute(select(PhotoPurchase).execution_options(populate_existing=True))
    return list(result.scalars())


def test_split_amount_rounds_share_down():
    assert split_amount(99900, 25) == (74925, 24975)
    assert split_amount(101, 25) == (75, 26)
    assert split_amount(49900, 0) == (49900, 0)


async def test_sale_transfers_share_to_connected_photographer(async_client, db_session, fake_stripe):
    photographer = await _photographer(db_session, stripe_account_id="acct_pg1", **CONNECTED)
    photo = await _photo(db_session, photographer)

    order_id = await _buy(async_client, [photo])

    [purchase] = await _purchases(db_session)
    assert purchase.photographer_id == photographer.id
    assert (purchase.photographer_amount, purchase.platform_fee) == (74925, 24975)
    assert purchase.payout_status == "transferred"
    assert purchase.stripe_transfer_id == "tr_test_1"

    params, options = fake_stripe.transfers[0]
    assert params["amount"] == 74925
    assert params["currency"] == "sek"
    assert params["destination"] == "acct_pg1"
    assert params["source_transaction"] == "ch_test_1"
    assert params["transfer_group"] == f"order_{order_id}"
    assert options["idempotency_key"] == f"transfer-{order_id}-{photographer.id}"


async def test_unconnected_photographer_is_paid_after_connecting(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    photographer = await _photographer(db_session, user=photographer_user, stripe_account_id="acct_pg1")
    photo = await _photo(db_session, photographer)

    await _buy(async_client, [photo])
    [purchase] = await _purchases(db_session)
    assert purchase.payout_status == "owed"
    assert fake_stripe.transfers == []

    sales = (await async_client.get("/api/v1/photographer/sales", headers=photographer_auth_headers)).json()
    assert sales["totals"]["owed"] == 74925
    assert sales["totals"]["transferred"] == 0

    # Stripe now reports the account as active (they finished onboarding)
    fake_stripe.account_state = stripe.StripeObject.construct_from(
        {
            "id": "acct_pg1",
            "configuration": {
                "recipient": {"capabilities": {"stripe_balance": {"stripe_transfers": {"status": "active"}}}}
            },
            "requirements": {"summary": {"minimum_deadline": None}},
        },
        "sk_test_dummy",
    )
    status = await async_client.get("/api/v1/photographer/stripe?refresh=true", headers=photographer_auth_headers)
    assert status.json()["status"] == "active"

    [purchase] = await _purchases(db_session)
    assert purchase.payout_status == "transferred"
    assert fake_stripe.transfers[0][0]["amount"] == 74925

    sales = (await async_client.get("/api/v1/photographer/sales", headers=photographer_auth_headers)).json()
    assert sales["totals"] == {
        "count": 1,
        "amount": 99900,
        "photographer_amount": 74925,
        "transferred": 74925,
        "owed": 0,
    }
    assert sales["items"][0]["payout_status"] == "transferred"
    assert sales["commission_percent"] == 25


async def test_failed_transfer_is_retried(
    async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe
):
    photographer = await _photographer(
        db_session, user=photographer_user, stripe_account_id="acct_pg1", **CONNECTED
    )
    photo = await _photo(db_session, photographer)
    fake_stripe.fail_transfers = True

    await _buy(async_client, [photo])
    [purchase] = await _purchases(db_session)
    assert purchase.payout_status == "failed"

    fake_stripe.fail_transfers = False
    fake_stripe.account_state = stripe.StripeObject.construct_from(
        {
            "id": "acct_pg1",
            "configuration": {
                "recipient": {"capabilities": {"stripe_balance": {"stripe_transfers": {"status": "active"}}}}
            },
            "requirements": {"summary": {"minimum_deadline": None}},
        },
        "sk_test_dummy",
    )
    await async_client.get("/api/v1/photographer/stripe?refresh=true", headers=photographer_auth_headers)
    [purchase] = await _purchases(db_session)
    assert purchase.payout_status == "transferred"


async def test_one_transfer_per_photographer_in_an_order(async_client, db_session, fake_stripe):
    first = await _photographer(db_session, slug="pg-a", stripe_account_id="acct_a", **CONNECTED)
    second = await _photographer(db_session, slug="pg-b", stripe_account_id="acct_b", **CONNECTED)
    photo_a1 = await _photo(db_session, first)
    photo_a2 = await _photo(db_session, first)
    photo_b = await _photo(db_session, second)

    await _buy(async_client, [photo_a1, photo_a2, photo_b])

    amounts = {params["destination"]: params["amount"] for params, _ in fake_stripe.transfers}
    assert amounts == {"acct_a": 74925 * 2, "acct_b": 74925}


async def test_refund_reverses_transfers(async_client, db_session, admin_auth_headers, fake_stripe):
    photographer = await _photographer(db_session, stripe_account_id="acct_pg1", **CONNECTED)
    photo = await _photo(db_session, photographer)
    order_id = await _buy(async_client, [photo])

    response = await async_client.post(f"/api/v1/orders/{order_id}/refund", headers=admin_auth_headers)
    assert response.status_code == 200
    assert fake_stripe.reversals == ["tr_test_1"]
    [purchase] = await _purchases(db_session)
    assert purchase.payout_status == "reversed"


async def test_refund_cancels_owed_share(
    async_client, db_session, photographer_user, photographer_auth_headers, admin_auth_headers, fake_stripe
):
    photographer = await _photographer(db_session, user=photographer_user, stripe_account_id="acct_pg1")
    photo = await _photo(db_session, photographer)
    order_id = await _buy(async_client, [photo])

    await async_client.post(f"/api/v1/orders/{order_id}/refund", headers=admin_auth_headers)
    assert fake_stripe.reversals == []
    [purchase] = await _purchases(db_session)
    assert purchase.payout_status == "cancelled"

    sales = (await async_client.get("/api/v1/photographer/sales", headers=photographer_auth_headers)).json()
    assert sales["items"][0]["refunded"] is True
    assert sales["totals"]["count"] == 0
    assert sales["totals"]["owed"] == 0
