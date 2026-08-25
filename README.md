# TaskFlow

A Task Management API with JWT authentication, background notifications, and Redis caching.

Built as a take-home engineering assignment. The stack is FastAPI + PostgreSQL + Redis + Celery, running as a single `docker compose up` command.

---

## Quick start

**Prerequisites:** Docker and Docker Compose.

```bash
git clone <repo-url>
cd taskflow
cp .env.example .env          # review defaults — no changes needed for local dev
docker compose up --build
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

To apply database migrations (first run or after schema changes):

```bash
docker compose exec api alembic upgrade head
```

---

## Running tests locally

Tests use SQLite in-memory and fakeredis by default — no external services needed.

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

To run against real PostgreSQL + Redis (mirrors CI):

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://taskflow:taskflow@localhost:5432/taskflow
docker compose up db redis -d
alembic upgrade head
pytest tests/ -v
```

---

## Architecture

```
                     Client
                        │
                        ▼
                   ┌─────────┐
                   │ FastAPI │  ← JWT auth, request/error metrics middleware
                   └────┬────┘
                        │
          ┌─────────────┼──────────────┐
          ▼             ▼              ▼
     PostgreSQL       Redis        Celery broker
     (SQLAlchemy   (cache +        (Redis)
      async ORM)    invalidation)
          ▲                            │
          │                            ▼
          │                     Celery Worker
          │                      ┌─────────────────────────┐
          │                      │ send_reassignment_notif  │
          │                      │ send_overdue_notif       │
          └──────────────────────│ check_overdue_tasks      │
                                 │ (Beat: every 60s)        │
                                 └─────────────────────────┘
```

### Services

| Service | Role |
|---------|------|
| `api` | FastAPI app, uvicorn, handles all HTTP |
| `worker` | Celery worker, processes notification jobs |
| `beat` | Celery Beat scheduler, periodic overdue sweep |
| `db` | PostgreSQL 16 |
| `redis` | Redis 7, dual-purpose: cache store + Celery broker |

### Data model

```
users ──< projects ──< tasks ──< notifications
users ──< tasks (assignee_id)
users ──< notifications
```

- `tasks.due_date` is a `DATE` (not `DATETIME`) — comparisons use `date.today()`
- `notifications` has a `UNIQUE(task_id, type)` constraint — the DB-level idempotency guard for background jobs

### Cache strategy

```
Key:         tasks:user:{user_id}:{md5(sorted filter params)}
TTL:         60 seconds (configurable via CACHE_TTL_SECONDS)
Invalidate:  on any task CREATE / UPDATE / DELETE
             → delete tasks:user:{owner_id}:*
             → delete tasks:user:{old_assignee_id}:*  (on reassignment)
             → delete tasks:user:{new_assignee_id}:*  (on reassignment)
```

Stale reads after a status change are treated as bugs. The invalidation covers both sides of every reassignment to prevent cross-user stale data.

---

## API reference

All endpoints except `/auth/signup` and `/auth/login` require:

```
Authorization: Bearer <access_token>
```

### Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/signup` | Create account. Returns `UserOut` (no password fields). |
| `POST` | `/auth/login` | Get JWT access token. |

### Projects

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects` | List own projects |
| `POST` | `/projects` | Create project |
| `GET` | `/projects/{id}` | Get project (403 if not owner) |
| `PUT` | `/projects/{id}` | Update project |
| `DELETE` | `/projects/{id}` | Delete project |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tasks` | List all tasks (cross-project, cache-backed) |
| `GET` | `/projects/{id}/tasks` | List tasks in a project (cache-backed) |
| `POST` | `/projects/{id}/tasks` | Create task |
| `GET` | `/projects/{id}/tasks/{tid}` | Get task |
| `PUT` | `/projects/{id}/tasks/{tid}` | Update task (triggers notifications) |
| `DELETE` | `/projects/{id}/tasks/{tid}` | Delete task |

**Filters for `GET /tasks`:**

| Param | Type | Description |
|-------|------|-------------|
| `status` | `todo\|in_progress\|done` | Filter by status |
| `assignee_id` | UUID | Filter by assignee |
| `due_date_from` | date (`YYYY-MM-DD`) | due_date >= |
| `due_date_to` | date (`YYYY-MM-DD`) | due_date <= |
| `page` | int (default: 1) | Page number |
| `page_size` | int (default: 20, max: 100) | Items per page |

