"""
Project CRUD + authorization tests.
Key scenarios:
- Full CRUD happy path
- 404 for nonexistent project
- 403 when user B touches user A's project (cross-user boundary)
- 401 on unauthenticated requests
"""

import pytest
from httpx import AsyncClient

from tests.conftest import create_user_and_token

# ── Helpers ───────────────────────────────────────────────────────────────────


async def create_project(
    client: AsyncClient, name: str = "My Project", description: str = "desc"
) -> dict:
    resp = await client.post(
        "/projects", json={"name": name, "description": description}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── CRUD happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_project(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/projects", json={"name": "Alpha", "description": "First project"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Alpha"
    assert body["description"] == "First project"
    assert "id" in body
    assert "owner_id" in body


@pytest.mark.asyncio
async def test_list_projects(auth_client: AsyncClient):
    await create_project(auth_client, "Project A")
    await create_project(auth_client, "Project B")

    resp = await auth_client.get("/projects")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "Project A" in names
    assert "Project B" in names


@pytest.mark.asyncio
async def test_get_project(auth_client: AsyncClient):
    created = await create_project(auth_client, "Beta")
    project_id = created["id"]

    resp = await auth_client.get(f"/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == project_id


@pytest.mark.asyncio
async def test_update_project(auth_client: AsyncClient):
    created = await create_project(auth_client, "Old Name")
    project_id = created["id"]

    resp = await auth_client.put(f"/projects/{project_id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    # description unchanged
    assert resp.json()["description"] == "desc"


@pytest.mark.asyncio
async def test_delete_project(auth_client: AsyncClient):
    created = await create_project(auth_client, "ToDelete")
    project_id = created["id"]

    del_resp = await auth_client.delete(f"/projects/{project_id}")
    assert del_resp.status_code == 204

    # Should now be gone
    get_resp = await auth_client.get(f"/projects/{project_id}")
    assert get_resp.status_code == 404


# ── 404 for nonexistent project ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_nonexistent_project(auth_client: AsyncClient):
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await auth_client.get(f"/projects/{fake_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_nonexistent_project(auth_client: AsyncClient):
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await auth_client.put(f"/projects/{fake_id}", json={"name": "X"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_project(auth_client: AsyncClient):
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await auth_client.delete(f"/projects/{fake_id}")
    assert resp.status_code == 404


# ── Cross-user 403 authorization boundary ─────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_user_get_project(client: AsyncClient):
    """User B cannot GET user A's project."""
    _, token_a = await create_user_and_token(client, "user_a_proj@example.com")
    _, token_b = await create_user_and_token(client, "user_b_proj@example.com")

    # User A creates a project
    client.headers.update({"Authorization": f"Bearer {token_a}"})
    created = await create_project(client, "A's Project")
    project_id = created["id"]

    # User B tries to read it
    client.headers.update({"Authorization": f"Bearer {token_b}"})
    resp = await client.get(f"/projects/{project_id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cross_user_update_project(client: AsyncClient):
    """User B cannot PUT user A's project."""
    _, token_a = await create_user_and_token(client, "user_a_upd@example.com")
    _, token_b = await create_user_and_token(client, "user_b_upd@example.com")

    client.headers.update({"Authorization": f"Bearer {token_a}"})
    created = await create_project(client, "A's Project")
    project_id = created["id"]

    client.headers.update({"Authorization": f"Bearer {token_b}"})
    resp = await client.put(f"/projects/{project_id}", json={"name": "Hijacked"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cross_user_delete_project(client: AsyncClient):
    """User B cannot DELETE user A's project."""
    _, token_a = await create_user_and_token(client, "user_a_del@example.com")
    _, token_b = await create_user_and_token(client, "user_b_del@example.com")

    client.headers.update({"Authorization": f"Bearer {token_a}"})
    created = await create_project(client, "A's Project")
    project_id = created["id"]

    client.headers.update({"Authorization": f"Bearer {token_b}"})
    resp = await client.delete(f"/projects/{project_id}")
    assert resp.status_code == 403


# ── 401 on unauthenticated requests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_projects_unauthenticated(client: AsyncClient):
    resp = await client.get("/projects")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_project_unauthenticated(client: AsyncClient):
    resp = await client.post("/projects", json={"name": "Anon"})
    assert resp.status_code in (401, 403)
