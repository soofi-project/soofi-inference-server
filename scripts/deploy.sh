#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# cd to project root so all docker compose paths are relative (avoids MINGW path mangling)
cd "$PROJECT_ROOT"

COMPOSE_FILE="docker/docker-compose.ansible.yml"

# Parse --build flag (triggers image rebuild, e.g. after requirements.yaml changes)
BUILD_FLAG=""
if [[ "$1" == "--build" ]]; then
    BUILD_FLAG="--build"
    shift
fi

# Start ansible container (or rebuild image if --build)
docker compose -f "$COMPOSE_FILE" up -d $BUILD_FLAG

# Run the playbook inside the container
# -it required for interactive prompts (SSH key passphrases, sudo password via -K)
# MSYS_NO_PATHCONV=1 prevents Git Bash from mangling container-internal paths
MSYS_NO_PATHCONV=1 docker compose -f "$COMPOSE_FILE" exec -it \
    ansible \
    ansible-run site.yaml -i inventory/hosts.yaml --ask-vault-pass "$@"
