async def test_get_profile_unauthenticated(async_client):
    response = await async_client.get("/api/v1/me")
    assert response.status_code in (401, 422)


async def test_get_profile_authenticated(async_client, auth_headers):
    response = await async_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"


async def test_get_my_orders_empty(async_client, auth_headers):
    response = await async_client.get("/api/v1/me/orders", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_upsert_and_get_photographer_profile(async_client, auth_headers):
    body = {
        "slug": "alice-lind",
        "display_name": "Alice Lind",
        "city": "Stockholm",
        "country": "SE",
        "avatar_url": "https://example.com/avatar.jpg",
        "phone": "+46701234567",
        "is_available_to_hire": False,
    }

    upsert_response = await async_client.put(
        "/api/v1/photographer/me",
        json=body,
        headers=auth_headers,
    )
    assert upsert_response.status_code == 200
    profile = upsert_response.json()
    assert profile["slug"] == "alice-lind"
    assert profile["display_name"] == "Alice Lind"
    assert profile["status"] == "pending"

    me_response = await async_client.get("/api/v1/me", headers=auth_headers)
    assert me_response.status_code == 200
    assert me_response.json()["role"] == "photographer"

    public_response = await async_client.get("/api/v1/photographers/alice-lind")
    assert public_response.status_code == 200
    assert public_response.json()["display_name"] == "Alice Lind"


async def test_clerk_approval_metadata_syncs_photographer_status(
    async_client,
    make_jwt,
):
    base_headers = {
        "Authorization": f"Bearer {make_jwt({'sub': 'clerk_approval_sync', 'email': 'sync@example.com'})}"
    }
    create_response = await async_client.put(
        "/api/v1/photographer/me",
        json={"slug": "approval-sync", "display_name": "Approval Sync"},
        headers=base_headers,
    )
    assert create_response.status_code == 200
    assert create_response.json()["status"] == "pending"

    approved_token = make_jwt(
        {
            'sub': 'clerk_approval_sync',
            'email': 'sync@example.com',
            'public_metadata': {'approvalStatus': 'approved'},
        }
    )
    approved_headers = {"Authorization": f"Bearer {approved_token}"}
    me_response = await async_client.get("/api/v1/me", headers=approved_headers)
    assert me_response.status_code == 200

    profile_response = await async_client.get(
        "/api/v1/photographer/me",
        headers=approved_headers,
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["status"] == "approved"
