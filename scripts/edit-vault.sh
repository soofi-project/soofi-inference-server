#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# cd to project root so all docker compose paths are relative (avoids MINGW path mangling)
cd "$PROJECT_ROOT"

COMPOSE_FILE="docker/docker-compose.ansible.yml"
VAULT_FILE="inventory/group_vars/gpu_nodes/vault.yaml"

# Parse --encrypt flag (first-time setup: encrypts a plaintext vault file)
ACTION="edit"
if [[ "$1" == "--encrypt" ]]; then
    ACTION="encrypt"
    shift
fi

# Start ansible container if not already running
docker compose -f "$COMPOSE_FILE" up -d

# Run vault command inside the container
# -it required for the interactive editor / password prompt
# MSYS_NO_PATHCONV=1 prevents Git Bash from mangling container-internal paths
MSYS_NO_PATHCONV=1 docker compose -f "$COMPOSE_FILE" exec -it \
    ansible \
    ansible-vault "$ACTION" --ask-vault-pass "$VAULT_FILE"
