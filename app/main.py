from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.config import get_settings
from app.database import create_schema
from app.exceptions import GallopicsException
from app.middleware.error_handler import gallopics_exception_handler, validation_exception_handler
from app.middleware.logging import RequestLoggingMiddleware, setup_logging
from app.routers.admin import router as admin_router
from app.routers.checkout import router as checkout_router
from app.routers.events import router as events_router
from app.routers.gallery import router as gallery_router
from app.routers.health import router as health_router
from app.routers.integrations import router as integrations_router
from app.routers.orders import router as orders_router
from app.routers.photographer import router as photographer_router
from app.routers.users import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    import structlog

    logger = structlog.get_logger()
    await logger.ainfo("startup", app=app.title)
    await create_schema()
    yield
    await logger.ainfo("shutdown", app=app.title)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.debug)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)

    app.add_exception_handler(GallopicsException, gallopics_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.include_router(health_router)
    app.include_router(events_router)
    app.include_router(integrations_router)
    app.include_router(users_router)
    app.include_router(checkout_router)
    app.include_router(orders_router)
    app.include_router(admin_router)
    app.include_router(gallery_router)
    app.include_router(photographer_router)

    return app


app = create_app()
