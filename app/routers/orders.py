import uuid

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import ConflictError, ExternalServiceError, ForbiddenError
from app.integrations.clerk.auth import get_current_user, require_role
from app.integrations.klarna.client import KlarnaClient
from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType, UserRole
from app.models.user import User
from app.schemas.order import OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])

_VALID_TRANSITIONS = {
    "capture": {OrderStatus.AUTHORIZED},
    "refund": {OrderStatus.CAPTURED},
    "cancel": {OrderStatus.AUTHORIZED},
}


async def get_klarna_client():
    settings = get_settings()
    client = KlarnaClient(
        api_url=settings.klarna_api_url,
        username=settings.klarna_username,
        password=settings.klarna_password,
    )
    try:
        yield client
    finally:
        await client.close()


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


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.user_id != user.id and user.role != UserRole.ADMIN:
        raise ForbiddenError("Not authorized to view this order")
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/capture", response_model=OrderResponse)
async def capture(
    order_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
    klarna: KlarnaClient = Depends(get_klarna_client),
):
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.status not in _VALID_TRANSITIONS["capture"]:
        raise ConflictError(f"Cannot capture order in {order.status} state")
    payload = {
        "captured_amount": order.amount,
        "description": f"Capture for order {order.id}",
    }
    if order.klarna_order_id:
        try:
            await klarna.capture(order.klarna_order_id, payload)
        except Exception as exc:
            await service.record_transaction(
                order_id,
                PaymentTransactionType.CAPTURE,
                PaymentTransactionStatus.FAILED,
                payload={
                    "klarna_order_id": order.klarna_order_id,
                    "klarna_capture_payload": payload,
                    "error": str(exc),
                },
            )
            raise _klarna_error(exc, "capture") from exc
    order = await service.update_order_status(order_id, OrderStatus.CAPTURED)
    await service.record_transaction(
        order_id,
        PaymentTransactionType.CAPTURE,
        PaymentTransactionStatus.SUCCESS,
        payload={"klarna_order_id": order.klarna_order_id, "klarna_capture_payload": payload}
        if order.klarna_order_id
        else None,
    )
    order = await service.get_order(order_id)
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/refund", response_model=OrderResponse)
async def refund(
    order_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
    klarna: KlarnaClient = Depends(get_klarna_client),
):
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.status not in _VALID_TRANSITIONS["refund"]:
        raise ConflictError(f"Cannot refund order in {order.status} state")
    payload = {
        "refunded_amount": order.amount,
        "description": f"Refund for order {order.id}",
    }
    if order.klarna_order_id:
        try:
            await klarna.refund(order.klarna_order_id, payload)
        except Exception as exc:
            await service.record_transaction(
                order_id,
                PaymentTransactionType.REFUND,
                PaymentTransactionStatus.FAILED,
                payload={
                    "klarna_order_id": order.klarna_order_id,
                    "klarna_refund_payload": payload,
                    "error": str(exc),
                },
            )
            raise _klarna_error(exc, "refund") from exc
    order = await service.update_order_status(order_id, OrderStatus.REFUNDED)
    await service.record_transaction(
        order_id,
        PaymentTransactionType.REFUND,
        PaymentTransactionStatus.SUCCESS,
        payload={"klarna_order_id": order.klarna_order_id, "klarna_refund_payload": payload}
        if order.klarna_order_id
        else None,
    )
    order = await service.get_order(order_id)
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel(
    order_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
    klarna: KlarnaClient = Depends(get_klarna_client),
):
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.status not in _VALID_TRANSITIONS["cancel"]:
        raise ConflictError(f"Cannot cancel order in {order.status} state")
    if order.klarna_order_id:
        try:
            await klarna.cancel(order.klarna_order_id)
        except Exception as exc:
            await service.record_transaction(
                order_id,
                PaymentTransactionType.CANCEL,
                PaymentTransactionStatus.FAILED,
                payload={"klarna_order_id": order.klarna_order_id, "error": str(exc)},
            )
            raise _klarna_error(exc, "cancel") from exc
    order = await service.update_order_status(order_id, OrderStatus.CANCELLED)
    await service.record_transaction(
        order_id,
        PaymentTransactionType.CANCEL,
        PaymentTransactionStatus.SUCCESS,
        payload={"klarna_order_id": order.klarna_order_id} if order.klarna_order_id else None,
    )
    order = await service.get_order(order_id)
    return OrderResponse.model_validate(order)
