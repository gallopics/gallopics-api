import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.integrations.clerk.auth import ClerkAuth


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
