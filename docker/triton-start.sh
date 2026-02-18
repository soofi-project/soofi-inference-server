#!/bin/bash
# Triton Inference Server with OpenAI-compatible frontend
#
# Starts Triton in-process via the OpenAI frontend (python/openai/openai_frontend/main.py).
# --enable-kserve-frontends exposes the native Triton HTTP/gRPC endpoints alongside
# the OpenAI API, so LiteLLM can still connect to :8000 as before.
#
# Ports:
#   8000 — Triton native HTTP (KServe V2)  — used by LiteLLM
#   8001 — Triton native gRPC
#   8002 — Metrics (Prometheus)
#   9000 — OpenAI-compatible API           — used by LangChain, direct clients

set -e

# Locate the OpenAI frontend script in the Triton image
OPENAI_FRONTEND=""
for candidate in \
    "/opt/tritonserver/python/openai/openai_frontend/main.py" \
    "/usr/local/lib/python3.12/dist-packages/openai_frontend/main.py" \
    "/opt/tritonserver/lib/python3.12/site-packages/openai_frontend/main.py"; do
    if [[ -f "$candidate" ]]; then
        OPENAI_FRONTEND="$candidate"
        break
    fi
done

if [[ -z "$OPENAI_FRONTEND" ]]; then
    echo "ERROR: OpenAI frontend script not found in this Triton image."
    echo "Falling back to plain tritonserver (no OpenAI API)."
    exec tritonserver \
        --model-repository=/models \
        --log-verbose=0 \
        --log-info=1 \
        --log-warning=1 \
        --log-error=1
fi

echo "Starting Triton with OpenAI frontend: $OPENAI_FRONTEND"

exec python3 "$OPENAI_FRONTEND" \
    --model-repository /models \
    --tokenizer "${MODEL_NAME:-Qwen/Qwen2.5-72B-Instruct}" \
    --host 0.0.0.0 \
    --openai-port "${OPENAI_PORT:-9000}" \
    --enable-kserve-frontends \
    --kserve-http-port 8000 \
    --kserve-grpc-port 8001
