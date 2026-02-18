# Soofi Inference Server

Self-hosted AI inference server based on NVIDIA Triton + vLLM on H200 hardware.
Provisioned via Ansible, operated via Docker Compose.

## Architecture

```
Clients / Soofi Trainer
        │
        ▼
┌───────────────────────────┐
│    Triton Inference Server │
│                            │
│  Port 9000 — OpenAI API   │  ← /v1/chat/completions
│  Port 8000 — KServe V2    │  ← internal / LiteLLM
│  Port 8001 — gRPC         │
│  Port 8002 — Metrics      │
│                            │
│  vLLM Backend              │
└───────────────────────────┘
        │
   ┌────┴────┐
   ▼         ▼
H200 #0   H200 #1
(141 GB)  (141 GB)
```

> **Note:** LiteLLM and Open WebUI are still in the stack but will be removed in T-06-7.
> After cleanup, port 9000 will be the only external endpoint.

## Quickstart (local Docker Compose)

```bash
# 1. Create secrets file once (outside the repo)
echo "HF_TOKEN=hf_your_token_here" > ~/.env.secrets

# 2. Start the stack (docker/.env is committed with sensible defaults)
docker compose -f docker/docker-compose.yml up -d

# 3. Verify
curl http://localhost:8000/v2/health/ready   # Triton KServe
curl http://localhost:9000/v1/models         # OpenAI frontend
```

## Hardware

| Component | Spec |
|-----------|------|
| GPU | 2x NVIDIA H200 NVL (141 GB HBM3e, 282 GB total) |
| GPU Interconnect | PCIe 5.0 (no NVLink → Pipeline Parallel recommended) |
| CPU | 2x AMD EPYC GENOA 9124 (32 cores / 64 threads) |
| RAM | 256 GB |
| Storage | 3.84 TB SSD |

## Triton + vLLM Compatibility

| Triton Image | CUDA | vLLM | Min. Driver |
|-------------|------|------|------------|
| 24.08 | 12.6 | 0.5.3 | ≥ 560 |
| 25.01 | 12.8 | 0.6.3 | ≥ 570 |
| **26.01** | **13.1** | **0.13.0** | **≥ 590** |

Currently used: `nvcr.io/nvidia/tritonserver:26.01-vllm-python-py3`

> **Note:** NVIDIA's release notes state ≥ 580 for 26.01, but Forward Compatibility mode fails
> in practice when vLLM initializes CUDA. Driver ≥ 590 is required.

## Repository Structure

```
soofi-inference-server/
├── ansible/
│   ├── site.yaml                      # Orchestrator — imports all playbooks
│   ├── ansible.cfg
│   ├── requirements.yaml              # Galaxy collections (community.docker, community.general)
│   ├── templates/
│   │   ├── triton.env.j2              # .env template for the server
│   │   ├── config.pbtxt.j2            # Triton model config
│   │   └── model.json.j2              # vLLM engine config
│   ├── playbooks/
│   │   ├── os_setup.yaml              # Base packages, UFW, system limits, swap
│   │   ├── nvidia_setup.yaml          # Driver 590-server, Container Toolkit
│   │   ├── docker_setup.yaml          # Docker Engine, NVIDIA runtime
│   │   ├── triton_deploy.yaml         # Model download, Compose stack, health check
│   │   └── verify.yaml                # Sanity checks
│   └── inventory/
│       ├── hosts.yaml                 # GPU server inventory [gpu_nodes]
│       └── group_vars/gpu_nodes/
│           ├── vars.yaml              # Model, GPU settings, ports (committed)
│           └── vault.yaml             # Secrets (AES256-encrypted, never commit plaintext)
├── docker/
│   ├── Dockerfile.ansible
│   ├── ansible-run.sh                 # Wrapper: SSH agent, HOME=/tmp fix for Linux
│   ├── docker-compose.ansible.yml     # Ansible runner service
│   ├── docker-compose.yml             # Triton stack
│   ├── triton-start.sh                # Starts Triton with OpenAI frontend
│   ├── litellm-config.yaml            # (removed in T-06-7)
│   └── .env                           # Non-secret defaults (committed)
├── docs/
│   ├── 01-os-setup.md
│   ├── 02-nvidia-setup.md
│   └── 03-docker-deployment.md
├── models/
│   └── model_repository/              # Triton model configs (no weights)
└── scripts/
    ├── deploy.sh                      # Ansible deployment entrypoint
    ├── edit-vault.sh                  # Edit Ansible Vault secrets
    └── remove-model.sh                # Interactive model removal (config + HF cache)
```

---

## Ansible Deployment

### Prerequisites

- **Docker** installed locally
- **VPN** active if outside the DFKI network
- **SSH access** to the GPU server — your public key must be in `~/.ssh/authorized_keys` on the server

