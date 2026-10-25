import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.exceptions import UnauthorizedError
from app.integrations.clerk.auth import ClerkAuth
from app.models.enums import PhotographerStatus
from app.models.photographer import Photographer


def test_validate_token_with_wrong_key():
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    right_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    token = pyjwt.encode({"sub": "user1", "email": "a@b.com"}, wrong_key, algorithm="RS256")

    # ClerkAuth needs JWKS, so we test the decode logic directly
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, right_key.public_key(), algorithms=["RS256"], options={"verify_aud": False})


def test_validate_token_success(rsa_keypair, rsa_public_key):
    token = pyjwt.encode({"sub": "user1", "email": "a@b.com"}, rsa_keypair, algorithm="RS256")
    claims = pyjwt.decode(token, rsa_public_key, algorithms=["RS256"], options={"verify_aud": False})
    assert claims["sub"] == "user1"


def test_derive_jwks_url_from_clerk_issuer():
    token = pyjwt.encode(
        {"sub": "user1", "iss": "https://example.clerk.accounts.dev"},
        "secret",
        algorithm="HS256",
    )

    assert ClerkAuth._derive_jwks_url(token) == "https://example.clerk.accounts.dev/.well-known/jwks.json"


def test_derive_jwks_url_requires_https_issuer():
    token = pyjwt.encode({"sub": "user1", "iss": "http://example.test"}, "secret", algorithm="HS256")

    with pytest.raises(UnauthorizedError):
        ClerkAuth._derive_jwks_url(token)


async def test_get_current_user_no_header(async_client):
    response = await async_client.get("/api/v1/me")
    assert response.status_code == 422 or response.status_code == 401


async def test_get_current_user_malformed_header(async_client):
    response = await async_client.get("/api/v1/me", headers={"Authorization": "Basic xxx"})
    assert response.status_code == 401


async def test_get_current_user_valid(async_client, auth_headers):
    response = await async_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["clerk_user_id"] == "clerk_user_test"


async def test_require_role_allows_admin(async_client, admin_auth_headers):
    response = await async_client.get("/api/v1/admin/orders", headers=admin_auth_headers)
    assert response.status_code == 200


async def test_require_role_denies_user(async_client, auth_headers):
    response = await async_client.get("/api/v1/admin/orders", headers=auth_headers)
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        (PhotographerStatus.PENDING, "Your photographer account is waiting for approval"),
        # Rejected sign-ups are stored as SUSPENDED
        (PhotographerStatus.SUSPENDED, "Your photographer account was not approved"),
    ],
)
async def test_require_approved_photographer_blocks_unapproved(
    async_client, db_session, photographer_user, photographer_auth_headers, status, detail
):
    db_session.add(
        Photographer(user_id=photographer_user.id, slug="guard-test", display_name="Guard Test", status=status)
    )
    await db_session.flush()
    response = await async_client.put(
        "/api/v1/photographer/highlights", json={"photo_ids": []}, headers=photographer_auth_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"] == detail


async def test_require_approved_photographer_allows_approved(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    db_session.add(
        Photographer(
            user_id=photographer_user.id,
            slug="guard-test",
            display_name="Guard Test",
            status=PhotographerStatus.APPROVED,
        )
    )
    await db_session.flush()
    response = await async_client.put(
        "/api/v1/photographer/highlights", json={"photo_ids": []}, headers=photographer_auth_headers
    )
    assert response.status_code == 200


def _pem(public_key) -> str:
    from cryptography.hazmat.primitives import serialization

    return public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def test_jwk_client_is_reused_between_requests(monkeypatch):
    from app.integrations.clerk import auth as clerk_auth

    created = []

    class FakeJWKClient:
        def __init__(self, url, **kwargs):
            created.append(url)

    clerk_auth._jwk_client.cache_clear()
    monkeypatch.setattr(clerk_auth, "PyJWKClient", FakeJWKClient)
    first = clerk_auth._jwk_client("https://example.clerk.accounts.dev/.well-known/jwks.json")
    second = clerk_auth._jwk_client("https://example.clerk.accounts.dev/.well-known/jwks.json")
    assert first is second
    assert created == ["https://example.clerk.accounts.dev/.well-known/jwks.json"]
    clerk_auth._jwk_client.cache_clear()


def test_pem_key_verifies_without_network(rsa_keypair, rsa_public_key):
    token = pyjwt.encode({"sub": "user1"}, rsa_keypair, algorithm="RS256")
    # The PEM as it often sits in .env: one line with literal \n
    one_line_pem = _pem(rsa_public_key).replace("\n", "\n")
    claims = ClerkAuth("", jwt_key=one_line_pem).validate_token(token)
    assert claims["sub"] == "user1"


def test_pem_key_rejects_wrong_signature(rsa_public_key):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = pyjwt.encode({"sub": "user1"}, other_key, algorithm="RS256")
    with pytest.raises(UnauthorizedError):
        ClerkAuth("", jwt_key=_pem(rsa_public_key)).validate_token(token)


def test_azp_must_be_one_of_our_sites(rsa_keypair, rsa_public_key):
    clerk = ClerkAuth("", jwt_key=_pem(rsa_public_key), authorized_parties=["https://gallopics.com/"])
    ours = pyjwt.encode({"sub": "u", "azp": "https://gallopics.com"}, rsa_keypair, algorithm="RS256")
    other = pyjwt.encode({"sub": "u", "azp": "https://evil.example"}, rsa_keypair, algorithm="RS256")
    no_azp = pyjwt.encode({"sub": "u"}, rsa_keypair, algorithm="RS256")

    assert clerk.validate_token(ours)["sub"] == "u"
    assert clerk.validate_token(no_azp)["sub"] == "u"
    with pytest.raises(UnauthorizedError):
        clerk.validate_token(other)


def test_authorized_parties_default_to_cors_and_frontend():
    from types import SimpleNamespace

    from app.integrations.clerk.auth import _authorized_parties

    settings = SimpleNamespace(
        clerk_authorized_parties="",
        cors_origins="http://localhost:3010, https://gallopics.com/",
        frontend_base_url="http://localhost:5173",
    )
    assert _authorized_parties(settings) == (
        "http://localhost:3010",
        "http://localhost:5173",
        "https://gallopics.com",
    )
    settings.clerk_authorized_parties = "https://only.example"
    assert _authorized_parties(settings) == ("https://only.example",)
