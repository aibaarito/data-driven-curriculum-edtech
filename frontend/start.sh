#!/bin/sh
set -eu
exec node node_modules/next/dist/bin/next start -p "${PORT:-3010}" -H "${HOSTNAME_BIND:-::}"
