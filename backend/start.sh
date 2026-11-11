#!/bin/sh
set -eu
if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then
    alembic upgrade head
fi
exec python -m app.serve
