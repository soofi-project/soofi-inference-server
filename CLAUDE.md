# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains documentation and scripts for setting up and configuring an AI inference server from scratch. It covers hardware selection, OS installation, driver setup, and deployment of inference frameworks.

## Repository Structure

```
soofi-inference-server/
├── ansible/
│   ├── site.yaml                # Main playbook (entrypoint)
│   ├── ansible.cfg              # Ansible configuration (auto-loaded)
│   ├── requirements.yaml        # Galaxy roles & collections
│   └── inventory/
│       └── hosts.yaml           # GPU server inventory [gpu_nodes]
├── docs/
│   ├── 01-os-setup.md           # Ubuntu 24.04 Installation
│   ├── 02-nvidia-setup.md       # Driver, CUDA, Container Toolkit
│   ├── 03-docker-deployment.md  # Docker Compose Setup
│   ├── 04-kubernetes-setup.md   # K8s Migration
│   └── 05-open-webui-setup.md   # Open WebUI + LiteLLM
├── docker/
│   ├── Dockerfile.ansible       # Ansible runner container
│   ├── docker-compose.yml       # Full Stack (Triton + LiteLLM + Open WebUI)
│   ├── litellm-config.yaml      # LiteLLM Proxy Configuration
│   └── .env.example             # Environment Variables
├── kubernetes/
│   ├── namespace.yaml
│   ├── triton-deployment.yaml
│   ├── triton-service.yaml
│   ├── litellm-deployment.yaml
│   ├── open-webui-deployment.yaml
│   ├── storage.yaml
│   ├── secrets.yaml.example
│   └── gpu-resource-quota.yaml
├── models/
│   └── model_repository/        # Triton Model Repository
│       └── <model_name>/
│           └── config.pbtxt
└── scripts/
    ├── deploy.sh                # Ansible deployment (docker run)
    ├── install-nvidia.sh        # NVIDIA Stack Installation
    ├── detect-gpu.sh            # GPU Detection & Parallelism Config
    ├── download-model.sh        # Model Download (interaktiv)
    └── models.txt               # Verfügbare Modelle (bis 30B)
```

## Key Commands

```bash
# Ansible Deployment
./scripts/deploy.sh                       # Start container + run playbook
./scripts/deploy.sh --build              # Rebuild image (after requirements.yaml changes)
./scripts/deploy.sh --check              # Dry-run (check mode)
./scripts/deploy.sh --limit gpu-server-01  # Target specific host

# NVIDIA Setup
./scripts/install-nvidia.sh              # Driver + CUDA + Container Toolkit

# Docker Deployment
docker compose -f docker/docker-compose.yml up -d    # Start Stack
docker compose -f docker/docker-compose.yml down     # Stop Stack
docker compose -f docker/docker-compose.yml logs -f  # View Logs

# Kubernetes Deployment
kubectl apply -f kubernetes/                         # Deploy to K8s
kubectl get pods -n triton-inference                 # Check Pods

# GPU Detection
bash scripts/detect-gpu.sh                           # Show GPU config
source scripts/detect-gpu.sh                         # Load as env vars

# Model Management
./scripts/download-model.sh                          # Interaktive Auswahl
./scripts/download-model.sh 1                        # Model #1 aus Liste

# Health & Endpoints
curl localhost:8000/v2/health/ready                  # Triton Health
curl localhost:4000/health                           # LiteLLM Health
http://localhost:3000                                # Open WebUI
```

## Hardware Specifications

| Component | Specification |
|-----------|---------------|
| GPU | 2x NVIDIA H200 (141 GB HBM3e each, 282 GB total) |
| GPU Interconnect | PCIe 5.0 (kein NVLink) |
| CPU | 2x AMD EPYC GENOA 9124 (16 Cores, 32 Threads each, 200W TDP) |
| RAM | 256 GB |
| Storage | 1x 3.84 TB SSD |

### Hardware Notes

