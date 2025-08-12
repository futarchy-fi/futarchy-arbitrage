#!/usr/bin/env bash
set -euo pipefail

# Wrapper to source an env file and deploy+verify V5
# Usage: ./scripts/deploy_v5.sh [.env.file]

ENV_FILE=${1:-.env.0x9590dAF4d5cd4009c3F9767C5E7668175cFd37CF}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: $ENV_FILE" >&2
  exit 1
fi

echo "Sourcing $ENV_FILE"
set -a
source "$ENV_FILE"
set +a

echo "Deploying FutarchyArbExecutorV5 to Gnosis..."
python3 scripts/deploy_executor_v5.py

