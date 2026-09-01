# Harden the inference stack against the qwen38 deploy failure

_Status: proposed, not yet implemented. Written 2026-08-18 after the 2026-08-17
`qwen38-27b-coding` deploy incident._

## Context

Deploying `qwen38-27b-coding` failed with `dependency failed to start: container
vllm-qwen38-27b-coding is unhealthy`. Root cause, confirmed on the server with py-spy:
an orphaned `hf download` container from an earlier aborted deploy stalled inside the
Xet transfer backend on one shard (`layers-28.safetensors`), holding a HuggingFace
cache lock. The new vLLM container blocked forever in `snapshot_download` waiting on
that lock, never reported healthy, and took LiteLLM — and therefore the entire
port-4000 API — down with it.

Five defects made this possible. Fixing them so the same class of failure degrades
gracefully instead of causing an outage.

## Decisions taken

- **Keep Xet** as the transfer backend, but via the correct env var. Stall risk stays,
  so orphan reaping + the completeness check carry the mitigation.
- **Fail the deploy** with a summary when a model container never becomes healthy —
  preserving the loud failure that `depends_on` used to provide.
- **Keep `vllm_defaults` `true`** for the prefill flags. An absent key still means "on";
  the fix is that `false` finally works.

---

## Fix 1 — LiteLLM must not gate on model health

**Problem:** `docker-compose.stack.yml.j2:320-332` gives LiteLLM
`condition: service_healthy` on every active model. One slow or hung model blackouts
the whole API. Observed: `litellm-proxy` stuck in `Created`, port 4000 dead, while
three other models had been healthy for 10 days. The template already applies the
opposite reasoning for Falcon-Perception (comment at lines 238-239) — it just was
never extended to vLLM models. LiteLLM resolves `api_base` lazily per request
(`litellm-config.stack.yaml.j2:10`), so it does not need upstreams at boot.

**Change A — `ansible/templates/docker-compose.stack.yml.j2`**

In the LiteLLM `depends_on` block, change `condition: service_healthy` →
`condition: service_started` for the model loop and for `stt_service` / `tts_service`.
Add a comment mirroring lines 238-239 explaining that model health is verified by the
playbook instead, so one slow model cannot black out the proxy.

Leave `open-webui`'s `depends_on: litellm: service_healthy` alone — LiteLLM's own
healthcheck is a liveness probe and comes up in seconds.

**Change B — `ansible/playbooks/stack_deploy.yaml`, section 8 (lines 363-379)**

Insert between "Wait for LiteLLM to be ready" and "Query deployed models via LiteLLM":

- A per-model gate looping `active_models`, running
  `docker inspect -f '{% raw %}{{ .State.Health.Status }}{% endraw %}' vllm-{{ item.name }}`
  with `until: ... == 'healthy'`, `retries: "{{ model_health_retries | default(60) }}"`,
  `delay: 30`, `changed_when: false`, `failed_when: false`.
  The `{% raw %}` wrapper is required — the Go template braces collide with Jinja.
- An `ansible.builtin.fail` guarded by
  `model_health.results | selectattr('stdout', 'ne', 'healthy') | map(attribute='item.name') | list`,
  whose message names the unhealthy containers and points at
  `docker logs vllm-<name>`.

Net effect: LiteLLM and every healthy model stay serving; the play exits non-zero
naming exactly what broke.

---

## Fix 2 — `enable_prefix_caching: false` is silently ignored

**Problem:** `docker-compose.stack.yml.j2:111-116` renders the flag only when truthy:

```jinja
{% if cfg.enable_prefix_caching | default(false) %}
      - "--enable-prefix-caching"
{% endif %}
```

A tri-state (true / false / unset) is collapsed to a boolean, so `false` emits nothing
and vLLM applies its own default. **Five entries in `vars.yaml` are affected** —
`qwen3-embedding-8b` (98-99), the three `soofi-s-*-preview` entries (315-316, 338-339,
361-362), and `qwen3-reranker-4b` (384-385), whose comment at 370-373 claims it
"Overrides the global vllm_defaults" when it does not. Two are currently enabled.

Both `--no-enable-prefix-caching` and `--no-enable-chunked-prefill` are valid — verified
against the running image with `vllm serve --help=all`.

**Change — `ansible/templates/docker-compose.stack.yml.j2:111-116`**

Render on `is defined` rather than truthiness, emitting the negative form when false:

```jinja
{% if cfg.enable_prefix_caching is defined %}
      - "{{ '--enable-prefix-caching' if cfg.enable_prefix_caching else '--no-enable-prefix-caching' }}"
{% endif %}
{% if cfg.enable_chunked_prefill is defined %}
      - "{{ '--enable-chunked-prefill' if cfg.enable_chunked_prefill else '--no-enable-chunked-prefill' }}"
{% endif %}
```

