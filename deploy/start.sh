#!/usr/bin/env bash
# Boots the demo container: Postgres -> migrations -> API -> web -> nginx.
# Everything lives under /tmp, so a Space restart starts from a clean slate.
set -euo pipefail

DATA=/tmp/papertrail
PGDATA="$DATA/pg"
mkdir -p "$DATA/storage"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  initdb -D "$PGDATA" -U papertrail --auth=trust >/dev/null
fi
pg_ctl -D "$PGDATA" -l "$DATA/postgres.log" -w \
  -o "-c listen_addresses=127.0.0.1 -c unix_socket_directories=$DATA" start
createdb -h 127.0.0.1 -U papertrail papertrail 2>/dev/null || true

export DATABASE_URL="postgresql+asyncpg://papertrail@127.0.0.1:5432/papertrail"
# Local mode (no accounts) is safe here only because nginx is the sole public
# listener; a fresh random secret per boot since no session outlives a restart.
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(48))')}"
export LOCAL_MODE=true
export LOCAL_PROVIDERS_ENABLED=false
export STORAGE_DIR="$DATA/storage"

cd /app/backend
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers &
(cd /app/frontend && HOSTNAME=127.0.0.1 PORT=3000 exec node server.js) &
nginx -c /app/deploy/nginx.conf -g 'daemon off;' &

# If any service dies, exit so the Space restarts instead of serving 502s.
wait -n
exit 1
