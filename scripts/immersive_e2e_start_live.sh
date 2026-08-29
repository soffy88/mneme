#!/usr/bin/env bash
# Start isolated Immersive live HTTP stack (Docker) for Playwright merge gate.
# - API listens inside compose network on :8000
# - Host publishes 127.0.0.1:<ephemeral> → 8000 (never production :8000)
# - DATABASE_URL forced to mneme_test
# - Media blobs patched to /tmp inside the harness script
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STATE_DIR="${IMMERSIVE_E2E_STATE_DIR:-/tmp/mneme-immersive-e2e}"
mkdir -p "$STATE_DIR"
PORT_FILE="$STATE_DIR/api.port"
PID_FILE="$STATE_DIR/api.docker.pid"
LOG_FILE="$STATE_DIR/api.log"
ENV_FILE="$STATE_DIR/e2e.env"
READY_TIMEOUT="${IMMERSIVE_E2E_READY_TIMEOUT:-180}"

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  # Only export what we need (avoid polluting shell with unrelated secrets usage).
  POSTGRES_PASSWORD="$(grep -E '^POSTGRES_PASSWORD=' "$ROOT/.env" | head -1 | cut -d= -f2-)"
  JWT_SECRET="$(grep -E '^JWT_SECRET=' "$ROOT/.env" | head -1 | cut -d= -f2- || true)"
  MINIO_SECRET_KEY="$(grep -E '^MINIO_SECRET_KEY=' "$ROOT/.env" | head -1 | cut -d= -f2- || true)"
  set +a
fi
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD missing in .env}"
JWT_SECRET="${JWT_SECRET:-mneme-dev-secret-change-in-prod!}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"

# Ephemeral host port (never hardcode 18000 / never 8000).
HOST_PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
if [[ "$HOST_PORT" == "8000" ]]; then
  echo "REFUSING: ephemeral allocator returned 8000" >&2
  exit 2
fi
echo "$HOST_PORT" >"$PORT_FILE"

TEST_DB_URL="postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@db:5432/mneme_test"
HOST_TEST_DB_URL="postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@127.0.0.1:5433/mneme_test"

# Safety assertions
case "$TEST_DB_URL" in
  *sxueji.com*|*api.sxueji.com*)
    echo "REFUSING: test DB URL mentions production hostname" >&2
    exit 2
    ;;
  */mneme_test|*/mneme_test\?*) ;;
  *)
    echo "REFUSING: test DB URL is not mneme_test" >&2
    exit 2
    ;;
esac

echo "==> Ensuring mneme_test schema (alembic)…"
docker compose exec -T \
  -e DATABASE_URL="$TEST_DB_URL" \
  -e PYTHONPATH=/app/vendor:/app:/app/packages/mneme-core:/app/packages/mneme-agent:/app/packages/event-schema \
  api sh -c 'cd /tmp && alembic -c /app/alembic.ini upgrade head' \
  >"$STATE_DIR/alembic.log" 2>&1 || {
    echo "alembic upgrade failed; see $STATE_DIR/alembic.log" >&2
    tail -40 "$STATE_DIR/alembic.log" >&2
    exit 1
  }

echo "==> Starting isolated API on 127.0.0.1:${HOST_PORT} (container :8000, mneme_test)…"
# --rm cleaned on exit; do not touch production mneme-api-1
docker compose run --rm --no-deps \
  -p "127.0.0.1:${HOST_PORT}:8000" \
  -e DATABASE_URL="$TEST_DB_URL" \
  -e IMMERSIVE_E2E_DATABASE_URL="$TEST_DB_URL" \
  -e IMMERSIVE_LEARNING_ENABLED=true \
  -e MNEME_ENV=test \
  -e REGISTRATION_OPEN=1 \
  -e SMS_PROVIDER=mock \
  -e EMAIL_PROVIDER=mock \
  -e MNEME_SKIP_SANDBOX_SELFCHECK=1 \
  -e IMMERSIVE_E2E_HOST=0.0.0.0 \
  -e IMMERSIVE_E2E_PORT=8000 \
  -e JWT_SECRET="$JWT_SECRET" \
  -e REDIS_URL=redis://redis:6379/1 \
  -e MINIO_ENDPOINT=minio:9000 \
  -e MINIO_ACCESS_KEY=minioadmin \
  -e MINIO_SECRET_KEY="$MINIO_SECRET_KEY" \
  -e MINIO_BUCKET=immersive-e2e-test \
  -e PYTHONPATH=/app/vendor:/app:/app/packages/mneme-core:/app/packages/mneme-agent:/app/packages/event-schema \
  -e PYTHONPYCACHEPREFIX=/tmp/mneme-immersive-e2e-pycache \
  api \
  python /app/scripts/immersive_e2e_isolated_api.py \
  >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

API_URL="http://127.0.0.1:${HOST_PORT}"
echo "==> Waiting for health/readiness at ${API_URL} (timeout ${READY_TIMEOUT}s)…"
deadline=$((SECONDS + READY_TIMEOUT))
ok=0
while (( SECONDS < deadline )); do
  if curl -sf "${API_URL}/health" >/dev/null 2>&1 \
    && curl -sf "${API_URL}/readiness" >/dev/null 2>&1; then
    ok=1
    break
  fi
  # Fail fast if docker run exited
  if [[ -f "$PID_FILE" ]] && ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Isolated API process exited before ready. Logs:" >&2
    tail -80 "$LOG_FILE" >&2 || true
    exit 1
  fi
  sleep 1
done

if [[ "$ok" != "1" ]]; then
  echo "TIMEOUT waiting for isolated API. Logs:" >&2
  tail -120 "$LOG_FILE" >&2 || true
  exit 1
fi

# Confirm LISTEN on loopback ephemeral port
if ! ss -ltn | grep -q "127.0.0.1:${HOST_PORT}"; then
  echo "REFUSING: ss does not show LISTEN on 127.0.0.1:${HOST_PORT}" >&2
  exit 1
fi

IMMERSIVE_STATUS="$(curl -sf "${API_URL}/v2/immersive/status" || true)"
echo "immersive status: ${IMMERSIVE_STATUS}"

cat >"$ENV_FILE" <<EOF
IMMERSIVE_E2E_LIVE=1
IMMERSIVE_E2E_API_BASE=${API_URL}
IMMERSIVE_E2E_DATABASE_URL=${HOST_TEST_DB_URL}
DATABASE_URL=${HOST_TEST_DB_URL}
MNEME_ENV=test
IMMERSIVE_LEARNING_ENABLED=true
NEXT_PUBLIC_API_BASE=${API_URL}
NEXT_PUBLIC_IMMERSIVE_MOCK=0
EOF

echo "READY ${API_URL}"
echo "ENV_FILE=${ENV_FILE}"
echo "LOG_FILE=${LOG_FILE}"
echo "PORT=${HOST_PORT}"
