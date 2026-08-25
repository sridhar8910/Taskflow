"""
Task CRUD + filtering + pagination tests.
Key scenarios:
- Full CRUD happy path
- GET /tasks top-level endpoint
- Filter by status, assignee, date range
- Pagination correctness (total, pages)
- Cross-project 403
- Unauthenticated 401/403
"""

import pytest
from httpx import AsyncClient

from tests.conftest import create_user_and_token

# ── Helpers ───────────────────────────────────────────────────────────────────


async def make_project(client: AsyncClient, name: str = "Test Project") -> str:
    resp = await client.post("/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def make_task(
    client: AsyncClient,
    project_id: str,
    title: str = "A Task",
    status: str = "todo",
    assignee_id: str | None = None,
    due_date: str | None = None,
) -> dict:
    payload: dict = {"title": title, "status": status}
    if assignee_id:
        payload["assignee_id"] = assignee_id
    if due_date:
        payload["due_date"] = due_date
    resp = await client.post(f"/projects/{project_id}/tasks", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── CRUD happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_task(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    resp = await auth_client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Write tests", "status": "todo", "due_date": "2025-12-31"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Write tests"
    assert body["status"] == "todo"
    assert body["due_date"] == "2025-12-31"
    assert body["project_id"] == project_id


@pytest.mark.asyncio
async def test_get_task(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    task = await make_task(auth_client, project_id, "Get me")
    task_id = task["id"]

    resp = await auth_client.get(f"/projects/{project_id}/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == task_id


@pytest.mark.asyncio
async def test_update_task(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    task = await make_task(auth_client, project_id, "Old Title")
    task_id = task["id"]

    resp = await auth_client.put(
        f"/projects/{project_id}/tasks/{task_id}",
        json={"title": "New Title", "status": "in_progress"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "New Title"
    assert body["status"] == "in_progress"


@pytest.mark.asyncio
async def test_delete_task(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    task = await make_task(auth_client, project_id, "Delete me")
    task_id = task["id"]

    del_resp = await auth_client.delete(f"/projects/{project_id}/tasks/{task_id}")
    assert del_resp.status_code == 204

    get_resp = await auth_client.get(f"/projects/{project_id}/tasks/{task_id}")
    assert get_resp.status_code == 404


# ── GET /tasks top-level ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_level_get_tasks(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    await make_task(auth_client, project_id, "Task 1")
    await make_task(auth_client, project_id, "Task 2")

    resp = await auth_client.get("/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    titles = [t["title"] for t in body["items"]]
    assert "Task 1" in titles
    assert "Task 2" in titles


# ── Filter by status ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_by_status(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    await make_task(auth_client, project_id, "Todo task", status="todo")
    await make_task(auth_client, project_id, "Done task", status="done")

    resp = await auth_client.get("/tasks?status=todo")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(t["status"] == "todo" for t in items)
    titles = [t["title"] for t in items]
    assert "Todo task" in titles
    assert "Done task" not in titles


# ── Filter by assignee ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_by_assignee(client: AsyncClient):
    user_id, token = await create_user_and_token(client, "owner_assignee@example.com")
    client.headers.update({"Authorization": f"Bearer {token}"})

    # Sign up another user to be the assignee
    assignee_signup = await client.post(
        "/auth/signup",
        json={"email": "assignee@example.com", "password": "securepass1"},
    )
    assignee_id = assignee_signup.json()["id"]

    project_id = await make_project(client)
    await make_task(client, project_id, "Assigned task", assignee_id=assignee_id)
    await make_task(client, project_id, "Unassigned task")

    resp = await client.get(f"/tasks?assignee_id={assignee_id}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(t["assignee_id"] == assignee_id for t in items)
    titles = [t["title"] for t in items]
    assert "Assigned task" in titles
    assert "Unassigned task" not in titles


# ── Filter by due date range ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_by_due_date_range(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    await make_task(auth_client, project_id, "Early task", due_date="2025-01-01")
    await make_task(auth_client, project_id, "Mid task", due_date="2025-06-15")
    await make_task(auth_client, project_id, "Late task", due_date="2025-12-31")

    resp = await auth_client.get(
        "/tasks?due_date_from=2025-06-01&due_date_to=2025-07-01"
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    titles = [t["title"] for t in items]
    assert "Mid task" in titles
    assert "Early task" not in titles
    assert "Late task" not in titles


# ── Pagination ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pagination(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    for i in range(7):
        await make_task(auth_client, project_id, f"Paged Task {i}")

    resp = await auth_client.get("/tasks?page=1&page_size=3")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 3
    assert body["page"] == 1
    assert body["page_size"] == 3
    assert body["total"] >= 7
    assert body["pages"] >= 3


@pytest.mark.asyncio
async def test_pagination_page_two(auth_client: AsyncClient):
    project_id = await make_project(auth_client)
    for i in range(5):
        await make_task(auth_client, project_id, f"Seq Task {i}")

    p1 = await auth_client.get("/tasks?page=1&page_size=3")
    p2 = await auth_client.get("/tasks?page=2&page_size=3")

    ids_p1 = {t["id"] for t in p1.json()["items"]}
    ids_p2 = {t["id"] for t in p2.json()["items"]}
    # Pages must not overlap
    assert ids_p1.isdisjoint(ids_p2)


# ── Cross-project 403 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_project_task_access(client: AsyncClient):
    """User B cannot access tasks in user A's project."""
    _, token_a = await create_user_and_token(client, "task_owner_a@example.com")
    _, token_b = await create_user_and_token(client, "task_owner_b@example.com")

    # User A creates project + task
    client.headers.update({"Authorization": f"Bearer {token_a}"})
    project_id = await make_project(client, "A's Project")
    task = await make_task(client, project_id, "A's Task")
    task_id = task["id"]

    # User B tries to access
    client.headers.update({"Authorization": f"Bearer {token_b}"})
    assert (
        await client.get(f"/projects/{project_id}/tasks/{task_id}")
    ).status_code == 403
    assert (
        await client.put(f"/projects/{project_id}/tasks/{task_id}", json={"title": "x"})
    ).status_code == 403
    assert (
        await client.delete(f"/projects/{project_id}/tasks/{task_id}")
    ).status_code == 403


@pytest.mark.asyncio
async def test_cross_project_create_task(client: AsyncClient):
    """User B cannot create tasks in user A's project."""
    _, token_a = await create_user_and_token(client, "create_owner_a@example.com")
    _, token_b = await create_user_and_token(client, "create_owner_b@example.com")

    client.headers.update({"Authorization": f"Bearer {token_a}"})
    project_id = await make_project(client, "A's Only Project")

    client.headers.update({"Authorization": f"Bearer {token_b}"})
    resp = await client.post(
        f"/projects/{project_id}/tasks", json={"title": "Intruder"}
    )
    assert resp.status_code == 403


# ── Unauthenticated ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tasks_unauthenticated(client: AsyncClient):
    resp = await client.get("/tasks")
    assert resp.status_code in (401, 403)
