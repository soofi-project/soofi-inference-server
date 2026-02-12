# Soofi Inference Server

Self-hosted AI Inference Server mit NVIDIA Triton, vLLM, LiteLLM und Open WebUI.

## Architektur

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Open WebUI    │────>│    LiteLLM      │────>│     Triton      │
│   (Port 3000)   │     │   (Port 4000)   │     │   (Port 8000)   │
│  Chat Interface │     │  OpenAI API     │     │  vLLM Backend   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

- **Triton Inference Server** mit vLLM Backend fuer GPU-beschleunigte LLM-Inference
- **LiteLLM Proxy** stellt eine OpenAI-kompatible API bereit
- **Open WebUI** bietet ein Chat-Interface im Browser

## Quickstart

```bash
# 1. Environment konfigurieren
cp docker/.env.example docker/.env
vim docker/.env   # HF_TOKEN, GPU-Settings anpassen

# 2. Modell hinzufuegen
./scripts/download-model.sh

# 3. Stack starten
docker compose -f docker/docker-compose.yml up -d

# 4. Health pruefen
curl http://localhost:8000/v2/health/ready   # Triton
curl http://localhost:4000/health             # LiteLLM
# Open WebUI: http://localhost:3000
```

## Hardware-Anforderungen

| Komponente | Minimum | Empfohlen |
|-----------|---------|-----------|
| GPU | 1x NVIDIA (Turing+, >=12 GB VRAM) | 1-2x NVIDIA (>=40 GB VRAM) |
| CPU | 8 Cores | 16+ Cores |
| RAM | 32 GB | 64+ GB |
| Storage | 100 GB SSD | 500+ GB SSD |

Unterstuetzt werden Single- und Multi-GPU-Setups. Bei 2 GPUs wird je nach Interconnect automatisch Pipeline Parallel (PCIe) oder Tensor Parallel (NVLink) konfiguriert.

## Software Stack

| Schicht | Komponente |
|---------|-----------|
| Inference Server | NVIDIA Triton (26.01) + vLLM 0.13.0 |
| API Proxy | LiteLLM (OpenAI-kompatibel) |
| Web UI | Open WebUI |
| Container Runtime | Docker + NVIDIA Container Toolkit |
| OS | Ubuntu Server 24.04 LTS |

## Treiber / CUDA / Triton Kompatibilitaet

Die Wahl des Triton-Images bestimmt die benoetigte CUDA- und Treiber-Version:

| Triton Image | CUDA | vLLM | Min. Treiber (Linux) | Min. Treiber (WSL2) |
|-------------|------|------|---------------------|---------------------|
| 24.08 | 12.6.0 | 0.5.3 | >=560.28 | >=560.76 |
| 25.01 | 12.8.0 | 0.6.3 | >=570.26 | >=570.65 |
| 25.10 | 13.0.2 | 0.10.2 | >=575 | >=575 |
| **26.01** | **13.1.1** | **0.13.0** | **>=590.48 empf.** | **>=590.48 empf.** |

Vollstaendige Matrix: [docs/03-docker-deployment.md](docs/03-docker-deployment.md#treiber--cuda--triton-kompatibilität)

## Dokumentation

| Dokument | Inhalt |
|----------|--------|
| [01 - OS Setup](docs/01-os-setup.md) | Ubuntu 24.04 Installation |
| [02 - NVIDIA Setup](docs/02-nvidia-setup.md) | Treiber, CUDA, Container Toolkit |
| [03 - Docker Deployment](docs/03-docker-deployment.md) | Docker Compose, LiteLLM, Kompatibilitaet, Troubleshooting |
| [04 - Kubernetes Setup](docs/04-kubernetes-setup.md) | K8s Migration |
| [05 - Open WebUI Setup](docs/05-open-webui-setup.md) | Open WebUI + LiteLLM |

## Projekt-Struktur

```
soofi_inference_server/
├── docs/                        # Ausfuehrliche Dokumentation
├── docker/
│   ├── docker-compose.yml       # Full Stack (Triton + LiteLLM + Open WebUI)
│   ├── litellm-config.yaml      # LiteLLM Proxy Konfiguration
│   └── .env.example             # Environment Variables
├── kubernetes/                  # K8s Manifeste (Phase 2)
├── models/
│   └── model_repository/        # Triton Model Repository
├── scripts/
│   ├── detect-gpu.sh            # GPU-Erkennung & Parallelismus
│   ├── download-model.sh        # Modell-Download (interaktiv)
│   └── models.txt               # Verfuegbare Modelle
└── README.md
```
