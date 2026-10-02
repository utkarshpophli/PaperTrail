#!/usr/bin/env bash
# Boots the demo container: Postgres -> migrations -> API -> web -> nginx.
# Everything lives under /data: mount a volume there to keep papers across
# restarts (the hosted demo doesn't, so it starts clean on every restart).
set -euo pipefail

DATA=/data
PGDATA="$DATA/pg"
mkdir -p "$DATA/storage"
# A container that was killed leaves a stale lock; nothing else can own it here.
rm -f "$PGDATA/postmaster.pid"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  initdb -D "$PGDATA" -U papertrail --auth=trust >/dev/null
fi
pg_ctl -D "$PGDATA" -l "$DATA/postgres.log" -w \
  -o "-c listen_addresses=127.0.0.1 -c unix_socket_directories=$DATA" start
createdb -h 127.0.0.1 -U papertrail papertrail 2>/dev/null || true

export DATABASE_URL="postgresql+asyncpg://papertrail@127.0.0.1:5432/papertrail"
# Local mode (no accounts) is safe here only because nginx is the sole
# listener; a fresh random secret per boot since no session outlives a restart.
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(48))')}"
export LOCAL_MODE=true
# On the shared demo, "localhost" is the server, not the visitor: no local models.
if [ "${DEMO_MODE:-0}" = "1" ]; then export LOCAL_PROVIDERS_ENABLED=false; fi
export STORAGE_DIR="$DATA/storage"

cd /app/backend
alembic upgrade head
# Bundled example papers (first boot only; skipped, not fatal, if arXiv is unreachable).
python -m app.example_papers load || echo "example papers skipped"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers &
(cd /app/frontend && HOSTNAME=127.0.0.1 PORT=3000 exec node server.js) &
nginx -c /app/deploy/nginx.conf -g 'daemon off;' &

# If any service dies, exit so the Space restarts instead of serving 502s.
wait -n
exit 1