`vllm_defaults.config` (vars.yaml:23-27) keeps both `true`, so the key is always defined
and models that don't set it render exactly what they render today — no behaviour change
for the 8 such models.

**Change — `ansible/inventory/group_vars/gpu_nodes/vars.yaml:23-27`**

Add a comment on `vllm_defaults.config` stating that these values are merged into every
model (`combine(..., recursive=True)`, template line 64), so *deleting* a key from a
model entry falls back to the default — use an explicit `false` to turn a flag off.

---

## Fixes 3, 4, 5 — download hardening

These are one change set; #3 and #4 do not help without the completeness check, which is
the defect that made every re-run skip the download and hang.

### 5. Wrong / dead download env vars

`stack_deploy.yaml:155` sets `HF_HUB_ENABLE_HF_TRANSFER=1`. In `huggingface_hub` 1.27.0
(the version in the image) this is fully deprecated — `constants.py:307-313` only emits a
`FutureWarning` and the variable is otherwise unused. `hf_transfer` is not even installed
(`importlib.util.find_spec` → `False`); `hf_xet` is.

Replace it with `HF_XET_HIGH_PERFORMANCE=1` (the documented successor) and add
`HF_HUB_DOWNLOAD_TIMEOUT=60` / `HF_HUB_ETAG_TIMEOUT=30` — both default to 10s and govern
the non-Xet HTTP path, so they help on fallback and cost nothing.

### 4. Orphaned downloader containers

`docker run --rm` only fires on exit; the stalled container survived 4h+ fully detached
from the aborted Ansible run and nothing reaped it. Give the downloader a deterministic
name, `--name hf-download-{{ hf_name | replace('/', '-') }}`, and:

- **Before** the download loop, `docker rm -f` that exact name (`failed_when: false`) for
  every model that needs downloading.
- Wrap the download loop in a `block:` whose `always:` runs
  `docker ps -aq --filter 'name=^hf-download-' | xargs -r docker rm -f`. This is what
  catches an `async: 7200` timeout — today the task fails and the play aborts before any
  cleanup, which is precisely how the orphan survived.
- Apply the same naming to the Falcon-Perception download (lines 216-231), which has the
  identical anonymous-`--rm` pattern; the glob reap then covers it too.

### 3. Stale `.lock` files are never cleaned

The playbook scrubs `*.incomplete` twice (116-131, 170-185) but never touches `.locks/`.
Nine stale locks are present right now across `Qwen3.8-27B-FP8`,
`faster-whisper-large-v3` and `Kokoro-82M-v1.0-ONNX`. Two new tasks before the download:

- **Age-based sweep (unconditional):** `ansible.builtin.find` on
  `{{ deploy_dir }}/models/hf_cache/hub/.locks` with `patterns: '*.lock'`, `recurse: true`,
  `age: 1h`, then remove the hits. Safe because `WeakFileLock` continuously refreshes the
  lock's mtime while genuinely held — observed directly during the incident, where a
  4-hour-old lock still had a current mtime. Anything an hour cold has a dead owner.
  This also clears the nine existing leftovers.
- **Scoped purge:** for each model the completeness check flags as incomplete, remove
  `.locks/models--<repo>` entirely. Runs *after* the orphan reap, so the only possible
  holder is already gone, and it is limited to repos whose weights are broken anyway.

### Completeness check (root cause — in scope because 3/4/5 are inert without it)

`stack_deploy.yaml:133-142` treats "the `snapshots/` dir has ≥1 subdirectory" as
"download complete". 65 of 66 shards passes that test, so the download was skipped and
Compose started a container that could never load.

