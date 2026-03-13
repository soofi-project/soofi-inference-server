#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

COMPOSE_FILE="docker/docker-compose.ansible.yml"

# Parse --nvidia flag (also removes NVIDIA driver, CUDA, container toolkit)
EXTRA_VARS=""
if [[ "$1" == "--nvidia" ]]; then
    echo "⚠  Will also remove NVIDIA packages (driver, CUDA, container toolkit)."
    EXTRA_VARS="-e remove_nvidia=true"
    shift
fi

docker compose -f "$COMPOSE_FILE" up -d

MSYS_NO_PATHCONV=1 docker compose -f "$COMPOSE_FILE" exec -it \
    ansible \
    ansible-run playbooks/remove_triton.yaml -i inventory/hosts.yaml --ask-vault-pass $EXTRA_VARS "$@"
