import ssl

import certifi
import httpx
import jwt
from fastapi import Depends, Header
from jwt import PyJWKClient, PyJWKClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import ForbiddenError, UnauthorizedError
from app.models.enums import PhotographerStatus, UserRole
from app.models.photographer import Photographer
from app.models.user import User
from app.services.user_service import UserService


class ClerkAuth:
    def __init__(self, jwks_url: str):
        self.jwks_url = jwks_url
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())
        self._jwk_client = self._build_jwk_client(jwks_url) if jwks_url else None

    def _build_jwk_client(self, jwks_url: str) -> PyJWKClient:
        return PyJWKClient(jwks_url, cache_keys=True, ssl_context=self._ssl_context)

    @staticmethod
    def _derive_jwks_url(token: str) -> str:
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.DecodeError as e:
            raise UnauthorizedError(f"Invalid token: {e}") from e

        issuer = claims.get("iss")
        if not isinstance(issuer, str) or not issuer.startswith("https://"):
            raise UnauthorizedError("Invalid token issuer")

        return f"{issuer.rstrip('/')}/.well-known/jwks.json"

    def validate_token(self, token: str) -> dict:
        jwk_client = self._jwk_client or self._build_jwk_client(self._derive_jwks_url(token))
        try:
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except (jwt.InvalidTokenError, PyJWKClientError, ValueError) as e:
            raise UnauthorizedError(f"Invalid token: {e}") from e


def _metadata_value(claims: dict, key: str) -> str | None:
    for container_key in (
        "public_metadata",
        "unsafe_metadata",
        "private_metadata",
        "metadata",
    ):
        container = claims.get(container_key)
        if isinstance(container, dict) and isinstance(container.get(key), str):
            return container[key]

    value = claims.get(key)
    return value if isinstance(value, str) else None


def _clerk_approval_status(claims: dict) -> PhotographerStatus | None:
    status = _metadata_value(claims, "approvalStatus") or _metadata_value(
        claims, "approval_status"
    )
    normalized = status.lower() if status else None

    if normalized == "approved":
        return PhotographerStatus.APPROVED
    if normalized == "pending":
        return PhotographerStatus.PENDING
    if normalized == "suspended":
        return PhotographerStatus.SUSPENDED

    return None


async def _fetch_clerk_user_claims(clerk_user_id: str, secret_key: str) -> dict:
    if not secret_key:
        return {}

    async with httpx.AsyncClient(
        base_url="https://api.clerk.com",
        headers={"Authorization": f"Bearer {secret_key}"},
        timeout=5,
    ) as client:
        response = await client.get(f"/v1/users/{clerk_user_id}")
        response.raise_for_status()
        user = response.json()

    email = ""
    for address in user.get("email_addresses", []):
        if address.get("id") == user.get("primary_email_address_id"):
            email = address.get("email_address", "")
            break

    return {
        "email": email,
        "public_metadata": user.get("public_metadata") or {},
        "unsafe_metadata": user.get("unsafe_metadata") or {},
        "private_metadata": user.get("private_metadata") or {},
    }


async def get_current_user(
    authorization: str = Header(alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("Invalid authorization header")
    token = authorization[7:]
    settings = get_settings()
    clerk = ClerkAuth(settings.clerk_jwks_url)
    claims = clerk.validate_token(token)
    clerk_claims = {}
    if settings.clerk_secret_key:
        try:
            clerk_claims = await _fetch_clerk_user_claims(
                claims["sub"], settings.clerk_secret_key
            )
        except httpx.HTTPError:
            clerk_claims = {}

    user_service = UserService(db)
    email = clerk_claims.get("email") or claims.get("email", "")
    if not email:
        addresses = claims.get("email_addresses", [])
        if addresses and isinstance(addresses[0], dict):
            email = addresses[0].get("email_address", "")
    user, _ = await user_service.get_or_create_by_clerk_id(
        clerk_user_id=claims["sub"],
        email=email,
    )
    clerk_status = _clerk_approval_status({**claims, **clerk_claims})
    if clerk_status:
        result = await db.execute(
            select(Photographer).where(Photographer.user_id == user.id)
        )
        photographer = result.scalar_one_or_none()
        if photographer:
            photographer.status = clerk_status
            await db.flush()
    return user


def require_role(*roles: UserRole):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("Insufficient permissions")
        return user
    return _check
