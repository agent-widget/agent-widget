#!/usr/bin/env bash
# Stop the local lab broker (container + persistence volumes are kept).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f broker/docker-compose.yml stop
echo ">> broker stopped (state kept in broker/state/, restart with scripts/start-broker.sh)"
