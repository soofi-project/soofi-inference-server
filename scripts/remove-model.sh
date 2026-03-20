#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INVENTORY="$PROJECT_ROOT/ansible/inventory/hosts.yaml"
DEPLOY_DIR="/opt/soofi"

# Parse server connection from inventory
SERVER=$(grep 'ansible_host:' "$INVENTORY" | head -1 | awk '{print $2}')
SSH_USER=$(grep 'ansible_user:' "$INVENTORY" | head -1 | awk '{print $2}')
SSH_TARGET="${SSH_USER:-mrk}@${SERVER}"

MODEL_NAME="$1"   # name field from vars.yaml (e.g. qwen35-122b-fp8)
HF_NAME="$2"      # hf_name field from vars.yaml (e.g. Qwen/Qwen3.5-122B-A10B-FP8)

if [[ -z "$MODEL_NAME" || -z "$HF_NAME" ]]; then
    echo "Usage: $0 <name> <hf_name>"
    echo "Example: $0 qwen35-122b-fp8 Qwen/Qwen3.5-122B-A10B-FP8"
    echo ""
    echo "Model names can be found in ansible/inventory/group_vars/gpu_nodes/vars.yaml"
    exit 1
fi

HF_CACHE_PATH="$DEPLOY_DIR/models/hf_cache/hub/models--${HF_NAME//\//--}"

echo "Checking disk usage on $SERVER..."
CACHE_SIZE=$(ssh "$SSH_TARGET" "du -sh '$HF_CACHE_PATH' 2>/dev/null | cut -f1" || echo "not found")

echo ""
echo "Model:      $HF_NAME  ($MODEL_NAME)"
echo "  HF cache: $HF_CACHE_PATH  ($CACHE_SIZE)"
echo ""
echo "Step 1: Stop vLLM container (vllm-$MODEL_NAME)"
read -r -p "  Stop container? [y/N] " confirm_stop
if [[ "$confirm_stop" =~ ^[Yy]$ ]]; then
    ssh "$SSH_TARGET" "docker compose -f $DEPLOY_DIR/docker/docker-compose.yml stop vllm-$MODEL_NAME" || true
    echo "  Done."
fi

echo ""
echo "Step 2: Delete HF cache ($CACHE_SIZE) — ⚠  requires full re-download to use this model again"
read -r -p "  Delete HF cache? [y/N] " confirm_cache
if [[ "$confirm_cache" =~ ^[Yy]$ ]]; then
    ssh "$SSH_TARGET" "rm -rf '$HF_CACHE_PATH'"
    echo "  Done."
fi

echo ""
echo "Remember: remove the model entry from ansible/inventory/group_vars/gpu_nodes/vars.yaml"
echo "The container will be removed automatically on the next deploy (--remove-orphans)."
