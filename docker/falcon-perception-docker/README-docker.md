# Falcon Perception Docker image

This folder provides Docker files for running the `tiiuae/Falcon-Perception` FastAPI inference server on NVIDIA GPUs.

> **Ansible stack:** the production deployment on gpu-server-01 uses a pinned copy of
> `Dockerfile.remote` at `docker/Dockerfile.falcon-perception`, built on the GPU host by
> `stack_deploy.yaml` and configured via the `falcon_perception_service` block in
> `ansible/inventory/group_vars/gpu_nodes/vars.yaml` (host port 8004, not in LiteLLM).
> This folder remains for local/standalone use; when upgrading, bump `REPO_REF` in the
> pinned Dockerfile and the image tag in vars.yaml together.

## Prerequisites

- Docker with NVIDIA Container Toolkit enabled.
- NVIDIA driver compatible with CUDA 12.8 / PyTorch cu128 wheels. The upstream repo notes CUDA 12.8 wheels require NVIDIA driver >= 570.x.
- A GPU with enough VRAM for the selected model and image sizes.

## Option A: build from a local clone

```bash
git clone https://github.com/tiiuae/Falcon-Perception.git
cd Falcon-Perception
cp /path/to/these/files/Dockerfile /path/to/these/files/docker-compose.yml /path/to/these/files/.dockerignore .
docker compose build
```

Run:

```bash
docker compose up
```

Health check:

```bash
curl http://localhost:7860/v1/health
```

## Option B: build directly from GitHub

```bash
docker build \
  -f Dockerfile.remote \
  -t falcon-perception:cuda128 \
  --build-arg REPO_REF=main \
  .
```

Run:

```bash
docker run --rm -it \
  --gpus all \
  --ipc=host \
  --shm-size=16g \
  -p 7860:7860 \
  -e HF_MODEL_ID=tiiuae/Falcon-Perception \
  -e DTYPE=bfloat16 \
  -e NUM_GPUS=-1 \
  -v "$HOME/.cache/huggingface:/models/huggingface" \
  -v "$HOME/.cache/falcon-perception:/cache" \
  falcon-perception:cuda128
```

## Test request

```bash
curl -X POST http://localhost:7860/v1/predictions \
  -H "Content-Type: application/json" \
  -d '{
    "image": {"url": "https://raw.githubusercontent.com/ultralytics/yolov5/master/data/images/zidane.jpg"},
    "query": "person",
    "task": "detection"
  }'
```

## Useful runtime switches

- Full perception model: `-e HF_MODEL_ID=tiiuae/Falcon-Perception`
- OCR model: `-e HF_MODEL_ID=tiiuae/Falcon-OCR`
- Use one GPU: `-e NUM_GPUS=1`
- Disable compile for debugging: `-e COMPILE=false -e CUDAGRAPH=false`
- Max image size: `-e MAX_IMAGE_SIZE=1024`
- Safer dtype: `-e DTYPE=float32`

## Smaller build

The default image installs `server,demo,ocr` extras. For a smaller image that only runs the Falcon Perception server, build with:

```bash
docker build -t falcon-perception:cuda128 --build-arg EXTRAS=server,demo .
```
