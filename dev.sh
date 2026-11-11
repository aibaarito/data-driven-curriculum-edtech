#!/usr/bin/env bash
# Local development without Docker: embedded PostgreSQL 17 + FastAPI + Next.js.
# Usage: ./dev.sh setup   (first time)   ./dev.sh start   ./dev.sh stop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PG="${DDC_PG_BIN:-$ROOT/devdb/node_modules/@embedded-postgres/darwin-arm64/native/bin}"
PGDATA="${DDC_PGDATA:-$ROOT/devdb/data}"
PORT_DB="${PORT_DB:-55433}"
PYTHON="${DDC_PYTHON:-$ROOT/backend/.venv/bin/python}"

case "${1:-start}" in
  setup)
    mkdir -p "$ROOT/devdb"
    (cd "$ROOT/devdb" && [ -f package.json ] || echo '{"name":"devdb","private":true}' > package.json)
    (cd "$ROOT/devdb" && npm i @embedded-postgres/darwin-arm64@17.11.0-beta.19)
    if [ ! -d "$PGDATA" ]; then
      echo "ddc_dev_pw" > "$ROOT/devdb/pwfile"
      "$PG/initdb" -D "$PGDATA" -U ddc --pwfile="$ROOT/devdb/pwfile" -A scram-sha-256 -E UTF8 --locale=C
    fi
    "$PG/pg_ctl" -D "$PGDATA" -o "-p $PORT_DB -k /tmp -h 127.0.0.1" -l "$ROOT/devdb/pg.log" -w start
    (cd "$ROOT/backend" && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt && PORT_DB="$PORT_DB" python - <<'EOF'
import os
import psycopg
c = psycopg.connect(f"postgresql://ddc:ddc_dev_pw@127.0.0.1:{int(os.environ['PORT_DB'])}/postgres", autocommit=True)
for db in ("ddc", "ddc_test"):
    if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db,)).fetchone():
        c.execute(f"CREATE DATABASE {db}")
EOF
    )
    (cd "$ROOT/frontend" && npm ci)
    if [ ! -f "$ROOT/backend/.env" ]; then
      # Local development only: reset is enabled with a random admin token kept in the git-ignored backend/.env.
      ADMIN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
      printf "ENABLE_DATA_RESET=true\nADMIN_TOKEN=%s\n" "$ADMIN" > "$ROOT/backend/.env"
      chmod 600 "$ROOT/backend/.env"
      echo "Created backend/.env (local reset enabled; the admin token is stored there)."
    fi
    echo "Setup complete. Run ./dev.sh start"
    ;;
  start)
    # Check service ports before starting even this checkout's database.
    for port in "${BACKEND_PORT:-8010}" "${FRONTEND_PORT:-3010}"; do
      if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "Port $port is in use; refusing to change running services." >&2
        exit 1
      fi
    done
    "$PG/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1 || \
      "$PG/pg_ctl" -D "$PGDATA" -o "-p $PORT_DB -k /tmp -h 127.0.0.1" -l "$ROOT/devdb/pg.log" -w start
    "$PYTHON" "$ROOT/backend/scripts/local_services.py" start
    ;;
  stop)
    "$PYTHON" "$ROOT/backend/scripts/local_services.py" stop
    ;;
esac
