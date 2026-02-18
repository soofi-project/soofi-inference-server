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
├── ansible/
│   ├── site.yaml                # Ansible Hauptplaybook
│   ├── ansible.cfg              # Ansible Konfiguration
│   ├── requirements.yaml        # Galaxy Collections
│   └── inventory/
│       └── hosts.yaml           # GPU-Server Inventar [gpu_nodes]
├── docs/                        # Ausfuehrliche Dokumentation
├── docker/
│   ├── Dockerfile.ansible       # Ansible Runner Container
│   ├── ansible-run.sh           # Wrapper: fixes NTFS permissions, starts SSH agent
│   ├── docker-compose.ansible.yml  # Ansible runner service
│   ├── docker-compose.yml       # Full Stack (Triton + LiteLLM + Open WebUI)
│   ├── litellm-config.yaml      # LiteLLM Proxy Konfiguration
│   └── .env.example             # Environment Variables
├── kubernetes/                  # K8s Manifeste (Phase 2)
├── models/
│   └── model_repository/        # Triton Model Repository
├── scripts/
│   ├── deploy.sh                # Ansible Deployment (docker compose exec)
│   ├── detect-gpu.sh            # GPU-Erkennung & Parallelismus
│   ├── download-model.sh        # Modell-Download (interaktiv)
│   ├── install-nvidia.sh        # NVIDIA Treiber + CUDA + Container Toolkit
│   └── models.txt               # Verfuegbare Modelle
└── README.md
```

## Infrastructure Automation (Ansible)

To ensure a consistent setup across all lab servers, we use Ansible for provisioning. A pre-configured Docker-based runner is provided to avoid local dependency issues.

### Prerequisites

* **Docker:** Required to build and run the Ansible container locally.
* **VPN:** If you are working from outside the DFKI network, you **must have an active VPN connection** to reach the lab infrastructure.
* **SSH Access:** Your public key must be present in the target server's `~/.ssh/authorized_keys`. The container mounts your `~/.ssh` directory (read-only). An SSH agent is started automatically inside the container — you will be prompted for your key passphrase on each run.

### How to add your SSH Key to the Shared Lab Account

Since we use a shared account (`mrk`), follow these steps to gain access:

1. **Generate your key** (if you haven't already):
```bash
ssh-keygen -t ed25519 -C "vorname.nachname@dfki.de"

```

2. **Add your key to the server**
```bash
# This appends your key to the existing authorized_keys file
ssh-copy-id -i ~/.ssh/id_ed25519.pub mrk@10.2.10.33
```

3. **Verify access:**
```bash
ssh mrk@10.2.10.33
# You should be logged in as mrk@10.2.10.33 without a password prompt.

```


### Project Structure

```text
ansible/
├── site.yaml                # Main playbook (entrypoint)
├── ansible.cfg              # Ansible configuration (auto-loaded)
├── requirements.yaml        # External roles & collections
└── inventory/
    └── hosts.yaml           # Lab server inventory [gpu_nodes]

```

### Usage

The `deploy.sh` script is the central entrypoint. It starts a long-running Ansible container via Docker Compose and executes playbooks inside it with `docker compose exec`.

```bash
# Run the full deployment to all configured nodes
./scripts/deploy.sh

# Perform a dry-run (check mode)
./scripts/deploy.sh --check

# Target only a specific host from the inventory
./scripts/deploy.sh --limit gpu-server-01

# Rebuild the image (required after changes to requirements.yaml)
./scripts/deploy.sh --build
```

### Deployment Flow

1. **Start:** `docker compose up -d` starts the `soofi-ansible-runner` container (builds image on first run).
2. **Execute:** `docker compose exec` runs `ansible-run` (wrapper script) inside the container — fixes NTFS permissions, starts SSH agent, prompts for passphrase, then runs `ansible-playbook`.
3. **Sources:** The `ansible/` directory is mounted as a volume — playbooks and inventory are always current from the repo.
4. **Collections:** Ansible Galaxy collections are baked into the image. Use `--build` to pick up changes to `requirements.yaml`.
