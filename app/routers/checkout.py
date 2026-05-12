import uuid
from copy import deepcopy
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import BadRequestError, ConflictError, ExternalServiceError
from app.integrations.clerk.auth import ClerkAuth
from app.integrations.klarna.client import KlarnaClient
from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType
from app.models.user import User
from app.schemas.checkout import AuthorizeCheckoutRequest, CheckoutSessionResponse, CreateCheckoutSessionRequest
from app.schemas.order import OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1/checkout", tags=["checkout"])


async def get_klarna_client():
    settings = get_settings()
    if not settings.klarna_username or not settings.klarna_password:
        raise ExternalServiceError("Klarna credentials are not configured")

    client = KlarnaClient(
        api_url=settings.klarna_api_url,
        username=settings.klarna_username,
        password=settings.klarna_password,
    )
    try:
        yield client
    finally:
        await client.close()


async def _get_or_create_user(
    auth: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    if auth and auth.startswith("Bearer "):
        try:
            settings = get_settings()
            claims = ClerkAuth(settings.clerk_jwks_url).validate_token(auth[7:])
            from app.services.user_service import UserService

            user_service = UserService(db)
            user, _ = await user_service.get_or_create_by_clerk_id(
                clerk_user_id=claims["sub"],
                email=claims.get("email", ""),
            )
            return user
        except Exception:
            pass

    guest_email = "guest+checkout@gallopics.local"
    result = await db.execute(select(User).where(User.email == guest_email))
    guest = result.scalar_one_or_none()
    if not guest:
        guest = User(
            clerk_user_id=f"guest_{uuid.uuid4()}",
            email=guest_email,
        )
        db.add(guest)
        await db.flush()
        await db.refresh(guest)
    return guest


def _klarna_error(exc: Exception, action: str) -> ExternalServiceError:
    response = getattr(exc, "response", None)
    if isinstance(exc, httpx.HTTPStatusError) and response is not None:
        try:
            body = response.json()
        except ValueError:
            body = response.text[:500]
        return ExternalServiceError(
            f"Klarna {action} failed with status {response.status_code}: {body}"
        )
    return ExternalServiceError(f"Klarna {action} failed: {exc}")


def _build_klarna_session_payload(body: CreateCheckoutSessionRequest) -> dict[str, Any]:
    order_amount = sum(item.total_amount for item in body.line_items)
    order_tax_amount = sum(item.total_tax_amount for item in body.line_items)
    return {
        "acquiring_channel": "ECOMMERCE",
        "intent": "buy",
        "purchase_country": body.purchase_country.upper(),
        "purchase_currency": body.purchase_currency.upper(),
        "locale": body.locale,
        "order_amount": order_amount,
        "order_tax_amount": order_tax_amount,
        "order_lines": [
            {
                "type": item.type,
                "reference": item.reference or f"item_{index + 1}",
                "name": item.name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_rate": item.tax_rate,
                "total_amount": item.total_amount,
                "total_tax_amount": item.total_tax_amount,
            }
            for index, item in enumerate(body.line_items)
        ],
    }


def _find_session_payload(order) -> dict[str, Any] | None:
    for transaction in sorted(order.transactions, key=lambda txn: txn.created_at, reverse=True):
        payload = transaction.payload or {}
        if payload.get("klarna_session_payload") and payload.get("klarna_session_id"):
            return payload
    return None


def _capture_payload(order) -> dict[str, Any]:
    return {
        "captured_amount": order.amount,
        "description": f"Capture for order {order.id}",
    }


@router.post("/sessions", response_model=CheckoutSessionResponse)
async def create_session(
    body: CreateCheckoutSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    klarna: KlarnaClient = Depends(get_klarna_client),
):
    clerk_token = request.headers.get("authorization")
    user = await _get_or_create_user(auth=clerk_token, db=db)
    session_payload = _build_klarna_session_payload(body)

    service = OrderService(db)
    order = await service.create_order(
        user_id=user.id,
        amount=session_payload["order_amount"],
        currency=session_payload["purchase_currency"],
        idempotency_key=body.idempotency_key,
    )

    if order.amount != session_payload["order_amount"] or order.currency != session_payload["purchase_currency"]:
        raise ConflictError("Idempotency key was already used for a different checkout")

    order = await service.get_order(order.id)
    existing_session = _find_session_payload(order)
    if existing_session:
        return CheckoutSessionResponse(
            session_id=existing_session["klarna_session_id"],
            client_token=existing_session["klarna_client_token"],
            order_id=order.id,
        )

    try:
        klarna_response = await klarna.create_session(session_payload)
    except Exception as exc:
        raise _klarna_error(exc, "session creation") from exc

    await service.record_transaction(
        order.id,
        PaymentTransactionType.AUTHORIZATION,
        PaymentTransactionStatus.PENDING,
        payload={
            "klarna_session_id": klarna_response["session_id"],
            "klarna_client_token": klarna_response["client_token"],
            "klarna_session_payload": session_payload,
            "klarna_payment_method_categories": klarna_response.get("payment_method_categories", []),
        },
    )

    return CheckoutSessionResponse(
        session_id=klarna_response["session_id"],
        client_token=klarna_response["client_token"],
        order_id=order.id,
    )


@router.post("/authorize", response_model=OrderResponse)
async def authorize(
    body: AuthorizeCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    klarna: KlarnaClient = Depends(get_klarna_client),
):
    service = OrderService(db)
    order = await service.get_order(body.order_id)
    session_payload = _find_session_payload(order)
    if not session_payload:
        raise BadRequestError("Order does not have an active Klarna checkout session")

    order_payload = deepcopy(session_payload["klarna_session_payload"])
    order_payload["merchant_reference1"] = str(order.id)

    try:
        klarna_order = await klarna.create_order(body.authorization_token, order_payload)
    except Exception as exc:
        await service.record_transaction(
            order.id,
            PaymentTransactionType.AUTHORIZATION,
            PaymentTransactionStatus.FAILED,
            payload={
                "authorization_token": body.authorization_token,
                "klarna_order_payload": order_payload,
                "error": str(exc),
            },
        )
        raise _klarna_error(exc, "order creation") from exc

    await service.set_klarna_order_id(order.id, klarna_order["order_id"])
    order = await service.update_order_status(order.id, OrderStatus.AUTHORIZED)
    await service.record_transaction(
        order.id,
        PaymentTransactionType.AUTHORIZATION,
        PaymentTransactionStatus.SUCCESS,
        payload={
            "authorization_token": body.authorization_token,
            "klarna_order_payload": order_payload,
            "klarna_order_response": klarna_order,
        },
    )

    capture_payload = _capture_payload(order)
    try:
        await klarna.capture(klarna_order["order_id"], capture_payload)
    except Exception as exc:
        await service.record_transaction(
            order.id,
            PaymentTransactionType.CAPTURE,
            PaymentTransactionStatus.FAILED,
            payload={
                "klarna_order_id": klarna_order["order_id"],
                "klarna_capture_payload": capture_payload,
                "error": str(exc),
            },
        )
        raise _klarna_error(exc, "capture") from exc

    order = await service.update_order_status(order.id, OrderStatus.CAPTURED)
    await service.record_transaction(
        order.id,
        PaymentTransactionType.CAPTURE,
        PaymentTransactionStatus.SUCCESS,
        payload={
            "klarna_order_id": klarna_order["order_id"],
            "klarna_capture_payload": capture_payload,
        },
    )

    order = await service.get_order(order.id)
    return OrderResponse.model_validate(order)


@router.post("/callback/klarna")
async def klarna_callback(request: Request, db: AsyncSession = Depends(get_db)):
    await request.json()
    # In production, validate Klarna signature and update order
    return {"status": "received"}
