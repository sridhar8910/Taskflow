"""
Redis caching + invalidation tests.

Verifies:
- First GET /tasks is a cache miss (writes to cache)
- Second identical GET /tasks is a cache hit (returns from cache)
- Creating a task invalidates cache (next read re-queries DB)
- Updating a task invalidates cache
- Deleting a task invalidates cache
- Reassigning a task invalidates BOTH old and new assignee's cache
"""

import pytest
from httpx import AsyncClient

from app.cache import make_cache_key
from tests.conftest import create_user_and_token

# ── Helpers ───────────────────────────────────────────────────────────────────


async def signup_and_login(client: AsyncClient, email: str) -> tuple[str, str]:
    """Returns (user_id, token)."""
    return await create_user_and_token(client, email)


async def make_project(client: AsyncClient, name: str = "Cache Project") -> str:
    resp = await client.post("/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def make_task(
    client: AsyncClient, project_id: str, title: str = "Cached Task"
) -> dict:
    resp = await client.post(f"/projects/{project_id}/tasks", json={"title": title})
    assert resp.status_code == 201
    return resp.json()


# ── Cache miss → hit ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_miss_then_hit(client: AsyncClient, fake_redis):
    """Second identical request should be served from cache."""
    user_id, token = await signup_and_login(client, "cache_hit@example.com")
    client.headers.update({"Authorization": f"Bearer {token}"})

    project_id = await make_project(client)
    await make_task(client, project_id, "Task for cache")

    # First request — cache miss, key should be written
    resp1 = await client.get("/tasks")
    assert resp1.status_code == 200

    # Verify a key now exists in Redis for this user
    filters = {
        "status": None,
        "assignee_id": None,
        "due_date_from": None,
        "due_date_to": None,
        "project_id": None,
        "page": 1,
        "page_size": 20,
    }
    import uuid

    key = make_cache_key(uuid.UUID(user_id), filters)
    cached_value = await fake_redis.get(key)
    assert cached_value is not None, "Cache key was not written after first request"

    # Second request — should return same data (from cache)
    resp2 = await client.get("/tasks")
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()


# ── Invalidation on create ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_invalidated_on_create(client: AsyncClient, fake_redis):
    """Creating a task must clear the cache so the next read sees the new task."""
    user_id, token = await signup_and_login(client, "cache_create@example.com")
    client.headers.update({"Authorization": f"Bearer {token}"})

    project_id = await make_project(client)
    await make_task(client, project_id, "Existing Task")

    # Warm the cache
    resp1 = await client.get("/tasks")
    assert resp1.status_code == 200
    count_before = resp1.json()["total"]

    # Create another task — should invalidate the cache
    await make_task(client, project_id, "New Task After Cache")

    # Next GET must reflect the new task (fresh DB read)
    resp2 = await client.get("/tasks")
    assert resp2.status_code == 200
    assert resp2.json()["total"] > count_before
    titles = [t["title"] for t in resp2.json()["items"]]
    assert "New Task After Cache" in titles


# ── Invalidation on update ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_invalidated_on_update(client: AsyncClient, fake_redis):
    """Updating a task must clear the cache."""
    user_id, token = await signup_and_login(client, "cache_update@example.com")
    client.headers.update({"Authorization": f"Bearer {token}"})

    project_id = await make_project(client)
    task = await make_task(client, project_id, "Before Update")
    task_id = task["id"]

    # Warm the cache
    resp1 = await client.get("/tasks")
    assert resp1.status_code == 200
    assert any(t["title"] == "Before Update" for t in resp1.json()["items"])

    # Update the task
    await client.put(
        f"/projects/{project_id}/tasks/{task_id}",
        json={"title": "After Update"},
    )

    # Cache must be invalidated — next read shows updated title
    resp2 = await client.get("/tasks")
    assert resp2.status_code == 200
    titles = [t["title"] for t in resp2.json()["items"]]
    assert "After Update" in titles
    assert "Before Update" not in titles


# ── Invalidation on delete ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_invalidated_on_delete(client: AsyncClient, fake_redis):
    """Deleting a task must clear the cache."""
    user_id, token = await signup_and_login(client, "cache_delete@example.com")
    client.headers.update({"Authorization": f"Bearer {token}"})

    project_id = await make_project(client)
    task = await make_task(client, project_id, "To Be Deleted")
    task_id = task["id"]

    # Warm the cache
    resp1 = await client.get("/tasks")
    assert resp1.status_code == 200
    assert any(t["title"] == "To Be Deleted" for t in resp1.json()["items"])

    # Delete the task
    del_resp = await client.delete(f"/projects/{project_id}/tasks/{task_id}")
    assert del_resp.status_code == 204

    # Cache must be invalidated — deleted task should not appear
    resp2 = await client.get("/tasks")
    assert resp2.status_code == 200
    titles = [t["title"] for t in resp2.json()["items"]]
    assert "To Be Deleted" not in titles


# ── Invalidation on reassignment (both users) ─────────────────────────────────


@pytest.mark.asyncio
async def test_cache_invalidated_for_both_assignees_on_reassignment(
    client: AsyncClient, fake_redis
):
    """
    When a task is reassigned from User A to User B, both users' caches
    must be invalidated.
    """
    import uuid as uuid_mod

    owner_id, owner_token = await signup_and_login(client, "reassign_owner@example.com")
    assignee_a_id, token_a = await signup_and_login(client, "reassign_a@example.com")
    assignee_b_id, token_b = await signup_and_login(client, "reassign_b@example.com")

    # Owner creates project and task assigned to A
    client.headers.update({"Authorization": f"Bearer {owner_token}"})
    project_id = await make_project(client, "Reassign Project")
    task_resp = await client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Reassignable Task", "assignee_id": assignee_a_id},
    )
    assert task_resp.status_code == 201
    task_id = task_resp.json()["id"]

    # Warm cache for assignee A
    client.headers.update({"Authorization": f"Bearer {token_a}"})
    warm_a = await client.get(f"/tasks?assignee_id={assignee_a_id}")
    assert warm_a.status_code == 200

    # Warm cache for assignee B
    client.headers.update({"Authorization": f"Bearer {token_b}"})
    warm_b = await client.get(f"/tasks?assignee_id={assignee_b_id}")
    assert warm_b.status_code == 200

    # Verify both cache keys exist
    filters_a = {
        "status": None,
        "assignee_id": assignee_a_id,
        "due_date_from": None,
        "due_date_to": None,
        "project_id": None,
        "page": 1,
        "page_size": 20,
    }
    filters_b = {
        "status": None,
        "assignee_id": assignee_b_id,
        "due_date_from": None,
        "due_date_to": None,
        "project_id": None,
        "page": 1,
        "page_size": 20,
    }
    key_a = make_cache_key(uuid_mod.UUID(assignee_a_id), filters_a)
    key_b = make_cache_key(uuid_mod.UUID(assignee_b_id), filters_b)
    assert await fake_redis.get(key_a) is not None, "Assignee A cache not warmed"
    assert await fake_redis.get(key_b) is not None, "Assignee B cache not warmed"

    # Owner reassigns task from A to B
    client.headers.update({"Authorization": f"Bearer {owner_token}"})
    update_resp = await client.put(
        f"/projects/{project_id}/tasks/{task_id}",
        json={"assignee_id": assignee_b_id},
    )
    assert update_resp.status_code == 200

    # Both cache keys must now be gone
    assert (
        await fake_redis.get(key_a) is None
    ), "Assignee A cache not invalidated after reassignment"
    assert (
        await fake_redis.get(key_b) is None
    ), "Assignee B cache not invalidated after reassignment"
