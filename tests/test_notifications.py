"""
Notification tests covering:
- Reassignment triggers send_reassignment_notification.delay
- No-op update (same assignee) does NOT trigger notification job
- Idempotency: calling the worker function twice with same task_id creates one row
- GET /notifications returns the current user's notifications
- GET /notifications unauthenticated → 401/403
"""

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from tests.conftest import create_user_and_token

# ── Helpers ───────────────────────────────────────────────────────────────────


async def make_project(client: AsyncClient, name: str = "Notif Project") -> str:
    resp = await client.post("/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def make_task(
    client: AsyncClient,
    project_id: str,
    title: str = "Notif Task",
    assignee_id: str | None = None,
) -> dict:
    payload: dict = {"title": title}
    if assignee_id:
        payload["assignee_id"] = assignee_id
    resp = await client.post(f"/projects/{project_id}/tasks", json=payload)
    assert resp.status_code == 201
    return resp.json()


# ── Reassignment triggers notification job ────────────────────────────────────


@pytest.mark.asyncio
async def test_reassignment_triggers_notification_job(client: AsyncClient):
    """PUT with a changed assignee_id must call send_reassignment_notification.delay."""
    owner_id, owner_token = await create_user_and_token(
        client, "notif_owner1@example.com"
    )
    assignee_id, _ = await create_user_and_token(client, "notif_assignee1@example.com")

    client.headers.update({"Authorization": f"Bearer {owner_token}"})
    project_id = await make_project(client)
    task = await make_task(client, project_id)
    task_id = task["id"]

    # Patch .delay on the actual task object imported in the worker module
    from app.worker import tasks as worker_module

    with patch.object(
        worker_module.send_reassignment_notification, "delay"
    ) as mock_delay:
        resp = await client.put(
            f"/projects/{project_id}/tasks/{task_id}",
            json={"assignee_id": assignee_id},
        )
        assert resp.status_code == 200
        mock_delay.assert_called_once()
        call_args = mock_delay.call_args.args
        assert call_args[:3] == (task_id, None, assignee_id)
        uuid.UUID(call_args[3])


@pytest.mark.asyncio
async def test_no_op_update_does_not_trigger_notification(client: AsyncClient):
    """PUT that doesn't change assignee must NOT call send_reassignment_notification."""
    owner_id, owner_token = await create_user_and_token(
        client, "notif_noop@example.com"
    )
    assignee_id, _ = await create_user_and_token(client, "notif_noop_a@example.com")

    client.headers.update({"Authorization": f"Bearer {owner_token}"})
    project_id = await make_project(client)
    task = await make_task(client, project_id, assignee_id=assignee_id)
    task_id = task["id"]

    # Update only the title — assignee unchanged
    from app.worker import tasks as worker_module

    with patch.object(
        worker_module.send_reassignment_notification, "delay"
    ) as mock_delay:
        resp = await client.put(
            f"/projects/{project_id}/tasks/{task_id}",
            json={"title": "New Title"},
        )
        assert resp.status_code == 200
        mock_delay.assert_not_called()


# ── Idempotency: _get_or_create_notification ──────────────────────────────────


@pytest.mark.asyncio
async def test_send_reassignment_notification_idempotent():
    """
    Calling send_reassignment_notification twice for the same task must result
    in created=True on the first call and created=False on the second.
    This validates the idempotency contract without touching a real DB.
    """
    from unittest.mock import MagicMock

    from app.worker import tasks as worker_module

    task_id = uuid.uuid4()
    assignee_id = uuid.uuid4()

    # Fake notification object — just needs an .id attribute
    fake_notif = MagicMock()
    fake_notif.id = uuid.uuid4()

    _store: dict = {}

    def fake_get_or_create(t_id, u_id, ntype, event_key, message):
        key = (str(t_id), str(ntype), event_key)
        if key in _store:
            return _store[key], False
        _store[key] = fake_notif
        return fake_notif, True

    with patch.object(
        worker_module, "_get_or_create_notification", side_effect=fake_get_or_create
    ):
        r1 = worker_module.send_reassignment_notification(
            str(task_id), None, str(assignee_id)
        )
        r2 = worker_module.send_reassignment_notification(
            str(task_id), None, str(assignee_id)
        )

    assert r1["created"] is True, "First call must create the notification"
    assert r2["created"] is False, "Second call must be idempotent (no-op)"


