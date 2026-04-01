# Soofi Inference Server

Self-hosted AI inference server running vLLM on H200 hardware.
Provisioned via Ansible, operated via Docker Compose.

## Architecture

```
Clients / Soofi Trainer
        │
        ▼
┌───────────────────────────┐
│       LiteLLM Proxy        │
│    Port 4000 — OpenAI API  │  ← /v1/chat/completions
└────────────┬──────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ vllm-model-A │  │ vllm-model-B │  (one container per model)
│  Port 8000   │  │  Port 8000   │
│  vLLM OpenAI │  │  vLLM OpenAI │
└──────┬───────┘  └──────┬───────┘
       │                 │
  ┌────┴────┐       ┌────┴────┐
  ▼         ▼       ▼         ▼
H200 #0   H200 #1  H200 #0  H200 #1
(141 GB)  (141 GB)
```

LiteLLM is the single external endpoint (port 4000). Each model gets its own
`vllm/vllm-openai` container reachable only within the Docker network.
Open WebUI is included for browser-based chat.

## Quickstart (local Docker Compose)

```bash
# 1. Create secrets file once (outside the repo)
echo "HF_TOKEN=hf_your_token_here" > ~/.env.secrets

# 2. Start the stack (docker/.env is committed with sensible defaults)
docker compose -f docker/docker-compose.yml up -d

# 3. Verify
curl http://localhost:4000/health/liveliness          # LiteLLM health
curl http://localhost:4000/v1/models                  # List models
```

## Hardware

| Component | Spec |
|-----------|------|
| GPU | 2x NVIDIA H200 NVL (141 GB HBM3e, 282 GB total) |
| GPU Interconnect | PCIe 5.0 (no NVLink → Tensor Parallel across both GPUs) |
| CPU | 2x AMD EPYC GENOA 9124 (32 cores / 64 threads) |
| RAM | 256 GB |
| Storage | 3.84 TB SSD |

## Repository Structure

```
soofi-inference-server/
├── ansible/
│   ├── site.yaml                      # Orchestrator — imports all playbooks
│   ├── ansible.cfg
│   ├── requirements.yaml              # Galaxy collections (community.docker, community.general)
│   ├── templates/
│   │   ├── docker-compose.vllm.yml.j2 # Docker Compose template (generated from models list)
│   │   └── litellm-config.vllm.yaml.j2# LiteLLM config template (generated from models list)
│   ├── playbooks/
│   │   ├── os_setup.yaml              # Base packages, UFW, system limits, swap
│   │   ├── nvidia_setup.yaml          # Driver 590-server, Container Toolkit
│   │   ├── docker_setup.yaml          # Docker Engine, NVIDIA runtime
│   │   ├── vllm_deploy.yaml           # Dirs, configs, model download, stack start, health check
│   │   └── verify.yaml                # Sanity checks
│   └── inventory/
│       ├── hosts.yaml                 # GPU server inventory [gpu_nodes]
│       └── group_vars/gpu_nodes/
│           ├── vars.yaml              # Model specs, ports (committed)
│           └── vault.yaml             # Secrets (AES256-encrypted, never commit plaintext)
├── docker/
│   ├── Dockerfile.ansible
│   ├── ansible-run.sh                 # Wrapper: SSH agent, HOME=/tmp fix for Linux
│   ├── docker-compose.ansible.yml     # Ansible runner service
│   ├── docker-compose.yml             # vLLM + LiteLLM + Open WebUI (local dev)
│   ├── litellm-config.yaml            # LiteLLM routing config (local dev)
│   └── .env                           # Non-secret defaults (committed)
├── docs/
│   ├── 01-os-setup.md
│   ├── 02-nvidia-setup.md
│   └── 03-docker-deployment.md
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

Day-to-day deployment inputs live in two files under `ansible/inventory/group_vars/gpu_nodes/`:

**`vars.yaml`** — committed, no secrets. For the `stack` and `vllm` backends, this is the file you edit to add, switch, or remove models and tune serving parameters. Shared serving defaults live under `vllm_defaults.config`, per-model overrides under `models[*].vllm`, parser-related flags under `parser_profiles`, and one-off vLLM CLI flags under `models[*].extra_args`:
```yaml
vllm_defaults:
  repository: "vllm/vllm-openai"
  tag: "v0.17.1"
  config:
    gpu_memory_utilization: 0.92
    max_model_len: 32768
    dtype: "auto"
    enable_prefix_caching: true
    enable_chunked_prefill: true

