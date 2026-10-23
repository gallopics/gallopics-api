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


async def test_upsert_and_get_photographer_profile(async_client, auth_headers, admin_auth_headers):
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

    # Not public until an admin approves the profile
    hidden = await async_client.get("/api/v1/photographers/alice-lind")
    assert hidden.status_code == 404
    hidden_by_id = await async_client.get(f"/api/v1/photographers/{profile['id']}/highlights")
    assert hidden_by_id.status_code == 404

    approved = await async_client.patch(
        f"/api/v1/admin/photographers/{profile['id']}",
        json={"status": "approved"},
        headers=admin_auth_headers,
    )
    assert approved.status_code == 200

    public_response = await async_client.get("/api/v1/photographers/alice-lind")
    assert public_response.status_code == 200
    assert public_response.json()["display_name"] == "Alice Lind"

    # Rejected again: hidden again
    rejected = await async_client.patch(
        f"/api/v1/admin/photographers/{profile['id']}",
        json={"status": "suspended"},
        headers=admin_auth_headers,
    )
    assert rejected.status_code == 200
    assert (await async_client.get("/api/v1/photographers/alice-lind")).status_code == 404


async def test_clerk_metadata_cannot_approve_photographer(async_client, make_jwt, admin_auth_headers):
    """Approval lives in our database; only an admin can set it (Clerk metadata is user-editable)."""
    headers = {"Authorization": f"Bearer {make_jwt({'sub': 'clerk_approval', 'email': 'pg@example.com'})}"}
    created = await async_client.put(
        "/api/v1/photographer/me",
        json={"slug": "approval-test", "display_name": "Approval Test"},
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["status"] == "pending"

    # A token claiming approval (as user-editable unsafe metadata could) changes nothing
    claims = {
        "sub": "clerk_approval",
        "email": "pg@example.com",
        "public_metadata": {"approvalStatus": "approved"},
        "unsafe_metadata": {"approvalStatus": "approved", "role": "admin"},
    }
    sneaky_headers = {"Authorization": f"Bearer {make_jwt(claims)}"}
    profile = await async_client.get("/api/v1/photographer/me", headers=sneaky_headers)
    assert profile.json()["status"] == "pending"
    me = await async_client.get("/api/v1/me", headers=sneaky_headers)
    assert me.json()["role"] == "photographer"

    # Pending photographers can't change anything yet
    blocked = await async_client.put("/api/v1/photographer/highlights", json={"photo_ids": []}, headers=headers)
    assert blocked.status_code == 403

    # An admin approves them
    listed = await async_client.get("/api/v1/admin/photographers?status=pending", headers=admin_auth_headers)
    assert listed.status_code == 200
    [pending] = [p for p in listed.json() if p["slug"] == "approval-test"]
    assert pending["email"] == "pg@example.com"
    assert pending["stripe_status"] == "not_connected"
    approved = await async_client.patch(
        f"/api/v1/admin/photographers/{pending['id']}", json={"status": "approved"}, headers=admin_auth_headers
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    allowed = await async_client.put("/api/v1/photographer/highlights", json={"photo_ids": []}, headers=headers)
    assert allowed.status_code == 200


async def test_rejected_photographer_is_blocked_until_approved(async_client, make_jwt, admin_auth_headers):
    """Rejecting a sign-up stores "suspended"; approving it later undoes a mistake."""
    headers = {"Authorization": f"Bearer {make_jwt({'sub': 'clerk_rejected', 'email': 'rejected@example.com'})}"}
    created = await async_client.put(
        "/api/v1/photographer/me", json={"slug": "rejected-test", "display_name": "Rejected Test"}, headers=headers
    )
    photographer_id = created.json()["id"]

    rejected = await async_client.patch(
        f"/api/v1/admin/photographers/{photographer_id}", json={"status": "suspended"}, headers=admin_auth_headers
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "suspended"
    assert (await async_client.get("/api/v1/photographer/me", headers=headers)).json()["status"] == "suspended"

    blocked = await async_client.put("/api/v1/photographer/highlights", json={"photo_ids": []}, headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Your photographer account was not approved"

    approved = await async_client.patch(
        f"/api/v1/admin/photographers/{photographer_id}", json={"status": "approved"}, headers=admin_auth_headers
    )
    assert approved.json()["status"] == "approved"
    allowed = await async_client.put("/api/v1/photographer/highlights", json={"photo_ids": []}, headers=headers)
    assert allowed.status_code == 200


async def test_only_admins_can_approve(async_client, make_jwt):
    headers = {"Authorization": f"Bearer {make_jwt({'sub': 'clerk_self', 'email': 'self@example.com'})}"}
    created = await async_client.put(
        "/api/v1/photographer/me", json={"slug": "self-approve", "display_name": "Self"}, headers=headers
    )
    response = await async_client.patch(
        f"/api/v1/admin/photographers/{created.json()['id']}", json={"status": "approved"}, headers=headers
    )
    assert response.status_code == 403
    assert (await async_client.get("/api/v1/admin/photographers", headers=headers)).status_code == 403
