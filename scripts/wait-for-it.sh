#!/usr/bin/env bash
###############################################################################
# wait-for-it.sh — Wait for a TCP host:port to become available
#
# Usage:
#   ./scripts/wait-for-it.sh HOST:PORT [-t TIMEOUT] [-- COMMAND [ARGS...]]
#
# Examples:
#   ./scripts/wait-for-it.sh localhost:5432 -t 30
#   ./scripts/wait-for-it.sh db:5432 -t 60 -- alembic upgrade head
###############################################################################

set -euo pipefail

TIMEOUT=30
HOST=""
PORT=""
CMD=()
QUIET=0

usage() {
  echo "Usage: $0 HOST:PORT [-t TIMEOUT] [-q] [-- COMMAND [ARGS...]]"
  exit 1
}

# Parse arguments
while [ $# -gt 0 ]; do
  case "$1" in
    *:*)
      HOST="${1%%:*}"
      PORT="${1##*:}"
      shift
      ;;
    -t)
      TIMEOUT="$2"
      shift 2
      ;;
    -q)
      QUIET=1
      shift
      ;;
    --)
      shift
      CMD=("$@")
      break
      ;;
    *)
      usage
      ;;
  esac
done

if [ -z "$HOST" ] || [ -z "$PORT" ]; then
  usage
fi

log() {
  if [ "$QUIET" -eq 0 ]; then
    echo "$@"
  fi
}

log "Waiting for $HOST:$PORT (timeout: ${TIMEOUT}s)..."

START=$(date +%s)
while true; do
  if (echo > /dev/tcp/$HOST/$PORT) 2>/dev/null; then
    log "$HOST:$PORT is available after $(($(date +%s) - START))s"
    break
  fi

  ELAPSED=$(($(date +%s) - START))
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "Timeout after ${TIMEOUT}s waiting for $HOST:$PORT" >&2
    exit 1
  fi

  sleep 1
done

# Execute the command if provided
if [ ${#CMD[@]} -gt 0 ]; then
  log "Executing: ${CMD[*]}"
  exec "${CMD[@]}"
fi