parser_profiles:
  qwen3:
    enable_auto_tool_choice: true
    tool_call_parser: "qwen3_coder"
    reasoning_parser: "qwen3"

# Models — each entry gets its own container
models:
  - name: "qwen35-122b-fp8"
    enabled: true
    hf_name: "Qwen/Qwen3.5-122B-A10B-FP8"
    gpu_ids: ["1"]
    parser_profile: "qwen3"
    vllm:
      gpu_memory_utilization: 0.9
      trust_remote_code: true
      max_num_seqs: 4
      kv_cache_dtype: "fp8"
    extra_args:
      - "--seed"
      - "3407"
```

Use `enabled: false` to keep a model in the catalog without deploying it.
Use `vllm:` with snake_case keys. Older `vllmConfig` entries are legacy and are ignored by the current `stack`/`vllm` templates.

**`vault.yaml`** — AES256-encrypted, never commit in plaintext:
```
hf_token: "hf_..."               # HuggingFace API token (must start with hf_)
ansible_become_password: "..."   # sudo password for the mrk user
```

### Running the Deployment

`deploy.sh` is the single entrypoint. It starts the Ansible container automatically and runs `site.yaml`. By default this uses the `stack` backend.

```bash
# Full deployment (default: stack backend)
./scripts/deploy.sh

# Dry-run (no changes applied)
./scripts/deploy.sh --check

# Target a specific host
./scripts/deploy.sh --limit gpu-server-01

# Rebuild the Ansible image (required after changes to requirements.yaml or ansible-run.sh)
./scripts/deploy.sh --build

# vLLM-only deployment
./scripts/deploy.sh -e inference_backend=vllm
```

The script prompts for the Vault password at startup (same as the `mrk` sudo password).

**Monitoring model downloads** — large models (30–130 GB) take time. While `deploy.sh` runs, open a second terminal to watch the progress:

```bash
ssh mrk@10.2.10.33 "docker logs -f \$(docker ps -lq)"
```

### Vault — First-Time Setup

Recommended workflow for a fresh server:

1. Edit `ansible/inventory/group_vars/gpu_nodes/vault.yaml` directly and fill in real values (plaintext at this point)
2. Build the Ansible image and run a full deployment: `./scripts/deploy.sh --build`
3. Once the deployment succeeds, encrypt the vault: `./scripts/edit-vault.sh --encrypt`
4. Re-deploy to confirm everything works with the encrypted vault: `./scripts/deploy.sh`

`edit-vault.sh` is the single entrypoint for vault operations — it starts the Ansible container automatically, just like `deploy.sh`:

```bash
# First time: encrypt vault.yaml after filling with real values
./scripts/edit-vault.sh --encrypt

# Edit vault secrets later (opens $EDITOR inside the container)
./scripts/edit-vault.sh
```

### HuggingFace Token

The `hf_token` in the vault is a real HuggingFace API token:
- Create at huggingface.co → Settings → Access Tokens → **Fine-grained**, Read-only
- Use a token from an **org account** for server deployments, not a personal token
- Public models (Qwen, Mistral) work without a token — but rate-limiting applies
- If the token does not start with `hf_`, Ansible falls back to anonymous download silently

### Playbooks

| Playbook | What it does |
|----------|-------------|
| `os_setup.yaml` | Base packages, NTP, UFW (ports 22/4000/3000), system limits, swap off |
| `nvidia_setup.yaml` | Driver 590-server (from CUDA repo), Container Toolkit, nvidia-smi verify |
| `docker_setup.yaml` | Docker Engine, NVIDIA runtime as default, mrk added to docker group |
| `vllm_deploy.yaml` | Generate configs from templates, pre-download model weights, start stack, health check |
| `verify.yaml` | Docker version, GPU access check |

### Changing the Model

For the `stack` and `vllm` backends, `vars.yaml` drives the generated `docker-compose.yml` and `litellm-config.yaml` on the server, and those files are regenerated on every deploy. The supported serving-parameter schema comes from the active Ansible templates: shared defaults come from `vllm_defaults.config`, per-model overrides from `models[*].vllm`, parser flags from `parser_profiles`, and any non-templated vLLM flags should go in `extra_args`. To add, switch, or remove a model: edit `vars.yaml`, run `./scripts/deploy.sh`.

```yaml
# Switch models by flipping enabled
models:
  - name: "qwen35-122b-fp8"
    enabled: true
    hf_name: "Qwen/Qwen3.5-122B-A10B-FP8"
    gpu_ids: ["1"]
    parser_profile: "qwen3"
    vllm:
      max_num_seqs: 4
      # ...

  - name: "MiniMax-M2.5"
    enabled: false
    hf_name: "MiniMaxAI/MiniMax-M2.5"
    gpu_ids: ["0", "1"]
    parser_profile: "minimax_m2"
    vllm:
      tensor_parallel_size: 2
      # ...
