import jwt
from fastapi import Depends, Header
from jwt import PyJWKClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import ForbiddenError, UnauthorizedError
from app.models.enums import UserRole
from app.models.user import User
from app.services.user_service import UserService


class ClerkAuth:
    def __init__(self, jwks_url: str):
        self._jwk_client = PyJWKClient(jwks_url, cache_keys=True)

    def validate_token(self, token: str) -> dict:
        signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )


async def get_current_user(
    authorization: str = Header(alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("Invalid authorization header")
    token = authorization[7:]
    settings = get_settings()
    clerk = ClerkAuth(settings.clerk_jwks_url)
    try:
        claims = clerk.validate_token(token)
    except jwt.InvalidTokenError as e:
        raise UnauthorizedError(f"Invalid token: {e}")
    user_service = UserService(db)
    email = claims.get("email", "")
    if not email:
        addresses = claims.get("email_addresses", [])
        if addresses and isinstance(addresses[0], dict):
            email = addresses[0].get("email_address", "")
    user, _ = await user_service.get_or_create_by_clerk_id(
        clerk_user_id=claims["sub"],
        email=email,
    )
    return user


def require_role(*roles: UserRole):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("Insufficient permissions")
        return user
    return _check
