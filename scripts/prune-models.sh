#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

COMPOSE_FILE="docker/docker-compose.ansible.yml"

docker compose -f "$COMPOSE_FILE" up -d

MSYS_NO_PATHCONV=1 docker compose -f "$COMPOSE_FILE" exec -it \
    ansible \
    ansible-run playbooks/prune_models.yaml -i inventory/hosts.yaml --ask-vault-pass "$@"
