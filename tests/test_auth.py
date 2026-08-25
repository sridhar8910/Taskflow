"""
Auth endpoint tests:
- POST /auth/signup
- POST /auth/login
- GET /me (protected stub)
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_signup_success(client: AsyncClient):
    resp = await client.post(
        "/auth/signup", json={"email": "alice@example.com", "password": "securepass1"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert "id" in body
    # Password must never appear in any response
    assert "password" not in body
    assert "hashed_password" not in body


@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient):
    payload = {"email": "bob@example.com", "password": "securepass1"}
    r1 = await client.post("/auth/signup", json=payload)
    assert r1.status_code == 201

    r2 = await client.post("/auth/signup", json=payload)
    assert r2.status_code == 400
    assert "already registered" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_signup_short_password(client: AsyncClient):
    resp = await client.post(
        "/auth/signup", json={"email": "short@example.com", "password": "abc"}
    )
    assert resp.status_code == 422  # Pydantic validation


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    # Create user first
    await client.post(
        "/auth/signup", json={"email": "charlie@example.com", "password": "securepass1"}
    )

    resp = await client.post(
        "/auth/login", json={"email": "charlie@example.com", "password": "securepass1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    # Password must not leak
    assert "password" not in body
    assert "hashed_password" not in body


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/auth/signup", json={"email": "dave@example.com", "password": "securepass1"}
    )

    resp = await client.post(
        "/auth/login", json={"email": "dave@example.com", "password": "wrongpass"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "securepass1"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_no_token(client: AsyncClient):
    resp = await client.get("/me")
    # FastAPI's HTTPBearer returns 401/403 when Authorization header is missing
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_protected_route_invalid_token(client: AsyncClient):
    resp = await client.get("/me", headers={"Authorization": "Bearer notavalidtoken"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_valid_token(client: AsyncClient):
    # Sign up and log in
    await client.post(
        "/auth/signup", json={"email": "eve@example.com", "password": "securepass1"}
    )
    login_resp = await client.post(
        "/auth/login", json={"email": "eve@example.com", "password": "securepass1"}
    )
    token = login_resp.json()["access_token"]

    resp = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "eve@example.com"
