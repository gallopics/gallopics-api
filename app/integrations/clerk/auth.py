import ssl
from collections.abc import Iterable
from functools import lru_cache

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


@lru_cache(maxsize=8)
def _jwk_client(jwks_url: str) -> PyJWKClient:
    """One client per JWKS URL, kept for the life of the process.

    Its key cache then survives between requests, like the JWKS cache in Clerk's own SDKs.
    (A new client per request downloaded Clerk's keys on every logged-in call.)
    """
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return PyJWKClient(jwks_url, cache_keys=True, ssl_context=ssl_context)


class ClerkAuth:
    """Verifies Clerk session tokens (RS256).

    - jwt_key: Clerk's PEM public key (Dashboard → API keys) for networkless verification;
      without it the keys come from the JWKS endpoint (downloaded once, then cached).
    - authorized_parties: our own site origins; a token whose `azp` claim names another site
      is rejected, as Clerk recommends (CSRF / leaked-cookie protection).
    """

    def __init__(self, jwks_url: str, jwt_key: str = "", authorized_parties: Iterable[str] = ()):
        self.jwks_url = jwks_url
        # .env files often hold the PEM on one line, with literal backslash-n for line breaks
        self.jwt_key = jwt_key.replace("\\n", "\n").strip()
        self.authorized_parties = {party.rstrip("/") for party in authorized_parties if party}

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
        try:
            if self.jwt_key:
                key = self.jwt_key
            else:
                jwk_client = _jwk_client(self.jwks_url or self._derive_jwks_url(token))
                key = jwk_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except (jwt.InvalidTokenError, PyJWKClientError, ValueError) as e:
            raise UnauthorizedError(f"Invalid token: {e}") from e

        azp = claims.get("azp")
        if azp and self.authorized_parties and azp.rstrip("/") not in self.authorized_parties:
            raise UnauthorizedError("Token was issued for another site")
        return claims


def _authorized_parties(settings) -> tuple[str, ...]:
    if settings.clerk_authorized_parties:
        parties = settings.clerk_authorized_parties.split(",")
    else:
        parties = [*settings.cors_origins.split(","), settings.frontend_base_url]
    return tuple(sorted({party.strip().rstrip("/") for party in parties if party.strip()}))


@lru_cache(maxsize=8)
def _clerk_auth(jwks_url: str, jwt_key: str, authorized_parties: tuple[str, ...]) -> ClerkAuth:
    return ClerkAuth(jwks_url, jwt_key, authorized_parties)


def get_clerk_auth() -> ClerkAuth:
    """The shared verifier for the current settings."""
    settings = get_settings()
    return _clerk_auth(settings.clerk_jwks_url, settings.clerk_jwt_key, _authorized_parties(settings))


async def _fetch_clerk_email(clerk_user_id: str, secret_key: str) -> str:
    """The user's primary email from Clerk's API (only needed the first time we see a user)."""
    if not secret_key:
        return ""

    async with httpx.AsyncClient(
        base_url="https://api.clerk.com",
        headers={"Authorization": f"Bearer {secret_key}"},
        timeout=5,
    ) as client:
        response = await client.get(f"/v1/users/{clerk_user_id}")
        response.raise_for_status()
        user = response.json()

    for address in user.get("email_addresses", []):
        if address.get("id") == user.get("primary_email_address_id"):
            return address.get("email_address", "")
    return ""


def _email_from_claims(claims: dict) -> str:
    """An email in the token itself (e.g. added through Clerk's session token template)."""
    email = claims.get("email")
    if isinstance(email, str) and email:
        return email
    addresses = claims.get("email_addresses", [])
    if addresses and isinstance(addresses[0], dict):
        return addresses[0].get("email_address", "") or ""
    return ""


async def get_current_user(
    authorization: str = Header(alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """The signed-in user, from our database.

    Roles and photographer approval live in our database only (set by admins in the admin
    pages); Clerk metadata is never trusted for access, since users can edit parts of it.
    Clerk's API is only asked for the email of a user we have no email for yet.
    """
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("Invalid authorization header")
    claims = get_clerk_auth().validate_token(authorization[7:])
    clerk_user_id = claims["sub"]

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user and user.email:
        return user

    email = _email_from_claims(claims)
    if not email:
        settings = get_settings()
        try:
            email = await _fetch_clerk_email(clerk_user_id, settings.clerk_secret_key)
        except httpx.HTTPError:
            email = ""

    if user:
        if email:
            user.email = email
            await db.flush()
        return user

    user, _ = await UserService(db).get_or_create_by_clerk_id(clerk_user_id=clerk_user_id, email=email)
    return user


def require_role(*roles: UserRole):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("Insufficient permissions")
        return user
    return _check


async def require_approved_photographer(
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
) -> User:
    """A photographer an admin has approved; needed for anything that books, uploads or sells."""
    result = await db.execute(select(Photographer).where(Photographer.user_id == user.id))
    photographer = result.scalar_one_or_none()
    # SUSPENDED is what admins set when they reject a sign-up
    if photographer and photographer.status == PhotographerStatus.SUSPENDED:
        raise ForbiddenError("Your photographer account was not approved")
    if not photographer or photographer.status != PhotographerStatus.APPROVED:
        raise ForbiddenError("Your photographer account is waiting for approval")
    return user
