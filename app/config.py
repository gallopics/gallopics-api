from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App
    app_name: str = "Gallopics API"
    app_version: str = "1.0.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    api_public_base_url: str = ""
    cors_origins: str = "http://localhost:5173,https://gallopics.com,https://www.gallopics.com"
    max_upload_file_size_mb: int = 100

    # Database
    database_url: str = "postgresql+asyncpg://localhost/gallopics_dev"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Clerk Auth
    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""
    clerk_jwks_url: str = ""
    # Optional: Clerk's PEM public key (Dashboard → API keys) to verify tokens without network calls
    clerk_jwt_key: str = ""
    # Sites allowed in a token's `azp` claim (comma-separated); empty = CORS_ORIGINS + FRONTEND_BASE_URL
    clerk_authorized_parties: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Signing secret of the Connect webhook (events from photographers' accounts);
    # empty = same as STRIPE_WEBHOOK_SECRET (e.g. one `stripe listen` locally)
    stripe_connect_webhook_secret: str = ""
    # Gallopics' cut of each photo sale, in percent
    platform_commission_percent: int = 25
    # Where Stripe Checkout sends the buyer back to
    frontend_base_url: str = "http://localhost:5173"

    # Klarna (no longer used; kept until KLARNA_* is removed from every .env)
    klarna_api_url: str = "https://api.playground.klarna.com"
    klarna_username: str = ""
    klarna_password: str = ""

    # Transactional email
    transactional_email_enabled: bool = False
    resend_api_url: str = "https://api.resend.com"
    resend_api_key: str = ""
    transactional_email_from: str = "Gallopics <onboarding@resend.dev>"
    transactional_email_reply_to: str = ""

    # Storage
    storage_backend: str = "local"
    storage_local_path: str = "./uploads"
    storage_s3_bucket: str = ""
    storage_s3_region: str = ""
    storage_s3_access_key: str = ""
    storage_s3_secret_key: str = ""
    storage_s3_endpoint_url: str = ""

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # TDB
    tdb_base_url: str = ""

    # Equipe
    equipe_base_url: str = "https://online.equipe.com/api/v1"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
