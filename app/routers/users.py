from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.integrations.clerk.auth import get_current_user
from app.models.user import User
from app.schemas.order import OrderResponse
from app.schemas.user import UserResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1/me", tags=["users"])


@router.get("", response_model=UserResponse)
async def get_my_profile(user: User = Depends(get_current_user)):
    return UserResponse.model_validate(user)


@router.get("/orders", response_model=list[OrderResponse])
async def get_my_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    orders = await service.list_user_orders(user.id)
    return [OrderResponse.model_validate(o) for o in orders]