- **GPU Memory**: 282 GB combined VRAM allows running very large models (e.g., Qwen2.5-72B, Nemotron, or multiple smaller models)
- **PCIe 5.0 vs NVLink**: Tensor parallelism across both GPUs will have higher latency than NVLink. For inference, this is acceptable but pipeline parallelism may be preferable for some workloads
- **CPU**: 32 total cores (64 threads) - sufficient for preprocessing and serving multiple concurrent requests

## Software Stack

| Layer | Component |
|-------|-----------|
| OS | Ubuntu Server 24.04 LTS |
| GPU Driver | NVIDIA Driver 550+ |
| CUDA | 12.4+ |
| Container Runtime | Docker + NVIDIA Container Toolkit |
| Web UI | Open WebUI |
| API Proxy | LiteLLM (OpenAI-kompatibel) |
| Inference Server | NVIDIA Triton Inference Server |
| LLM Backend | vLLM (als Triton Backend) |

### Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Open WebUI    │────▶│    LiteLLM      │────▶│     Triton      │
│   (Port 3000)   │     │   (Port 4000)   │     │   (Port 8000)   │
│                 │     │                 │     │                 │
│  Chat Interface │     │  OpenAI API     │     │  vLLM Backend   │
└─────────────────┘     │  Kompatibilität │     │  TP=2           │
                        └─────────────────┘     └────────┬────────┘
                                                         │
                                                ┌────────┴────────┐
                                                ▼                 ▼
                                          ┌──────────┐      ┌──────────┐
                                          │ H200 #0  │◄────►│ H200 #1  │
                                          │  141 GB  │PCIe5 │  141 GB  │
                                          └──────────┘      └──────────┘
```

### Triton + vLLM Integration

- Triton nutzt das **vLLM Backend** für LLM-Inference
- Modelle werden im Triton Model Repository konfiguriert (`config.pbtxt` + `model.json`)
- Triton stellt gRPC (Port 8001) und HTTP (Port 8000) APIs bereit

### GPU Parallelismus

| Modus | Config | Empfohlen für |
|-------|--------|---------------|
| **Pipeline Parallel** | TP=1, PP=2 | PCIe ohne NVLink (dieser Server) |
| Tensor Parallel | TP=2, PP=1 | NVLink Verbindungen |

Da die H200 GPUs über **PCIe 5.0** (nicht NVLink) verbunden sind, ist **Pipeline Parallel (PP=2)** empfohlen.

## Deployment Phases

### Phase 1: Docker (Entwicklung & Test)

Einfaches Setup mit Docker Compose für initiale Tests und Entwicklung.

```bash
# Stack starten
docker compose -f docker/docker-compose.yml up -d

# Logs prüfen
docker compose -f docker/docker-compose.yml logs -f triton

# Health Check
curl localhost:8000/v2/health/ready
```

**Vorteile:**
- Schnelles Setup
- Einfaches Debugging
- Ideal für Model-Tests und Benchmarking

### Phase 2: Kubernetes (Produktion)

Migration zu Kubernetes für Production Workloads.

**Komponenten:**
- NVIDIA GPU Operator (automatische Driver/Toolkit Installation)
- Triton Deployment mit GPU Resource Requests
- Horizontal Pod Autoscaling (optional)
- Prometheus/Grafana Monitoring

```bash
# GPU Operator installieren
helm install gpu-operator nvidia/gpu-operator

# Triton deployen
kubectl apply -f kubernetes/
```

## Development Notes

- Model Weights werden automatisch von HuggingFace heruntergeladen (HF_TOKEN erforderlich für gated Models)
- Erste Inference nach Model-Load kann langsamer sein (Warmup)
- GPU Memory Utilization von 0.90 lässt Spielraum für KV-Cache bei langen Kontexten
- Triton vLLM Backend benötigt `config.pbtxt` UND `1/model.json` pro Model
- Download-Script: `./scripts/download-model.sh` (interaktive Modell-Auswahl, GPU auto-detected via `detect-gpu.sh`, override via `TENSOR_PARALLEL_SIZE`, `PIPELINE_PARALLEL_SIZE`)
