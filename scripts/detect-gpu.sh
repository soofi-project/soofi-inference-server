#!/bin/bash
#===============================================================================
# GPU Detection Script
# Detects GPU hardware and recommends parallelism configuration.
#
# Usage:
#   source scripts/detect-gpu.sh       # Load as env vars
#   bash scripts/detect-gpu.sh         # Print detected config
#
# Respects existing env vars:
#   TENSOR_PARALLEL_SIZE, PIPELINE_PARALLEL_SIZE  - will not be overridden
#===============================================================================

_detect_gpu_config() {
    local gpu_count=0
    local interconnect="none"
    local recommended_tp=1
    local recommended_pp=1
    local cuda_devices=""

    # Detect GPU count
    if command -v nvidia-smi &> /dev/null; then
        gpu_count=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l)
        gpu_count=${gpu_count:-0}
    fi

    if [[ "$gpu_count" -eq 0 ]]; then
        # No GPUs detected (CI, container without GPU, etc.)
        interconnect="none"
        recommended_tp=1
        recommended_pp=1
        cuda_devices=""
    elif [[ "$gpu_count" -eq 1 ]]; then
        interconnect="none"
        recommended_tp=1
        recommended_pp=1
        cuda_devices="0"
    else
        # Multi-GPU: detect interconnect type
        cuda_devices=$(seq -s, 0 $((gpu_count - 1)))

        local topo_output
        topo_output=$(nvidia-smi topo -m 2>/dev/null || true)

        if echo "$topo_output" | grep -qE 'NV[0-9]+'; then
            # NVLink detected -> Tensor Parallel is preferred
            interconnect="nvlink"
            recommended_tp=$gpu_count
            recommended_pp=1
        else
            # PCIe (PIX/PHB/SYS) -> Pipeline Parallel is preferred
            interconnect="pcie"
            recommended_tp=1
            recommended_pp=$gpu_count
        fi
    fi

    # Export values (respect existing env var overrides)
    GPU_COUNT=$gpu_count
    GPU_INTERCONNECT=$interconnect
    TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-$recommended_tp}"
    PIPELINE_PARALLEL_SIZE="${PIPELINE_PARALLEL_SIZE:-$recommended_pp}"
    CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-$cuda_devices}"

    export GPU_COUNT GPU_INTERCONNECT TENSOR_PARALLEL_SIZE PIPELINE_PARALLEL_SIZE CUDA_VISIBLE_DEVICES
}

# Run detection
_detect_gpu_config

# If executed directly (not sourced), print the results
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "GPU_COUNT=$GPU_COUNT"
    echo "GPU_INTERCONNECT=$GPU_INTERCONNECT"
    echo "TENSOR_PARALLEL_SIZE=$TENSOR_PARALLEL_SIZE"
    echo "PIPELINE_PARALLEL_SIZE=$PIPELINE_PARALLEL_SIZE"
    echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
fi
