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

# Locate the qwen3 tool call parser (installed by Dockerfile.triton)
QWEN3_PARSER="$(dirname "$OPENAI_FRONTEND")/engine/utils/tool_call_parsers/qwen3_tool_call_parser.py"

TOOL_CALL_ARGS=()
if [[ -n "${TOOL_CALL_PARSER:-}" ]]; then
    TOOL_CALL_ARGS+=("--tool-call-parser" "${TOOL_CALL_PARSER}")
fi

# We launch main.py via `python3 -c` + runpy so we can pre-register the
# Qwen3 tool call parser in the same process before TritonLLMEngine is
# instantiated (which is when ToolParserManager.get_tool_parser_cls runs).
# Direct `python3 main.py` would not give us that hook.
CHAT_TEMPLATE="$(dirname "${OPENAI_FRONTEND}")/../../qwen3_no_think.jinja"
if [[ ! -f "${CHAT_TEMPLATE}" ]]; then
    CHAT_TEMPLATE="/opt/tritonserver/python/qwen3_no_think.jinja"
fi

exec python3 -c "
import sys, os, runpy

# Fix sys.argv: [-c, FRONTEND, ...args...] -> [FRONTEND, ...args...]
sys.argv = sys.argv[1:]

# Replicate what 'python3 main.py' does: add main.py's directory to sys.path
_frontend_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
if _frontend_dir not in sys.path:
    sys.path.insert(0, _frontend_dir)

# Register Qwen3 tool call parser via normal package import (sys.path already set)
try:
    import importlib
    importlib.import_module('engine.utils.tool_call_parsers.qwen3_tool_call_parser')
    print('[triton-start] qwen3_coder tool call parser registered')
except Exception as _e:
    print(f'[triton-start] WARNING: could not register qwen3_coder parser: {_e}', file=sys.stderr)

# Hand off to the real main.py
runpy.run_path(sys.argv[0], run_name='__main__')
" \
    "${OPENAI_FRONTEND}" \
    --model-repository /models \
    --tokenizer "${MODEL_NAME}" \
    --chat-template "${CHAT_TEMPLATE}" \
    --host 0.0.0.0 \
    --openai-port "${OPENAI_PORT:-9000}" \
    --enable-kserve-frontends \
    --kserve-http-port 8000 \
    --kserve-grpc-port 8001 \
    "${TOOL_CALL_ARGS[@]}"
