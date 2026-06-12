# Prompt: integrate Falcon-Perception into the Ansible stack

Integrate the `tiiuae/Falcon-Perception` FastAPI inference server into the Ansible-managed
stack on gpu-server-01, following two existing repo patterns: build it on the GPU host as a
custom image (like `soofi/vllm-openai-cosmos3`), and run it as a standalone service on a
dedicated host port (like `stt_service`). Work on the existing `feature/falcon-perception`
branch.

## Read first

- https://github.com/tiiuae/Falcon-Perception (README, "Launch server" section) — confirm
  current env vars and server flags before finalizing anything.
- `docker/falcon-perception-docker/` — Dockerfile, Dockerfile.remote, README-docker.md
- `ansible/inventory/group_vars/gpu_nodes/vars.yaml` — custom_images, stt_service, and the
  reranker's `host_port` pattern
- `ansible/templates/docker-compose.stack.yml.j2` — the `render_service` macro
- `ansible/playbooks/stack_deploy.yaml` — step 2b (custom image build flow)

## Dockerfile choice: use `Dockerfile.remote`

The playbook builds custom images with `docker build -f <dockerfile> -t <tag>
{{ deploy_dir }}/docker` — the build context on the server is just the docker dir, so the
local-clone `Dockerfile` (which does `COPY . .` from a Falcon-Perception checkout) cannot
work there. `Dockerfile.remote` clones the repo inside the build. Copy it to
`docker/Dockerfile.falcon-perception` at the repo root (the playbook copies Dockerfiles
from `/repo/docker/<name>`, non-recursive — follow the `Dockerfile.vllm-cosmos3` naming).
Pin `REPO_REF` to a specific upstream commit/tag, NOT `main`: the host build is
layer-cached, so a cached `git clone main` layer silently serves stale code. Upgrades
happen by bumping REPO_REF and the image tag together.

## Changes

1. **vars.yaml**
   - New `custom_images` entry: `repository: soofi/falcon-perception`, tag tied to the
     pinned ref, `dockerfile: Dockerfile.falcon-perception`.
   - New `falcon_perception_service` block modeled on `stt_service`: image
     `soofi/falcon-perception:<tag>`, `container_port: 7860`, host port via
     `internal_port` (suggest 8004 — verify it's free; 8003 = reranker, 8010 = STT),
     `healthcheck_path: "/v1/health"`, `gpu_devices: ["0"]` (vars.yaml notes GPU 1 is
     fully booked: qwen36-27b-multi 0.5 + nemotron-omni 0.5; GPU 0 has cosmos 0.5 +
     reranker 0.15). Environment: `HF_MODEL_ID=tiiuae/Falcon-Perception`,
     `DTYPE=bfloat16`, `NUM_GPUS=1`, `HF_TOKEN={{ hf_token }}`. Volumes:
     `{{ deploy_dir }}/models/hf_cache:/models/huggingface` (the image sets HF_HOME
     there) plus a persistent host dir for `/cache` (torchinductor/triton compile
     caches — saves minutes on every restart).
2. **stack_deploy.yaml** — the `active_custom_images` filter only selects images
   referenced by enabled *models'* `repository`; a standalone service never matches, so
   its image would silently never build. Extend the selection to also cover images
   referenced by service blocks, keeping the "build only when actually referenced"
   semantics.
3. **docker-compose.stack.yml.j2**
   - Render the new service via `render_service` (third conditional block, or generalize
     to a list — your call, match existing style). Two macro gaps to fix:
     (a) healthcheck `start_period: 120s` / 10 retries is too short — Falcon-Perception
     model load + torch compile can take ~15 min (see the upstream image's own
     HEALTHCHECK). Make start_period/retries per-service-overridable with the current
     values as defaults. `/v1/health` returns 200 while loading and the image has curl,
     so `curl -f` works. (b) add optional `shm_size` support (README recommends 16g).
   - Do NOT register it in LiteLLM and do NOT add a litellm `depends_on` for it: its API
     is `/v1/predictions`, not OpenAI-compatible, and a depends_on would block LiteLLM
     startup behind a long compile. It's reached directly via the host port, like the
     reranker. Omitting `litellm_name` keeps the LITELLM_MODELS recreate logic untouched.
4. **Weights pre-download (decide and state your choice)** — the playbook pre-downloads
   weights so health checks aren't blocked by downloads, but that loop is vLLM-specific.
   Either add a small task downloading `tiiuae/Falcon-Perception` into the shared HF
   cache, or rely on the extended healthcheck start_period for first boot.
5. Update `docker/falcon-perception-docker/README-docker.md` and the root `CLAUDE.md`
   line claiming falcon-perception is "Not part of the Ansible stack".

## Constraints

vars.yaml is the single source of truth — never edit generated files on the server.
Don't touch vault.yaml. Match existing template/playbook idiom.

## Verify

1. `./scripts/deploy.sh --check` — it prompts interactively for the Vault password; if
   you can't drive it, ask me to run `! ./scripts/deploy.sh --check`.
2. Full deploy: ask me to run `! ./scripts/deploy.sh`.
3. After deploy:
   - `curl http://10.2.10.33:<host_port>/v1/health` until status is `ready` (watch
     progress: `ssh mrk@10.2.10.33 "docker logs -f falcon-perception"`)
   - POST the zidane.jpg detection example from README-docker.md to `/v1/predictions`
   - `curl http://10.2.10.33:4000/v1/models` — confirm the existing stack is unaffected
   - `ssh mrk@10.2.10.33 nvidia-smi` — check GPU 0 VRAM headroom before enabling; if it
     can't fit alongside cosmos + reranker, report and propose a re-pin instead of
     deploying into an OOM.

Report what changed, the chosen port/GPU/REPO_REF/tag, and verification results.