- **New file `ansible/files/hf_cache_check.py`** — `#!/usr/bin/env python3`, args
  `<hub_dir> <repo_id>`; exit 0 complete, exit 2 incomplete (printing what's missing).
  Logic: repo/snapshot dir must exist; if `model.safetensors.index.json` is present,
  every distinct shard in `weight_map` must exist *and* resolve (the snapshot holds
  symlinks into `blobs/`, so a dangling link is the real failure mode); otherwise require
  at least one `*.safetensors` and that every symlink in the snapshot resolves. Also fail
  on any leftover `*.incomplete`. This is the same check used to diagnose the incident.
- Run it via `ansible.builtin.script` (`failed_when: false`, `changed_when: false`) over
  `active_models`, skipping `is_local: true`, and drive the download `when` off its
  `rc != 0` instead of `item.matched == 0`. The downstream "Ensure HF cache is writable"
  guard (line 192) keys off the same result.

---

## Files touched

| File | Change |
|---|---|
| `ansible/templates/docker-compose.stack.yml.j2` | `service_started` for LiteLLM deps; tri-state prefill flags |
| `ansible/playbooks/stack_deploy.yaml` | completeness check, lock sweep, orphan reap in `block/always`, download env, per-model health gate + fail summary |
| `ansible/files/hf_cache_check.py` | **new** — cache completeness validator |
| `ansible/inventory/group_vars/gpu_nodes/vars.yaml` | comment documenting absent-vs-`false` on `vllm_defaults.config` |
| `CLAUDE.md` | note that absent ≠ off in model entries, and that LiteLLM no longer gates on model health |

## Verification

1. **Dry run:** `./scripts/deploy.sh --check` — must complete with no task errors.
2. **Validator, standalone** (safe, read-only):
   ```
   python3 hf_cache_check.py /opt/soofi/models/hf_cache/hub Qwen/Qwen3.8-27B-FP8   # expect rc 0
   ```
   Then `mv` one shard symlink aside, re-run (expect rc 2 naming that shard), and restore it.
3. **Confirm the negative flags exist on the default image** (the qwen38 branch build is
   already verified):
   ```
   docker run --rm --entrypoint vllm vllm/vllm-openai:v0.27.1 serve --help=all | grep no-enable-prefix-caching
   ```
4. **Real deploy:** `./scripts/deploy.sh`, then on the server inspect the generated
   `/opt/soofi/docker/docker-compose.yml`:
   - `vllm-qwen3-embedding-8b` and `vllm-qwen3-reranker-4b` carry
     `--no-enable-prefix-caching` / `--no-enable-chunked-prefill`
   - the `litellm` block shows `condition: service_started` throughout
5. **Fix 1 behaves:** during the deploy, while a model is still `health: starting`,
   `curl http://10.2.10.33:4000/health/liveliness` must return 200 — the old build
   returned nothing at this point.
6. **Cleanup landed:**
   ```
   find /opt/soofi/models/hf_cache/hub/.locks -name '*.lock' | wc -l   # expect 0
   docker ps -a --filter 'name=hf-download-'                           # expect empty
   ```
7. **End-to-end:** `curl :4000/v1/models` lists all enabled models, and a chat completion
   against `qwen38-27b-coding` returns content.

## Branching

Two branches. Fixes 3/4/5 are tightly interdependent and must ship together; Fixes 1
and 2 are independent of everything (they touch different regions of the same two
files, nothing more).

**Branch 1 — incident response: Fix 1 + Fixes 3/4/5.** Three commits, Fix 1 first
because it is the safety net: 3/4/5 reduce how often a download stalls, Fix 1 contains
the blast radius when one still does. One deploy, one verification pass.

**Branch 2 — Fix 2 alone.** Isolated not because it is entangled but because it is the
only change that alters the behaviour of currently-serving endpoints, and it is
unrelated to the qwen38 incident. It needs its own acceptance check (rerank scores and
embedding output, before vs after) and its own revert path — bundling it would mean a
rollback of the qwen38 fixes silently re-enables prefix caching, and vice versa.

Do not split 3/4/5: the completeness check is the only thing that triggers a
re-download, so reaping and lock-cleanup without it reproduce the incident exactly.

**Ordering note:** Fix 1's key verification needs a slow-starting model to observe.
The qwen38 GDN JIT compile still provides that window — test it on the next deploy,
before 3/4/5 remove the opportunity.

## Risks

- **Fix 2 changes live behaviour, not just the rendered command.** Verified on the
  running v0.27.1 containers (restarted 2026-08-18 07:07): neither `qwen3-embedding-8b`
  nor `qwen3-reranker-4b` lists a prefix-caching entry in `non-default args`, and both
  engine configs read `enable_prefix_caching=True, enable_chunked_prefill=True`. vLLM
  does **not** auto-disable these for pooling models — so today both endpoints run with
  caching on, precisely what vars.yaml:370-373 warns against. Applying the fix genuinely
  turns both flags off for the first time; rerank scores and embedding throughput may
  shift. Measure before and after.
- Compose **will recreate** `qwen3-embedding-8b` and `qwen3-reranker-4b` (changed
  command) and `litellm-proxy` (changed `depends_on`) — real, if short, downtime.
- Keeping Xet means an indefinite stall is still possible. It is now recoverable rather
  than permanent: the next deploy reaps the orphan, clears the lock, detects the partial
  cache, and retries — instead of skipping the download and hanging.
- `HF_XET_HIGH_PERFORMANCE=1` raises transfer concurrency and memory use; comfortable on
  a 251 GB host, worth knowing if downloads run alongside a heavy job.