@pytest.mark.asyncio
async def test_distinct_reassignment_events_are_not_collapsed():
    """A later reassignment needs its own notification event."""
    from unittest.mock import MagicMock

    from app.worker import tasks as worker_module

    task_id = uuid.uuid4()
    assignee_a = uuid.uuid4()
    assignee_b = uuid.uuid4()
    fake_notif = MagicMock(id=uuid.uuid4())
    events: set[str] = set()

    def fake_get_or_create(t_id, u_id, ntype, event_key, message):
        if event_key in events:
            return fake_notif, False
        events.add(event_key)
        return fake_notif, True

    with patch.object(
        worker_module, "_get_or_create_notification", side_effect=fake_get_or_create
    ):
        first = worker_module.send_reassignment_notification(
            str(task_id), None, str(assignee_a), "event-1"
        )
        second = worker_module.send_reassignment_notification(
            str(task_id), str(assignee_a), str(assignee_b), "event-2"
        )

    assert first["created"] is True
    assert second["created"] is True


# ── GET /notifications ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_notifications_empty(client: AsyncClient):
    """Fresh user has no notifications."""
    _, token = await create_user_and_token(client, "notif_empty@example.com")
    client.headers.update({"Authorization": f"Bearer {token}"})

    resp = await client.get("/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_notifications_unauthenticated(client: AsyncClient):
    resp = await client.get("/notifications")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_notification_visible_after_insert(client: AsyncClient, db_session):
    """
    A notification inserted directly into the DB is visible via GET /notifications.
    (Simulates what the Celery worker does.)
    """
    owner_id, owner_token = await create_user_and_token(
        client, "notif_vis_a@example.com"
    )
    assignee_id, assignee_token = await create_user_and_token(
        client, "notif_vis_b@example.com"
    )

    client.headers.update({"Authorization": f"Bearer {owner_token}"})
    project_id = await make_project(client, "Vis Project")
    task_resp = await make_task(client, project_id)
    task_id = task_resp["id"]

    # Simulate worker writing a notification
    from app.models.notification import Notification, NotificationType

    n = Notification(
        task_id=uuid.UUID(task_id),
        user_id=uuid.UUID(assignee_id),
        type=NotificationType.reassigned,
        message="You have been assigned a task.",
    )
    db_session.add(n)
    await db_session.flush()

    # Assignee sees it via GET /notifications
    client.headers.update({"Authorization": f"Bearer {assignee_token}"})
    resp = await client.get("/notifications")
    assert resp.status_code == 200
    notif_ids = [item["id"] for item in resp.json()]
    assert str(n.id) in notif_ids


@pytest.mark.asyncio
async def test_notifications_scoped_to_current_user(client: AsyncClient, db_session):
    """User A cannot see User B's notifications."""
    id_a, token_a = await create_user_and_token(client, "notif_scope_a@example.com")
    id_b, token_b = await create_user_and_token(client, "notif_scope_b@example.com")

    client.headers.update({"Authorization": f"Bearer {token_a}"})
    project_id = await make_project(client, "Scope Project")
    task_resp = await make_task(client, project_id)
    task_id = task_resp["id"]

    from app.models.notification import Notification, NotificationType

    # Notification for user B only
    n = Notification(
        task_id=uuid.UUID(task_id),
        user_id=uuid.UUID(id_b),
        type=NotificationType.overdue,
        message="Overdue.",
    )
    db_session.add(n)
    await db_session.flush()

    # User A should see 0 notifications
    resp = await client.get("/notifications")
    assert resp.status_code == 200
    assert all(item["user_id"] == id_a for item in resp.json())
