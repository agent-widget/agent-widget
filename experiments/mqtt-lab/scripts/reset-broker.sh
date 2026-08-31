#!/usr/bin/env bash
# Wipe all broker state (users, persisted sessions, queued messages, data).
# The next start-broker.sh run reprovisions everything from scratch.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f broker/docker-compose.yml down -v 2>/dev/null || true
rm -rf broker/state
echo ">> broker state wiped. Run scripts/start-broker.sh to start fresh."
