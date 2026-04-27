import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.integrations.clerk.auth import get_current_user
from app.models.user import User
from app.schemas.checkout import AuthorizeCheckoutRequest, CheckoutSessionResponse, CreateCheckoutSessionRequest
from app.schemas.order import OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1/checkout", tags=["checkout"])


@router.post("/sessions", response_model=CheckoutSessionResponse)
async def create_session(
    body: CreateCheckoutSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    total_amount = sum(item.total_amount for item in body.line_items)
    order = await service.create_order(
        user_id=user.id,
        amount=total_amount,
        idempotency_key=body.idempotency_key,
    )
    # In production, this would call KlarnaClient.create_session()
    return CheckoutSessionResponse(
        session_id=f"klarna_session_{order.id}",
        client_token=f"client_token_{order.id}",
        order_id=order.id,
    )


@router.post("/authorize", response_model=OrderResponse)
async def authorize(
    body: AuthorizeCheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType

    service = OrderService(db)
    order = await service.get_order(body.order_id)
    # In production, this would call KlarnaClient.create_order()
    order = await service.update_order_status(order.id, OrderStatus.AUTHORIZED)
    await service.record_transaction(
        order.id, PaymentTransactionType.AUTHORIZATION, PaymentTransactionStatus.SUCCESS,
        payload={"authorization_token": body.authorization_token},
    )
    order = await service.get_order(order.id)
    return OrderResponse.model_validate(order)


@router.post("/callback/klarna")
async def klarna_callback(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    # In production, validate Klarna signature and update order
    return {"status": "received"}