**Linux / WSL** — SSH keys are often missing for the root user:
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# WSL only: copy keys from Windows
cp /mnt/c/Users/<name>/.ssh/id_ed25519* ~/.ssh/
chmod 600 ~/.ssh/id_ed25519
```

### Configuration

All deployment settings live in two files under `ansible/inventory/group_vars/gpu_nodes/`:

**`vars.yaml`** — committed, no secrets:
```yaml
# Models to deploy — the only place to configure models
models:
  - hf_name: "Qwen/Qwen2.5-72B-Instruct"
    triton_name: "qwen2.5-72b"
    # quantization: "awq"   # uncomment for AWQ models

# GPU defaults (can be overridden per model)
tensor_parallel_size: 1
pipeline_parallel_size: 2
gpu_memory_utilization: "0.90"
```

**`vault.yaml`** — AES256-encrypted, never commit in plaintext:
```
hf_token: "hf_..."               # HuggingFace API token (must start with hf_)
litellm_master_key: "sk-..."     # removed in T-06-7
ansible_become_password: "..."   # sudo password for the mrk user
```

### Running the Deployment

`deploy.sh` is the single entrypoint. It starts the Ansible container automatically and runs the playbook:

```bash
# Full provisioning run
./scripts/deploy.sh

# Dry-run (no changes applied)
./scripts/deploy.sh --check

# Target a specific host
./scripts/deploy.sh --limit gpu-server-01

# Rebuild the Ansible image (required after changes to requirements.yaml or ansible-run.sh)
./scripts/deploy.sh --build
```

The script prompts for the Vault password at startup (same as the `mrk` sudo password).

### Vault — First-Time Setup

`edit-vault.sh` is the single entrypoint for vault operations — it starts the Ansible container automatically, just like `deploy.sh`:

```bash
# First time: fill vault.yaml with real values (plaintext), then encrypt it
./scripts/edit-vault.sh --encrypt

# Edit vault secrets later (opens $EDITOR inside the container)
./scripts/edit-vault.sh
```

### HuggingFace Token

The `hf_token` in the vault is a real HuggingFace API token:
- Create at huggingface.co → Settings → Access Tokens → **Fine-grained**, Read-only
- Use a token from an **org account** for server deployments, not a personal token
- Public models (Qwen2.5, Mistral) work without a token — but rate-limiting applies
- If the token does not start with `hf_`, Ansible falls back to anonymous download silently

### Playbooks

| Playbook | What it does |
|----------|-------------|
| `os_setup.yaml` | Base packages, NTP, UFW (ports 22/8000-8002/9000), system limits, swap off |
| `nvidia_setup.yaml` | Driver 590-server (from CUDA repo), Container Toolkit, nvidia-smi verify |
| `docker_setup.yaml` | Docker Engine, NVIDIA runtime as default, mrk added to docker group |
| `triton_deploy.yaml` | Deploy configs, pre-download model weights, start stack, health check |
| `verify.yaml` | Docker version, GPU access check |

### Changing the Model

Edit only `vars.yaml` — `config.pbtxt`, `model.json`, and `.env` on the server are
regenerated on the next deploy:

```yaml
# Single model
models:
  - hf_name: "mistralai/Mistral-7B-Instruct-v0.3"
    triton_name: "mistral-7b"

# Multiple models (VRAM must fit)
models:
  - hf_name: "Qwen/Qwen2.5-72B-Instruct"
    triton_name: "qwen2.5-72b"
  - hf_name: "TechxGenus/Mistral-7B-Instruct-v0.3-AWQ"
    triton_name: "mistral-7b-awq"
    gpu_memory_utilization: "0.45"
    quantization: "awq"
```

### Removing a Model

`triton_name` and `hf_name` come from `ansible/inventory/group_vars/gpu_nodes/vars.yaml`:

```yaml
models:
  - hf_name: "Qwen/Qwen2.5-72B-Instruct"   # ← hf_name
    triton_name: "qwen2.5-72b"               # ← triton_name
```

```bash
# Interactive removal — shows disk usage and asks for confirmation at each step
./scripts/remove-model.sh qwen2.5-72b Qwen/Qwen2.5-72B-Instruct
```

The script handles two steps separately:
1. **Config directory** (`model_repository/qwen2.5-72b/`) — small, re-created by Ansible on next deploy
2. **HF cache** (~150 GB) — requires explicit confirmation; deleting means a full re-download

> **Note:** Large model downloads (~150 GB for Qwen 72B) saturate the lab network.
> Schedule downloads outside peak hours and inform colleagues beforehand.

After removal, delete the entry from `vars.yaml` to prevent Ansible from re-downloading on the next deploy.

---

## API Endpoints

```bash
# Health
curl http://gpu-server:8000/v2/health/ready

# List models (OpenAI format)
curl http://gpu-server:9000/v1/models

# Chat completion
curl http://gpu-server:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen2.5-72b", "messages": [{"role": "user", "content": "Hello"}]}'
```

Soofi Trainer integration (in `soofi-trainer/.env`):
```bash
OPENAI_API_BASE=http://gpu-server:9000/v1
CHAT_MODEL=qwen2.5-72b
```
