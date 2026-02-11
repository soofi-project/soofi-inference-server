#!/bin/bash
set -euo pipefail

#===============================================================================
# Model Download Helper Script
# Downloads models from HuggingFace for use with Triton + vLLM
#===============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_REPO_PATH="${MODEL_REPO_PATH:-${SCRIPT_DIR}/../models/model_repository}"
MODELS_FILE="${SCRIPT_DIR}/models.txt"
LITELLM_CONFIG="${LITELLM_CONFIG:-${SCRIPT_DIR}/../docker/litellm-config.yaml}"
LITELLM_UPDATED=false

# GPU Configuration (adjust for your setup)
# TP=2, PP=1: Tensor Parallelism (default, lower latency)
# TP=1, PP=2: Pipeline Parallelism (better for PCIe without NVLink)
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-2}"
PIPELINE_PARALLEL_SIZE="${PIPELINE_PARALLEL_SIZE:-1}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
CPU_OFFLOAD_GB="${CPU_OFFLOAD_GB:-0}"  # 0 = disabled, >0 = offload GB to CPU RAM

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    echo "Usage: $0 [model-number|model-id] [local-name]"
    echo ""
    echo "Options:"
    echo "  (no args)     Show interactive model selection"
    echo "  1-5           Select model by number from list"
    echo "  <model-id>    Use custom HuggingFace model ID"
    echo ""
    echo "Examples:"
    echo "  $0              # Interactive selection"
    echo "  $0 1            # Select first model from list"
    echo "  $0 Qwen/Qwen2.5-32B-Instruct qwen-32b  # Custom model"
    echo ""
    echo "Environment variables:"
    echo "  HF_TOKEN                 - HuggingFace token (required for gated models)"
    echo "  MODEL_REPO_PATH          - Path to model repository"
    echo "  TENSOR_PARALLEL_SIZE     - Tensor parallel GPUs (default: 2)"
    echo "  PIPELINE_PARALLEL_SIZE   - Pipeline parallel stages (default: 1)"
    echo "  GPU_MEMORY_UTILIZATION   - VRAM usage 0.0-1.0 (default: 0.90)"
    echo ""
    echo "Parallelism modes (for 2 GPUs):"
    echo "  TP=2, PP=1  Tensor Parallel   - Lower latency, needs high bandwidth"
    echo "  TP=1, PP=2  Pipeline Parallel - Better for PCIe (no NVLink)"
    echo "  TP=1, PP=1  Single GPU        - For testing"
    echo ""
    echo "Examples:"
    echo "  $0 3                                              # Default (TP=2)"
    echo "  TENSOR_PARALLEL_SIZE=1 PIPELINE_PARALLEL_SIZE=2 $0 3  # Pipeline mode"
    echo "  TENSOR_PARALLEL_SIZE=1 PIPELINE_PARALLEL_SIZE=1 $0 3  # Single GPU"
    exit 1
}

# Load models from file
load_models() {
    if [[ ! -f "$MODELS_FILE" ]]; then
        log_error "Models file not found: $MODELS_FILE"
        exit 1
    fi

    mapfile -t MODELS < <(grep -v '^#' "$MODELS_FILE" | grep -v '^$')
}

# Show model selection menu
show_menu() {
    echo ""
    echo -e "${BOLD}Available Models:${NC}"
    echo "═══════════════════════════════════════════════════════════════"
    printf "  ${BOLD}%-4s %-32s %-6s %-10s${NC}\n" "#" "Model" "Size" "VRAM"
    echo "───────────────────────────────────────────────────────────────"

    local i=1
    local last_was_comment=""
    for model in "${MODELS[@]}"; do
        local name=$(echo "$model" | cut -d'|' -f2)
        local size=$(echo "$model" | cut -d'|' -f3)
        local vram=$(echo "$model" | cut -d'|' -f4)
        printf "  ${CYAN}%2d)${NC} %-32s ${YELLOW}%-6s${NC} ${GREEN}%-10s${NC}\n" "$i" "$name" "$size" "$vram"
        ((i++))
    done

    echo "═══════════════════════════════════════════════════════════════"
    echo -e "  ${CYAN} 0)${NC} Cancel"
    echo ""
}

