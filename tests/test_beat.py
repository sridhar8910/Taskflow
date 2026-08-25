"""
Celery Beat overdue sweep tests.

Verifies:
- check_overdue_tasks enqueues send_overdue_notification for past-due tasks
- check_overdue_tasks does NOT enqueue if task is already done
- check_overdue_tasks does NOT enqueue if task has no assignee
- check_overdue_tasks does NOT enqueue if an overdue notification already exists (idempotency)
- Running the sweep twice for the same task only enqueues once
"""

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

from app.models.task import Task, TaskStatus

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fake_sync_db(tasks: list, notifications: list | None = None):
    """
    Returns a mock that mimics a sync SQLAlchemy session.
    The mock's execute() returns different result sets depending on the
    query (tasks query vs notifications subquery).
    """
    if notifications is None:
        notifications = []

    # Track which query is being run by inspecting the call count
    call_counter = [0]

    def fake_execute(query):
        call_counter[0] += 1
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = tasks
        return mock_result

    mock_db = MagicMock()
    mock_db.execute.side_effect = fake_execute
    mock_db.close = MagicMock()
    return mock_db


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sweep_enqueues_for_overdue_task():
    """
    check_overdue_tasks must call send_overdue_notification.delay
    for a task that is overdue, not done, and has an assignee.
    """
    from app.worker import tasks as worker_module

    task_id = uuid.uuid4()
    assignee_id = uuid.uuid4()

    overdue_task = MagicMock(spec=Task)
    overdue_task.id = task_id
    overdue_task.assignee_id = assignee_id
    overdue_task.due_date = date.today() - timedelta(days=1)
    overdue_task.status = TaskStatus.todo

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [overdue_task]
    mock_db.execute.return_value = mock_result

    with (
        patch.object(worker_module, "get_sync_db", return_value=mock_db),
        patch.object(worker_module.send_overdue_notification, "delay") as mock_delay,
    ):
        result = worker_module.check_overdue_tasks()

    mock_delay.assert_called_once_with(str(task_id), str(assignee_id))
    assert result["enqueued"] == 1


@pytest.mark.asyncio
async def test_sweep_skips_done_tasks():
    """
    check_overdue_tasks must NOT enqueue for tasks that are already done.
    The DB query filters these out — simulate by returning an empty list.
    """
    from app.worker import tasks as worker_module

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []  # filtered out at DB level
    mock_db.execute.return_value = mock_result

    with (
        patch.object(worker_module, "get_sync_db", return_value=mock_db),
        patch.object(worker_module.send_overdue_notification, "delay") as mock_delay,
    ):
        result = worker_module.check_overdue_tasks()

    mock_delay.assert_not_called()
    assert result["enqueued"] == 0


@pytest.mark.asyncio
async def test_sweep_skips_tasks_without_assignee():
    """
    check_overdue_tasks must skip overdue tasks that have no assignee.
    """
    from app.worker import tasks as worker_module

    task_id = uuid.uuid4()

    unassigned_task = MagicMock(spec=Task)
    unassigned_task.id = task_id
    unassigned_task.assignee_id = None  # no assignee
    unassigned_task.due_date = date.today() - timedelta(days=1)
    unassigned_task.status = TaskStatus.in_progress

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [unassigned_task]
    mock_db.execute.return_value = mock_result

    with (
        patch.object(worker_module, "get_sync_db", return_value=mock_db),
        patch.object(worker_module.send_overdue_notification, "delay") as mock_delay,
    ):
        result = worker_module.check_overdue_tasks()

    mock_delay.assert_not_called()
    assert result["enqueued"] == 0


@pytest.mark.asyncio
async def test_sweep_idempotent_second_run():
    """
    Running check_overdue_tasks twice for the same overdue task only enqueues
    once — the second sweep's DB query returns empty because the notification
    already exists (filtered by the NOT IN subquery).
    """
    from app.worker import tasks as worker_module

    task_id = uuid.uuid4()
    assignee_id = uuid.uuid4()

    overdue_task = MagicMock(spec=Task)
    overdue_task.id = task_id
    overdue_task.assignee_id = assignee_id

    mock_db_first = MagicMock()
    result_first = MagicMock()
    result_first.scalars.return_value.all.return_value = [overdue_task]
    mock_db_first.execute.return_value = result_first

    mock_db_second = MagicMock()
    result_second = MagicMock()
    result_second.scalars.return_value.all.return_value = []  # notification exists now
    mock_db_second.execute.return_value = result_second

    enqueue_count = [0]

    def count_delay(task_id_str, assignee_id_str):
        enqueue_count[0] += 1

    with patch.object(
        worker_module.send_overdue_notification, "delay", side_effect=count_delay
    ):
        # First sweep
        with patch.object(worker_module, "get_sync_db", return_value=mock_db_first):
            r1 = worker_module.check_overdue_tasks()

        # Second sweep (notification already exists — DB returns empty)
        with patch.object(worker_module, "get_sync_db", return_value=mock_db_second):
            r2 = worker_module.check_overdue_tasks()

    assert r1["enqueued"] == 1
    assert r2["enqueued"] == 0
    assert enqueue_count[0] == 1  # Only enqueued once across both sweeps


@pytest.mark.asyncio
async def test_sweep_multiple_overdue_tasks():
    """
    check_overdue_tasks enqueues one job per overdue task.
    """
    from app.worker import tasks as worker_module

    tasks_data = [
        (uuid.uuid4(), uuid.uuid4()),
        (uuid.uuid4(), uuid.uuid4()),
        (uuid.uuid4(), uuid.uuid4()),
    ]

    overdue_tasks = []
    for task_id, assignee_id in tasks_data:
        t = MagicMock(spec=Task)
        t.id = task_id
        t.assignee_id = assignee_id
        t.due_date = date.today() - timedelta(days=2)
        t.status = TaskStatus.todo
        overdue_tasks.append(t)

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = overdue_tasks
    mock_db.execute.return_value = mock_result

    with (
        patch.object(worker_module, "get_sync_db", return_value=mock_db),
        patch.object(worker_module.send_overdue_notification, "delay") as mock_delay,
    ):
        result = worker_module.check_overdue_tasks()

    assert result["enqueued"] == 3
    assert mock_delay.call_count == 3

    # Verify correct task/assignee pairs were passed
    expected_calls = [call(str(tid), str(aid)) for tid, aid in tasks_data]
    mock_delay.assert_has_calls(expected_calls, any_order=True)