```

```yaml
# Two models in parallel (VRAM must fit)
models:
  - name: "qwen35-122b-fp8"
    enabled: true
    gpu_ids: ["1"]
    # ...

  - name: "NVIDIA-Nemotron-3-Super-120B-A12B-FP8"
    enabled: true
    gpu_ids: ["0"]
    # ...
```

Disabled or removed models have their containers stopped automatically on the next deploy (`--remove-orphans`). The HF cache stays on disk until you run `./scripts/remove-model.sh`.

### Removing a Model

```bash
# Interactive removal — shows disk usage and asks for confirmation at each step
./scripts/remove-model.sh <name> <hf_name>
# e.g.
./scripts/remove-model.sh qwen35-122b-fp8 Qwen/Qwen3.5-122B-A10B-FP8
```

After removal, delete the entry from `vars.yaml` to prevent Ansible from re-downloading on the next deploy.

> **Note:** Large model downloads (~150 GB for 122B) saturate the lab network.
> Schedule downloads outside peak hours and inform colleagues beforehand.

---

## API Endpoints

LiteLLM runs without auth — no API key required.

```bash
# Health
curl http://gpu-server:4000/health/liveliness

# List models
curl http://gpu-server:4000/v1/models

# Chat completion
curl http://gpu-server:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen35-35b-fp8", "messages": [{"role": "user", "content": "Hello"}]}'

```

Soofi Trainer integration (in `soofi-trainer/.env`):
```bash
OPENAI_API_BASE=http://gpu-server:4000/v1
OPENAI_API_KEY=dummy
CHAT_MODEL=qwen35-35b-fp8
```


## BIOS Configuration (H200 / Hopper)

The H200 GPUs require specific BIOS settings. Without these, the GPUs fail with `BAR0 is 0M` because the BIOS cannot assign address space for 2x 141 GB VRAM.

| Setting | Path | Value | Why |
|---------|------|-------|-----|
| 1TB Remap | Advanced > AMD CBS > DF Common Options | Attempt to remap | Shifts address space high enough for 282 GB VRAM + system RAM |
| IOMMU | Advanced > AMD CBS > NBIO Common Options | Enabled | Kernel needs this to manage memory above 4 GB |
| PCIe ARI Support | Advanced > AMD CBS > NBIO Common Options | Enabled | Required for multi-function GPU devices |
| PCIe Ten Bit Tag | Advanced > AMD CBS > NBIO Common Options | Enabled | Performance optimization for Hopper GPUs |
| PCIe SR-IOV | Advanced | Enabled | Enables 64-bit PCIe addressing |

## NVIDIA Fabric Manager

Required on H200 (Hopper architecture) even without NVLink:

- **HBM3e initialization** — the 141 GB HBM3e memory must be trained at boot; without Fabric Manager it stays in safe mode
- **GSP firmware** — loads firmware for the GPU System Processor that handles memory management
- **P2P addressing** — creates address maps so both GPUs are visible as compute resources

Configured in standalone mode (`FabricManagementMode=0`) for PCIe-only setups (no NVSwitch).

## GPU Strategy

GPU assignment is controlled per model via `gpu_ids` in `vars.yaml`:

| Configuration | `gpu_ids` | `vllm.tensor_parallel_size` | Use case |
|---------------|-----------|-----------------------------|----------|
| Both GPUs | `["0", "1"]` | `2` | 35B–122B models |
| GPU 0 only | `["0"]` | `1` | smaller models / second model in parallel |
| GPU 1 only | `["1"]` | `1` | smaller models / second model in parallel |

To switch models, set the old entry to `enabled: false`, set the new one to `enabled: true`, adjust `gpu_ids` and `vllm.tensor_parallel_size` if needed, then run `./scripts/deploy.sh`.

## Driver Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Driver | `590-server-open` | Open kernel modules optimized for H200 GSP |
| Compute lib | `libnvidia-compute-590-server` | Avoids version conflicts with Fabric Manager |
| Fabric Manager | `nvidia-fabricmanager-590` | Required for HBM3e init on Hopper |