# Get model by number
get_model_by_number() {
    local num=$1
    if [[ $num -lt 1 || $num -gt ${#MODELS[@]} ]]; then
        log_error "Invalid selection: $num"
        exit 1
    fi
    echo "${MODELS[$((num-1))]}"
}

# Interactive GPU configuration
configure_gpu() {
    echo ""
    echo -e "${BOLD}GPU Parallelism Configuration:${NC}"
    echo "─────────────────────────────────────────────────"
    echo -e "  ${CYAN}TP=1, PP=2${NC}  Pipeline Parallel (für PCIe ohne NVLink)"
    echo -e "  ${CYAN}TP=2, PP=1${NC}  Tensor Parallel (für NVLink)"
    echo -e "  ${CYAN}TP=1, PP=1${NC}  Single GPU"
    echo "─────────────────────────────────────────────────"
    echo ""

    # Tensor Parallel Size
    read -p "Tensor Parallel Size [${TENSOR_PARALLEL_SIZE}]: " input_tp
    if [[ -n "$input_tp" ]]; then
        TENSOR_PARALLEL_SIZE="$input_tp"
    fi

    # Pipeline Parallel Size
    read -p "Pipeline Parallel Size [${PIPELINE_PARALLEL_SIZE}]: " input_pp
    if [[ -n "$input_pp" ]]; then
        PIPELINE_PARALLEL_SIZE="$input_pp"
    fi

    # GPU Memory Utilization
    read -p "GPU Memory Utilization [${GPU_MEMORY_UTILIZATION}]: " input_mem
    if [[ -n "$input_mem" ]]; then
        GPU_MEMORY_UTILIZATION="$input_mem"
    fi

    # CPU Offload
    echo ""
    echo -e "${YELLOW}CPU Offload: Wenn VRAM nicht ausreicht, können Teile des Modells in RAM ausgelagert werden.${NC}"
    read -p "CPU Offload GB (0=disabled) [${CPU_OFFLOAD_GB}]: " input_offload
    if [[ -n "$input_offload" ]]; then
        CPU_OFFLOAD_GB="$input_offload"
    fi

    echo ""
    log_info "Config: TP=${TENSOR_PARALLEL_SIZE}, PP=${PIPELINE_PARALLEL_SIZE}, GPU_MEM=${GPU_MEMORY_UTILIZATION}, CPU_OFFLOAD=${CPU_OFFLOAD_GB}GB"
}

# Update LiteLLM config
update_litellm_config() {
    local model_name="$1"

    if [[ ! -f "$LITELLM_CONFIG" ]]; then
        log_warn "LiteLLM config not found: $LITELLM_CONFIG"
        log_warn "Skipping LiteLLM configuration."
        return
    fi

    # Check if model already exists in config
    if grep -q "model_name: ${model_name}" "$LITELLM_CONFIG" 2>/dev/null; then
        log_info "Model '${model_name}' already in LiteLLM config."
        return
    fi

    echo ""
    read -p "Add '${model_name}' to LiteLLM config? (Y/n): " add_to_litellm
    if [[ "$add_to_litellm" =~ ^[Nn]$ ]]; then
        return
    fi

    # Insert new model entry after "model_list:" line
    local model_entry="\\
  # ${model_name} via Triton\\
  - model_name: ${model_name}\\
    litellm_params:\\
      model: triton/${model_name}\\
      api_base: http://triton:8000\\
"

    # Use sed to insert after model_list:
    sed -i "/^model_list:/a\\${model_entry}" "$LITELLM_CONFIG"
    log_info "Added '${model_name}' to LiteLLM config."
    LITELLM_UPDATED=true

    # Ask if this should be the default model
    read -p "Set as default model (gpt-4/gpt-3.5-turbo alias)? (y/N): " set_default
    if [[ "$set_default" =~ ^[Yy]$ ]]; then
        # Update gpt-4 and gpt-3.5-turbo aliases
        sed -i "s|model: triton/.*|model: triton/${model_name}|g" "$LITELLM_CONFIG"
        log_info "Set '${model_name}' as default model for OpenAI aliases."
    fi
}

# Setup model configuration
setup_model() {
    local model_id="$1"
    local local_name="$2"

    # Check for HF_TOKEN
    if [[ -z "${HF_TOKEN:-}" ]]; then
        log_warn "HF_TOKEN not set. Gated models will fail to download."
        log_warn "Qwen models don't require a token."
    fi

    # Check for huggingface-cli
    if ! command -v huggingface-cli &> /dev/null; then
        log_info "Installing huggingface-cli..."

        # Check for pipx (recommended for Ubuntu 24.04+)
        if command -v pipx &> /dev/null; then
            pipx install huggingface_hub
        elif [[ -f /etc/debian_version ]]; then
            # Debian/Ubuntu: install pipx first, then huggingface
            log_info "Installing pipx..."
            sudo apt-get update && sudo apt-get install -y pipx
            pipx ensurepath
            pipx install huggingface_hub
            # Reload PATH
            export PATH="$HOME/.local/bin:$PATH"
        else
            # Fallback for non-Debian systems
            pip install --user huggingface_hub
        fi
    fi

    # Login to HuggingFace if token is set
    if [[ -n "${HF_TOKEN:-}" ]]; then
        log_info "Logging in to HuggingFace..."
        huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential 2>/dev/null || true
    fi

    # Create model directory structure
    local model_dir="${MODEL_REPO_PATH}/${local_name}"
    log_info "Creating model directory: ${model_dir}"
    mkdir -p "${model_dir}/1"

    # Create config.pbtxt
    log_info "Creating Triton config for ${local_name}..."
    cat > "${model_dir}/config.pbtxt" << EOF
name: "${local_name}"
backend: "vllm"

input [
  {
    name: "text_input"
    data_type: TYPE_STRING
    dims: [ 1 ]
  },
  {
    name: "stream"
    data_type: TYPE_BOOL
    dims: [ 1 ]
    optional: true
  },
  {
    name: "sampling_parameters"
    data_type: TYPE_STRING
    dims: [ 1 ]
    optional: true
  }
]

output [
  {
    name: "text_output"
    data_type: TYPE_STRING
    dims: [ -1 ]
  }
]

instance_group [
  {
    count: 1
    kind: KIND_MODEL
  }
]

parameters [
  {
    key: "model"
    value: { string_value: "${model_id}" }
  },
  {
    key: "tensor_parallel_size"
    value: { string_value: "${TENSOR_PARALLEL_SIZE}" }
  },
  {
    key: "pipeline_parallel_size"
    value: { string_value: "${PIPELINE_PARALLEL_SIZE}" }
  },
  {
    key: "gpu_memory_utilization"
    value: { string_value: "${GPU_MEMORY_UTILIZATION}" }
  },
  {
    key: "dtype"
    value: { string_value: "auto" }
  }
]
EOF

    # Create model.json (required by Triton vLLM backend)
    log_info "Creating vLLM engine config (TP=${TENSOR_PARALLEL_SIZE}, PP=${PIPELINE_PARALLEL_SIZE}, CPU_OFFLOAD=${CPU_OFFLOAD_GB}GB)..."

    # Build JSON
    {
        echo "{"
        echo "    \"model\": \"${model_id}\","
        echo "    \"disable_log_requests\": true,"
        echo "    \"gpu_memory_utilization\": ${GPU_MEMORY_UTILIZATION},"
        echo "    \"tensor_parallel_size\": ${TENSOR_PARALLEL_SIZE},"
        echo "    \"pipeline_parallel_size\": ${PIPELINE_PARALLEL_SIZE},"
        if [[ "${CPU_OFFLOAD_GB}" -gt 0 ]]; then
            echo "    \"cpu_offload_gb\": ${CPU_OFFLOAD_GB},"
        fi
        echo "    \"dtype\": \"auto\""
        echo "}"
    } > "${model_dir}/1/model.json"

    log_info "Config created at: ${model_dir}/config.pbtxt"
    log_info "Engine config created at: ${model_dir}/1/model.json"
    echo ""
    log_info "Model ${local_name} configured successfully!"
    log_info "The model weights will be downloaded automatically by vLLM on first load."
    echo ""
    log_info "To pre-download the weights, run:"
    log_info "  huggingface-cli download ${model_id}"

    # Update LiteLLM config
    update_litellm_config "${local_name}"
}

# Main
load_models

if [[ $# -eq 0 ]]; then
    # Interactive mode
    show_menu
    read -p "Select model (1-${#MODELS[@]}): " selection

    if [[ "$selection" == "0" ]]; then
        echo "Cancelled."
        exit 0
    fi

    model_line=$(get_model_by_number "$selection")
    MODEL_ID=$(echo "$model_line" | cut -d'|' -f1)
    LOCAL_NAME=$(basename "$MODEL_ID" | tr '[:upper:]' '[:lower:]')

elif [[ "$1" =~ ^[0-9]+$ ]]; then
    # Selection by number
    model_line=$(get_model_by_number "$1")
    MODEL_ID=$(echo "$model_line" | cut -d'|' -f1)
    LOCAL_NAME="${2:-$(basename "$MODEL_ID" | tr '[:upper:]' '[:lower:]')}"

elif [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage

else
    # Custom model ID
    MODEL_ID="$1"
    LOCAL_NAME="${2:-$(basename "$MODEL_ID" | tr '[:upper:]' '[:lower:]')}"
fi

echo ""
log_info "Selected model: ${MODEL_ID}"

# Interactive GPU configuration
configure_gpu

setup_model "$MODEL_ID" "$LOCAL_NAME"

# Show restart hints
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo "─────────────────────────────────────────────────"
if [[ "$LITELLM_UPDATED" == true ]]; then
    echo -e "  ${YELLOW}1.${NC} Restart LiteLLM to load new config:"
    echo "     docker compose -f docker/docker-compose.yml restart litellm"
    echo ""
    echo -e "  ${YELLOW}2.${NC} Restart Triton to load new model:"
    echo "     docker compose -f docker/docker-compose.yml restart triton"
else
    echo -e "  ${YELLOW}1.${NC} Restart Triton to load new model:"
    echo "     docker compose -f docker/docker-compose.yml restart triton"
fi
echo "─────────────────────────────────────────────────"