### Notifications

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notifications` | List notifications for current user (`unread_only`, `limit`) |
| `PATCH` | `/notifications/{id}/read` | Mark one notification as read |
| `PATCH` | `/notifications/read-all` | Mark all current-user notifications as read |

### Operational

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Checks PostgreSQL (`SELECT 1`) + Redis (`PING`). Returns 200 or 503. |
| `GET` | `/metrics` | Request/error counters per route. |

---

## Authentication design

**JWT (HS256) over session-based auth.**

Reasons:
- Stateless — no server-side session store needed; Redis is already used for cache and broker, not session state
- Natural fit for API-first clients (mobile, SPAs, other services)
- Easy to test and inspect without browser tooling

Passwords are hashed with **Argon2id** via `argon2-cffi` (default params: time_cost=3, memory_cost=65536). Passwords are never logged, never returned in responses, and the `UserOut` schema explicitly excludes `hashed_password`.

Tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 60). There is no refresh token in this implementation — see tradeoffs below.

---

## Background jobs

Celery is configured with Redis as both broker and result backend.

**Notification triggers:**

1. **On `PUT /tasks/{id}`** — if `assignee_id` changed, `send_reassignment_notification.delay()` is called immediately after the DB write (not in the request handler — the `.delay()` returns instantly).

2. **Celery Beat sweep (every 60s)** — `check_overdue_tasks` queries for tasks where `due_date < today AND status != done AND no overdue notification exists`, then enqueues `send_overdue_notification.delay()` for each.

**Idempotency:** Overdue notifications use a stable event key, so repeated sweeps create only one alert. Each reassignment carries a distinct event key, so a later reassignment is not incorrectly suppressed. The worker uses a `get_or_create` pattern with `IntegrityError` handling for races.

**Simulated delivery:** Jobs write a structured log line and insert a row into the `notifications` table. No real email or webhook is sent.

---

## Deployment

**Path taken: documented Render deployment. No live URL is provided.**

This decision was deliberate — free-tier Render instances cold-start slowly and the assignment explicitly accepts a documented path as equivalent. The `render.yaml` in this repo is fully configured and ready to deploy.

### Deploy to Render

1. Fork or push this repo to GitHub.
2. Go to [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
3. Connect the GitHub repo. Render reads `render.yaml` automatically.
4. Set `SECRET_KEY` as a secret environment variable in the Render dashboard (Environment → Add Secret File or secret env var).
5. Add a **Redis** instance named `taskflow-redis` (New → Redis, free plan).
6. Click **Apply** — Render provisions PostgreSQL, runs migrations (`alembic upgrade head` in the build command), and starts all three services.

**Services deployed:**

| Render service | Type | Command |
|----------------|------|---------|
| `taskflow-api` | Web | `uvicorn app.main:app` |
| `taskflow-worker` | Background Worker | `celery worker` |
| `taskflow-beat` | Background Worker | `celery beat` |

All environment variables (database URL, Redis URL, etc.) are wired automatically via `fromDatabase` and `fromService` references in `render.yaml`. The only manual step is setting `SECRET_KEY`.

---

## CI/CD

Complete CI/CD pipeline via GitHub Actions. Two workflows automate the full lifecycle from code push to production deployment.

### Pipeline architecture

```
Push to main/master
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                    CI Workflow (ci.yml)                   │
│                                                          │
│  ┌──────┐    ┌──────┐    ┌──────────┐                    │
│  │ Lint │───▶│ Test │───▶│ Security │                    │
│  └──────┘    └──────┘    └──────────┘                    │
│                 │              │                          │
│                 ▼              ▼                          │
│              ┌────────────────────┐                       │
│              │  Build & Push to   │                       │
│              │  GitHub Container  │                       │
│              │  Registry (GHCR)   │                       │
│              └─────────┬──────────┘                       │
│                        ▼                                  │
│              ┌────────────────────┐                       │
│              │ Integration Smoke  │                       │
│              │ Test (full stack)  │                       │
│              └─────────┬──────────┘                       │
│                        ▼                                  │
│              ┌────────────────────┐                       │
│              │ Deploy to Render   │                       │
│              │ (manual approval)  │                       │
│              └────────────────────┘                       │
└──────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                    CD Workflow (cd.yml)                   │
│                                                          │
│  Gate → Smoke Test → Deploy → Health Verification        │
└──────────────────────────────────────────────────────────┘
```

### CI jobs (`.github/workflows/ci.yml`)

| Job | Runs on | Purpose |
|-----|---------|---------|
| **lint** | Every push/PR | `ruff format --check` + `ruff check` |
| **test** | After lint | Real PostgreSQL 16 + Redis 7, Alembic migrations, `pytest --cov` with 70% threshold |
| **security** | After lint | `pip-audit` dependency CVE scan + `hadolint` Dockerfile lint |
| **build** | After test+security, main only | Multi-stage Docker build → push to `ghcr.io` |
| **integration** | After build, main only | `docker compose up` full stack + `scripts/smoke-test.sh` |
| **deploy** | After integration, main only | Trigger Render deploy hook (requires `production` environment approval) |

### CD workflow (`.github/workflows/cd.yml`)

Triggers automatically after CI completes on main, or manually via `workflow_dispatch`:

1. **Gate** — verify CI passed
2. **Smoke test** — spin up full stack, run end-to-end API test
3. **Deploy** — trigger Render deploy hook
4. **Verify** — poll production `/health` endpoint

### Required GitHub secrets

| Secret | Purpose |
|--------|---------|
| `RENDER_DEPLOY_HOOK_URL` | Render service deploy hook URL (Settings → Deploy Hook) |
| `PRODUCTION_URL` | Production base URL for post-deploy health checks (e.g. `https://taskflow-api.onrender.com`) |

