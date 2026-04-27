import uuid

import pytest

from app.exceptions import NotFoundError
from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType
from app.models.user import User
from app.services.order_service import OrderService
from tests.factories import make_user


@pytest.fixture
async def user(db_session):
    u = User(**make_user())
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.fixture
def service(db_session):
    return OrderService(db_session)


async def test_create_order(service, user):
    order = await service.create_order(user.id, 5000)
    assert order.amount == 5000
    assert order.status == OrderStatus.PENDING
    assert order.user_id == user.id


async def test_create_order_idempotency(service, user):
    o1 = await service.create_order(user.id, 5000, idempotency_key="key-1")
    o2 = await service.create_order(user.id, 5000, idempotency_key="key-1")
    assert o1.id == o2.id


async def test_get_order(service, user):
    order = await service.create_order(user.id, 3000)
    found = await service.get_order(order.id)
    assert found.id == order.id


async def test_get_order_not_found(service):
    with pytest.raises(NotFoundError):
        await service.get_order(uuid.uuid4())


async def test_list_user_orders(service, user):
    await service.create_order(user.id, 1000)
    await service.create_order(user.id, 2000)
    orders = await service.list_user_orders(user.id)
    assert len(orders) == 2


async def test_update_order_status(service, user):
    order = await service.create_order(user.id, 5000)
    updated = await service.update_order_status(order.id, OrderStatus.AUTHORIZED)
    assert updated.status == OrderStatus.AUTHORIZED


async def test_record_transaction(service, user):
    order = await service.create_order(user.id, 5000)
    txn = await service.record_transaction(
        order.id, PaymentTransactionType.AUTHORIZATION, PaymentTransactionStatus.SUCCESS
    )
    assert txn.order_id == order.id
    assert txn.type == PaymentTransactionType.AUTHORIZATION
