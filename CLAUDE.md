# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Infrastructure-as-code for a self-hosted AI inference server: a 2x NVIDIA H200 NVL machine (`gpu-server-01`, 10.2.10.33, user `mrk`) serving LLMs via vLLM, fronted by LiteLLM (OpenAI-compatible API, port 4000, no auth) and Open WebUI (port 3000). Provisioned with Ansible, operated with Docker Compose. There is no application code, build step, or test suite — `./scripts/deploy.sh --check` (Ansible dry-run) is the closest thing to a test.

## Commands

```bash
./scripts/deploy.sh                    # Full deployment (default backend: stack)
./scripts/deploy.sh --check            # Dry-run
./scripts/deploy.sh --limit gpu-server-01
./scripts/deploy.sh --build            # Rebuild Ansible runner image (after requirements.yaml / ansible-run.sh changes)
./scripts/deploy.sh -e key=value       # Override inventory vars at deploy time

./scripts/edit-vault.sh                # Edit encrypted secrets ($EDITOR in container)
./scripts/edit-vault.sh --encrypt      # First-time encryption of plaintext vault.yaml
./scripts/remove-model.sh <name> <hf_name>   # Interactive removal incl. HF cache

# Health / verification (LiteLLM runs without auth)
curl http://10.2.10.33:4000/health/liveliness
curl http://10.2.10.33:4000/v1/models

# Watch model downloads / first-start compile during a deploy (separate terminal)
ssh mrk@10.2.10.33 "docker logs -f \$(docker ps -lq)"
```

`deploy.sh` runs Ansible inside a Docker container (`docker/Dockerfile.ansible` + `docker/ansible-run.sh`, which works around SSH key permission issues on WSL/Linux mounts). It prompts for the Vault password — same as the `mrk` sudo password. SSH access to the server and VPN (outside DFKI network) are prerequisites, so a real deploy can only be run by the operator, not by Claude.

## Architecture: vars.yaml → templates → generated stack

The single source of truth for the deployed stack is `ansible/inventory/group_vars/gpu_nodes/vars.yaml`. On every deploy, `ansible/playbooks/stack_deploy.yaml` renders two templates from it and writes them to `/opt/soofi/docker/` on the server:

- `ansible/templates/docker-compose.stack.yml.j2` → `docker-compose.yml` — **one vLLM container per enabled model** (`vllm-<name>`), plus the service containers, LiteLLM, and Open WebUI
- `ansible/templates/litellm-config.stack.yaml.j2` → `litellm-config.yaml` — routes each model name to its container

Never edit the generated files on the server; they are overwritten on each deploy. To add/switch/remove a model: edit `vars.yaml`, run `./scripts/deploy.sh`. Disabled entries' containers are removed via `--remove-orphans`; their HF cache stays until `remove-model.sh`.

`ansible/site.yaml` imports all playbooks; the deploy playbook is chosen by `inference_backend` (default `stack`). The Triton path (`triton_deploy.yaml`, `docker/Dockerfile.triton`, etc.) is **deprecated** — kept for reference only.

### vars.yaml model entry semantics (`models:` list)

- Per-model `vllm:` keys (snake_case) override `vllm_defaults.config`. Legacy `vllmConfig` keys are silently ignored.
- **The compose template whitelists vLLM flags.** A new `vllm:` key does nothing unless `docker-compose.stack.yml.j2` renders it — either add a template block or pass the flag via `extra_args` (raw CLI list).
- `parser_profile` selects tool-call/reasoning parser flags from `parser_profiles`. See `ansible/inventory/group_vars/gpu_nodes/PARSERS.md` — the wrong parser breaks multi-turn tool calls (turn 1 may work, turn 2 fails).
- `gpu_ids` pins the container to GPUs; `gpu_memory_utilization` is a fraction of that GPU, so co-located models/services on one GPU must keep their fractions summing below ~1.0. No NVLink (PCIe 5.0 only) — multi-GPU models use `tensor_parallel_size: 2`.
- `repository`/`tag` override the vLLM image per model. Models needing vLLM plugins (e.g. `nvidia/Cosmos3-Nano` needs `vllm-cosmos3`) reference a `custom_images` entry; those images are built **on the GPU host** from `docker/Dockerfile.*` during deploy, only when an enabled model/service references them.
- `host_port` exposes a model directly on the host (e.g. reranker on 8003); otherwise models are reachable only via LiteLLM inside the Docker network.
- HF-hosted weights are pre-downloaded into the shared HF cache (`/opt/soofi/models/hf_cache`) before containers start, so health checks aren't blocked by multi-hour downloads. Large downloads (~150 GB) saturate the lab network — schedule off-peak.

### Local models (`is_local: true`)

A model can serve weights already on the host instead of downloading from HF. Set `is_local: true`, make `hf_name` the **container path** (not an HF repo), and mount the host weights with `extraVolumes` (note: camelCase, read-only `:ro`). Any parser/plugin files (e.g. `reasoning_parser_plugin`) can live inside that mounted directory. Example: `soofi-nano-30b` mounts `/opt/soofi/models/local/.../iter_0000600` to `/models/soofi-nano-30b`.

### Service blocks (top-level, not in `models:`)

Non-vLLM services are defined as top-level keys in `vars.yaml`, siblings of `models:`: `stt_service` (speaches / faster-whisper), `falcon_perception_service`, `docling_service`. They use either `image:` (pulled) or `build_context:` (built on the host from a repo dir, e.g. `docling-service/`). Some register in LiteLLM (STT → `whisper-1`); others expose only a non-OpenAI HTTP API on a host port and are **not** in LiteLLM (Falcon-Perception 8004, Docling 8020). Toggle with `enabled:` / comment-out. First start of compile-heavy services (Falcon) can take ~15 min — hence their healthcheck `start_period` overrides and a persistent `/cache` volume.

### Secrets

`ansible/inventory/group_vars/gpu_nodes/vault.yaml` is AES256-encrypted (`hf_token`, `ansible_become_password`). Never commit it in plaintext. The `hf_token` must start with `hf_` — otherwise Ansible silently falls back to anonymous download.

### Gotcha: mounted configs and Compose

`docker compose up -d` does not detect changes to volume-mounted config files (e.g. `litellm-config.yaml`), only changes to service definitions. The playbook handles this with `register` + conditional `restart litellm`, and the compose template injects a `LITELLM_MODELS` env var so model-list changes force a container recreate. Keep this pattern when adding mounted configs.

## Other serving paths in this repo

- `docker/docker-compose.yml` + `docker/litellm-config.yaml` — standalone **local dev** Compose stack with its own committed serving flags; independent of `vars.yaml` and the Ansible flow. Secrets come from `~/.env.secrets` (HF_TOKEN).
- `docker/falcon-perception-docker/` — standalone Dockerfiles for the `tiiuae/Falcon-Perception` FastAPI server for local use (see its `README-docker.md`). The Ansible stack deploys this server too, via `falcon_perception_service` + `docker/Dockerfile.falcon-perception`.

## Working in this repo

- Commit only when explicitly asked, and stay on the current branch (no enforced branch-naming or MR convention). This is a GitLab repo (`mrk40.dfki.de`), not GitHub.
- Deploys are operator-run (VPN + SSH + vault password), so don't expect to run them or auto-validate against the server — edit the IaC and let the operator deploy.
