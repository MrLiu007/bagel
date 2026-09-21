#!/usr/bin/env sh
# Thin wrapper around docker compose for Bagel（贝果）.
# Usage: ./docker-up.sh up -d --build
set -eu
cd "$(dirname "$0")"
exec docker compose "$@"
