# syntax=docker/dockerfile:1.7
# GPU image for tiiuae/Falcon-Perception FastAPI inference server.
# Build from the root of https://github.com/tiiuae/Falcon-Perception.

ARG BASE_IMAGE=nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
ARG EXTRAS=server,demo,ocr

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HF_HOME=/models/huggingface \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    XDG_CACHE_HOME=/cache \
    TORCHINDUCTOR_CACHE_DIR=/cache/torchinductor \
    TRITON_CACHE_DIR=/cache/triton \
    PYTORCH_ALLOC_CONF=expandable_segments:True

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-venv \
      python3-dev \
      python3-pip \
      git \
      build-essential \
      ca-certificates \
      curl \
      libglib2.0-0 \
      libgl1 \
      libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv "$VIRTUAL_ENV" \
    && python -m pip install --upgrade pip setuptools wheel

WORKDIR /workspace/falcon-perception
COPY . .

# Install PyTorch explicitly from the CUDA 12.8 wheel index, then install the repo extras.
# Use --build-arg EXTRAS=server,demo for a smaller image that excludes OCR layout dependencies.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install torch torchvision --index-url "$TORCH_INDEX_URL" \
    && python -m pip install -e ".[${EXTRAS}]" \
    && mkdir -p /models/huggingface /cache/torchinductor /cache/triton /data/images

EXPOSE 7860
VOLUME ["/models/huggingface", "/cache", "/data/images"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15m --retries=3 \
  CMD python -c "import json,sys,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:7860/v1/health',timeout=5)); sys.exit(0 if d.get('status') in ('loading','ready') else 1)" || exit 1

ENTRYPOINT ["python", "-m", "falcon_perception.server"]
CMD ["--config.host", "0.0.0.0", "--config.port", "7860"]
