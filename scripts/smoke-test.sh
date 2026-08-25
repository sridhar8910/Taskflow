#!/usr/bin/env bash
###############################################################################
# TaskFlow — End-to-End Smoke Test
#
# Exercises the full API lifecycle:
#   1. Health check
#   2. Metrics endpoint
#   3. User signup
#   4. User login (JWT)
#   5. Create project
#   6. Create task in project
#   7. List tasks (with pagination)
#   8. Update task (status change)
#   9. List notifications
#  10. Delete task
#  11. Delete project
#
# Exit codes:
#   0 — all tests passed
#   1 — one or more tests failed
#
# Usage:
#   bash scripts/smoke-test.sh [BASE_URL]
#   Default BASE_URL: http://localhost:8000
###############################################################################

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
PASS=0
FAIL=0
TOTAL=0

# ── Helpers ──────────────────────────────────────────────────────────────────

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

assert_status() {
  local test_name="$1"
  local expected="$2"
  local actual="$3"
  TOTAL=$((TOTAL + 1))

  if [ "$actual" = "$expected" ]; then
    green "  ✓ $test_name (HTTP $actual)"
    PASS=$((PASS + 1))
  else
    red "  ✗ $test_name — expected HTTP $expected, got HTTP $actual"
    FAIL=$((FAIL + 1))
  fi
}

# Generate unique email so smoke tests are idempotent
TIMESTAMP=$(date +%s)
TEST_EMAIL="smoke-${TIMESTAMP}@test.taskflow.dev"
TEST_PASSWORD="SmokeTest_Pass_2024!"

bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bold "  TaskFlow Smoke Test Suite"
bold "  Target: $BASE_URL"
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. Health check ──────────────────────────────────────────────────────────
yellow "▸ Operational endpoints"

HTTP_CODE=$(curl -s -o /tmp/smoke-health.json -w "%{http_code}" "$BASE_URL/health")
assert_status "GET /health" "200" "$HTTP_CODE"

# ── 2. Metrics ───────────────────────────────────────────────────────────────
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/metrics")
assert_status "GET /metrics" "200" "$HTTP_CODE"

echo ""

# ── 3. Signup ────────────────────────────────────────────────────────────────
yellow "▸ Authentication"

HTTP_CODE=$(curl -s -o /tmp/smoke-signup.json -w "%{http_code}" \
  -X POST "$BASE_URL/auth/signup" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$TEST_EMAIL\", \"password\": \"$TEST_PASSWORD\"}")
assert_status "POST /auth/signup" "201" "$HTTP_CODE"

# ── 4. Login ─────────────────────────────────────────────────────────────────
HTTP_CODE=$(curl -s -o /tmp/smoke-login.json -w "%{http_code}" \
  -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$TEST_EMAIL\", \"password\": \"$TEST_PASSWORD\"}")
assert_status "POST /auth/login" "200" "$HTTP_CODE"

# Extract JWT token
TOKEN=$(cat /tmp/smoke-login.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
  red "  ✗ Failed to extract JWT token from login response"
  FAIL=$((FAIL + 1))
  TOTAL=$((TOTAL + 1))
  # Show summary and exit early
  echo ""
  bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  red "  RESULT: $PASS/$TOTAL passed, $FAIL failed — FAIL"
  bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 1
fi

AUTH="Authorization: Bearer $TOKEN"
green "  ✓ JWT token obtained"

echo ""

# ── 5. Protected route without token ─────────────────────────────────────────
yellow "▸ Authorization"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/projects")
assert_status "GET /projects (no token → 401)" "401" "$HTTP_CODE"

echo ""

# ── 6. Create project ───────────────────────────────────────────────────────
yellow "▸ Project CRUD"

HTTP_CODE=$(curl -s -o /tmp/smoke-project.json -w "%{http_code}" \
  -X POST "$BASE_URL/projects" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"name": "Smoke Test Project", "description": "Created by CI smoke test"}')
assert_status "POST /projects (create)" "201" "$HTTP_CODE"

PROJECT_ID=$(cat /tmp/smoke-project.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

# List projects
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "$AUTH" "$BASE_URL/projects")
assert_status "GET /projects (list)" "200" "$HTTP_CODE"

# Get single project
if [ -n "$PROJECT_ID" ]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "$AUTH" "$BASE_URL/projects/$PROJECT_ID")
  assert_status "GET /projects/{id}" "200" "$HTTP_CODE"
fi

echo ""

# ── 7. Create task ───────────────────────────────────────────────────────────
yellow "▸ Task CRUD"

if [ -n "$PROJECT_ID" ]; then
  HTTP_CODE=$(curl -s -o /tmp/smoke-task.json -w "%{http_code}" \
    -X POST "$BASE_URL/projects/$PROJECT_ID/tasks" \
    -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d '{"title": "Smoke Test Task", "description": "CI test task", "status": "todo", "due_date": "2030-12-31"}')
  assert_status "POST /projects/{id}/tasks (create)" "201" "$HTTP_CODE"

  TASK_ID=$(cat /tmp/smoke-task.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

  # List tasks (top-level)
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "$AUTH" "$BASE_URL/tasks")
  assert_status "GET /tasks (list all)" "200" "$HTTP_CODE"

  # List tasks (project-scoped)
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "$AUTH" "$BASE_URL/projects/$PROJECT_ID/tasks")
  assert_status "GET /projects/{id}/tasks (list)" "200" "$HTTP_CODE"

  # Update task
  if [ -n "$TASK_ID" ]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
      -X PUT "$BASE_URL/projects/$PROJECT_ID/tasks/$TASK_ID" \
      -H "$AUTH" \
      -H "Content-Type: application/json" \
      -d '{"status": "in_progress"}')
    assert_status "PUT /projects/{id}/tasks/{id} (update)" "200" "$HTTP_CODE"
  fi
fi

echo ""

# ── 8. Notifications ─────────────────────────────────────────────────────────
yellow "▸ Notifications"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "$AUTH" "$BASE_URL/notifications")
assert_status "GET /notifications" "200" "$HTTP_CODE"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "$AUTH" "$BASE_URL/notifications?unread_only=true&limit=10")
assert_status "GET /notifications (filtered)" "200" "$HTTP_CODE"

echo ""

# ── 9. Task filtering & pagination ──────────────────────────────────────────
yellow "▸ Filtering & Pagination"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "$AUTH" "$BASE_URL/tasks?status=todo&page=1&page_size=10")
assert_status "GET /tasks (status filter)" "200" "$HTTP_CODE"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "$AUTH" "$BASE_URL/tasks?limit=50")
assert_status "GET /tasks (limit alias)" "200" "$HTTP_CODE"

echo ""

# ── 10. Cleanup — delete task and project ────────────────────────────────────
yellow "▸ Cleanup"

if [ -n "$PROJECT_ID" ] && [ -n "$TASK_ID" ]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X DELETE "$BASE_URL/projects/$PROJECT_ID/tasks/$TASK_ID" \
    -H "$AUTH")
  assert_status "DELETE /projects/{id}/tasks/{id}" "204" "$HTTP_CODE"
fi

if [ -n "$PROJECT_ID" ]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X DELETE "$BASE_URL/projects/$PROJECT_ID" \
    -H "$AUTH")
  assert_status "DELETE /projects/{id}" "204" "$HTTP_CODE"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$FAIL" -eq 0 ]; then
  green "  RESULT: $PASS/$TOTAL passed — ALL PASSED ✓"
else
  red "  RESULT: $PASS/$TOTAL passed, $FAIL failed — FAIL ✗"
fi
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$FAIL" -eq 0 ]