> **Note:** `GITHUB_TOKEN` is automatically provided — no manual setup needed for GHCR pushes.

### Running smoke tests locally

```bash
# Start the full stack
docker compose up -d --build

# Run the smoke test suite
bash scripts/smoke-test.sh http://localhost:8000
```

The test job uses real PostgreSQL and Redis (not mocks) so cache invalidation and DB constraints are exercised as they would be in production.

---

## Tradeoffs and what I'd do with more time

This is the honest version. The assignment says to be candid, so here it is.

**What was prioritized:**

- Correctness of auth/authz boundaries — cross-user 403s are tested on every resource type
- Cache invalidation correctness — stale reads after reassignment are explicitly tested for both old and new assignee
- Idempotent background jobs — DB constraint + application-level guard, tested with double-enqueue scenarios
- Clean separation: service layer owns business logic, routers own HTTP concerns, workers own async concerns

**What was cut or simplified:**

- **Refresh tokens.** The current JWT implementation has no refresh flow. Tokens expire and the client must re-authenticate. A production system would issue short-lived access tokens (5–15 min) and longer-lived refresh tokens with revocation support (stored in Redis or a DB table).

- **Async Celery tasks.** Celery workers use a synchronous SQLAlchemy session. This was intentional — adding `asyncio` event loops inside Celery tasks adds complexity without real benefit at this scale. With more time, I'd evaluate `celery-django-aiohttp` or move notification jobs to a purpose-built async queue (e.g. arq).

- **Per-task cache granularity.** The current invalidation strategy deletes all cache keys for a user when any task changes. This is safe but slightly over-invalidates (e.g. changing task A invalidates cached pages that don't include task A). A more precise strategy would key cache entries by task ID and invalidate only affected pages — worth doing at scale but adds complexity.

- **Rate limiting.** No rate limiting on auth endpoints. A production deployment would add `slowapi` or an upstream proxy (nginx, Cloudflare) to limit signup/login attempts.

- **WebSocket / SSE notifications.** Notifications are written to a DB table but there's no push mechanism. Real-time delivery would use WebSockets or Server-Sent Events with a Redis pub/sub backend.

- **Prometheus metrics.** `/metrics` returns a JSON counter dict. The upgrade path is a one-line swap to `prometheus_client.generate_latest()` — the middleware structure is already in place.

- **`EXPLAIN ANALYZE` on task list query.** The `list_tasks` query joins `tasks` to `projects` and applies up to 4 filters. I added indexes on `project_id`, `assignee_id`, and `due_date`, but I didn't profile the query plan against a realistic dataset. With more time I'd run `EXPLAIN ANALYZE` with 100k+ rows and tune accordingly.

- **Integration tests in CI against Docker Compose stack.** ✅ Implemented — the CI pipeline includes a full `docker compose up` integration smoke test step that exercises the API end-to-end inside a containerized environment (see `docker-compose.ci.yml` and `scripts/smoke-test.sh`).

**Assumptions documented:**

- `due_date` is a `DATE`, not `DATETIME`. Overdue comparison uses `date.today()` in the worker's timezone (UTC). Tasks due "today" are not treated as overdue until the Beat sweep runs the following day.
- The `GET /tasks` top-level endpoint returns only tasks in projects owned by the authenticated user. Tasks the user is only _assigned to_ (but doesn't own the project) are not included. This matches the authorization model — a user can only see their own projects.
- Notification "delivery" is simulated via log lines and DB rows. The assignment explicitly permits this.
- No live deployment URL is provided. The `render.yaml` and these instructions are the deployment deliverable, as the assignment allows.
