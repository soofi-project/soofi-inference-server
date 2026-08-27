# Plan: Self-hosted Krea 2 Turbo Style Reference

> Source requirements: [ComfyUI Krea 2 tutorial](https://docs.comfy.org/tutorials/image/krea/krea-2#krea-2-turbo-style-reference-workflow), the approved design interview, and the existing Krea Raw deployment in this repository.

## Architectural decisions

- **Service boundary**: Deploy a dedicated ComfyUI service on GPU 1 of `gpu-server-01`. Keep the existing Krea Raw vLLM-Omni service available but disabled by default.
- **Routes**: Serve the browser and native ComfyUI HTTP/WebSocket API at `http://gpu-server-01:8188` and `http://10.2.10.33:8188`. Do not register ComfyUI in LiteLLM.
- **Runtime**: Build `soofi/comfyui-krea2:v0.30.0-torch2.13.0-cu130` from pinned ComfyUI v0.30.0, Python 3.12, PyTorch 2.13/torchvision 0.28, TorchAudio 2.11, and CUDA 13.0. TorchAudio 2.11 uses the stable ABI for PyTorch 2.11 and newer; there is no TorchAudio 2.13 wheel on the CUDA 13.0 index. Use only ComfyUI core nodes.
- **Execution policy**: Run with `--multi-user --disable-api-nodes`, one shared GPU queue, and no cloud/partner API nodes.
- **Storage**: Persist inputs, outputs, profiles, and workflows under `/home/mrk/image-gen-data`. Store verified model weights under `/opt/soofi/models/comfyui` and mount them read-only at runtime.
- **Network policy**: Expose unauthenticated HTTP port 8188 to every host that can route to `gpu-server-01`. Document that it must never be forwarded to the public internet.
- **Testing**: Use the `tdd` skill and red-green-refactor in every implementation phase. A real 1K style-reference generation is mandatory after deployment.
- **Retention**: Retain uploaded and generated data indefinitely. Disabling or rolling back the service must not remove models or user data.

## Public interfaces and configuration

- Preserve native ComfyUI endpoints including `/system_stats`, `/upload/image`, `/prompt`, `/history/{prompt_id}`, `/view`, and WebSocket progress.
- Add an independent `comfyui_service` inventory block with:
  - `enabled: true`
  - container name `comfyui-krea2`
  - image `soofi/comfyui-krea2:v0.30.0-torch2.13.0-cu130`
  - host/container port `8188`
  - GPU device `1`
  - explicit data and model directories
- Keep `image_generation_service.enabled: false` for Krea Raw on port 8005. Concurrent Raw and ComfyUI operation is outside acceptance testing.

---

## Phase 1: GPU-backed ComfyUI foundation

**User stories**: A trusted researcher can open a shared ComfyUI server from any routable PC, maintain a separate profile, and use GPU-backed workflows without sending data to cloud nodes.

### What to build

Create a complete but model-independent ComfyUI path through the Ansible inventory, custom image build, generated Compose stack, GPU runtime, persistent storage, firewall, and health checks.

Start by writing failing rendering and deployment tests. Correct the current test that assumes Krea Raw is enabled, while retaining a test that explicitly enables and validates Raw as an optional service.

The ComfyUI service must:

- Reserve GPU 1, use `restart: unless-stopped`, `init`, and 16 GB shared memory.
- Run as the UID/GID resolved for `mrk` so persistent files remain owned by that account.
- Mount models read-only and input, output, and user directories read-write.
- Listen on `0.0.0.0:8188` with multi-user mode, disabled API nodes, explicit directories, and persistent SQLite state.
- Use fail-loud container and Ansible health checks against `/system_stats`.
- Remain independent from LiteLLM and the health/startup lifecycle of text models.
- Add or remove the unrestricted UFW rule according to `comfyui_service.enabled`.

### Acceptance criteria

- [ ] Tests fail before the ComfyUI service exists and pass after implementation.
- [ ] Rendered Compose selects GPU 1 and contains the required command, mounts, port, identity, and health check.
- [ ] Disabling ComfyUI removes its container and UFW rule without affecting Raw or the text-model stack.
- [ ] Explicitly enabling Raw still renders the existing vLLM-Omni service correctly.
- [ ] `/home/mrk/image-gen-data/{input,output,user}` is created without deleting existing content.
- [ ] A model-independent ComfyUI instance starts with CUDA visible and is reachable from another network PC.

---

## Phase 2: Krea Turbo style-reference generation

**User stories**: A researcher can select the official Krea 2 style-reference workflow, upload a reference image, enter a prompt, generate locally on GPU 1, and download the result.

### What to build

Add exact, resumable model provisioning with size and SHA-256 verification. Abort before container startup with the failing path and expected/actual checksum if any asset is incomplete or corrupt.

Download only this manifest from `Comfy-Org/Krea-2`:

| Destination | Size | SHA-256 |
|---|---:|---|
| `diffusion_models/krea2_turbo_int8_convrot.safetensors` | 13,492,686,496 | `8e4eeda70dd5037ab1ba2bef6b417f9f901e26093117cf397f741fc1fdaaf3f1` |
| `text_encoders/qwen3vl_4b_fp8_scaled.safetensors` | 5,242,467,968 | `54bd5144df0bbc25dd6ccadfcb826b521445a1b06ae5a42570bdd2974ca87094` |
| `vae/qwen_image_vae.safetensors` | 253,806,246 | `a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f` |
| `loras/krea2_style_reference.safetensors` | 457,111,760 | `f50df5a9e62e4be8aa926a63dd5bb1a64770c4004f763c1208007ae13daa82b8` |

Verify that the pinned ComfyUI workflow-template package exposes the official “Krea-2 Style Reference” workflow to every user profile.

Replace the Raw-oriented live test with a native ComfyUI E2E test that generates a deterministic reference PNG, uploads it, queues the official one-reference graph, monitors completion, downloads the output, and validates the complete PNG. The graph must use the INT8 Convrot model, style-reference LoRA, Qwen encoder, VAE, eight Turbo steps, and disabled prompt enhancement.

### Acceptance criteria

- [ ] Unit tests validate the exact four-file manifest, paths, sizes, and checksums.
- [ ] Downloads run only when ComfyUI is enabled, resume partial transfers, and reuse verified files.
- [ ] A missing or corrupt file stops deployment with an actionable error.
- [ ] “Krea-2 Style Reference” is available from the browser Template Library without custom nodes.
- [ ] The native API uploads a real reference image and returns a valid 1024×1024 PNG generated on GPU 1.
- [ ] The interactive workflow retains its supported 1K–2K resolution choices.

---

## Phase 3: Operational acceptance and handoff

**User stories**: An operator can deploy, validate, troubleshoot, switch between ComfyUI and Raw, and roll back without losing researcher data.

### What to build

Complete the deployment documentation and operational validation. Document browser and native API access, storage locations, GPU placement, model size, initial download behavior, logs, health checks, profiles, acceptable use, troubleshooting, switching, and rollback.

The Krea Community License must be linked and the trusted-researcher human-review process documented. State prominently that ComfyUI is unauthenticated and must not be exposed publicly.

### Acceptance criteria

- [ ] `pytest -q` passes with no unexpected skips or failures.
- [ ] The Ansible deployment dry-run succeeds.
- [ ] The operator performs a real deployment and runs the mandatory live Krea E2E test without skipping it.
- [ ] A second network PC can open the UI, create a named profile, run the workflow, and download its output.
- [ ] Recreating the container preserves profiles, uploads, and generated outputs under `/home/mrk/image-gen-data`.
- [ ] Rollback removes only the ComfyUI container and UFW rule; models and user data remain recoverable.
- [ ] Existing vLLM, LiteLLM, Falcon Perception, reranker, and speech services retain their current runtimes and behavior.

## Explicit exclusions

- Authentication or an HTTPS reverse proxy.
- Public-internet exposure.
- An OpenAI-compatible image adapter or LiteLLM registration.
- Enforced content-classifier nodes.
- Third-party ComfyUI custom nodes.
- Automated input/output retention cleanup.
- Mandatory concurrent validation of Krea Raw and ComfyUI.
