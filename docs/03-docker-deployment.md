# Docker Deployment

Triton Inference Server mit vLLM Backend via Docker Compose.

## Voraussetzungen

- NVIDIA Driver und Container Toolkit installiert ([02-nvidia-setup.md](02-nvidia-setup.md))
- Docker mit GPU-Unterstützung verifiziert
- HuggingFace Token (optional für Qwen, erforderlich für gated Models)

### Treiber / CUDA / Triton Kompatibilität

Die Triton-Container-Images bündeln jeweils eine bestimmte CUDA-Version und erfordern einen Mindest-Treiber auf dem Host. **Bei WSL2 wird der Treiber vom Windows-Host bereitgestellt** und kann nicht aus WSL2 heraus aktualisiert werden.

| Triton Image | CUDA | vLLM | Min. Treiber (Linux) | Min. Treiber (WSL2/Windows) |
|-------------|------|------|---------------------|-----------------------------|
| 24.08 | 12.6.0 | 0.5.3 | ≥560.28 | ≥560.76 |
| 24.09–24.10 | 12.6.1–12.6.2 | 0.5.3 | ≥560.35 | ≥560.94 |
| 24.11–24.12 | 12.6.3 | 0.5.5 | ≥560.35 | ≥561.17 |
| 25.01 | 12.8.0 | 0.6.3 | ≥570.26 | ≥570.65 |
| 25.09 | 13.0.1 | 0.10.1 | ≥575 (≥580.65 empf.) | ≥575 |
| 25.10 | 13.0.2 | 0.10.2 | ≥575 (≥580.82 empf.) | ≥575 |
| 25.11 | 13.0.2 | 0.11.0 | ≥575 (≥580.95 empf.) | ≥575 |
| 25.12 | 13.1.0 | 0.11.1 | ≥575 (≥590.44 empf.) | ≥575 |
| **26.01** | **13.1.1** | **0.13.0** | **≥575 (≥590.48 empf.)** | **≥575** |

> **Wichtig:** Ab CUDA 13.x gibt es Forward-Compatibility-Probleme mit älteren Treiber-Branches (R418–R560). Für Triton ≥25.09 empfiehlt sich Treiber ≥575.
>
> Ab Triton 25.01 werden nur noch GPUs mit **Compute Capability ≥7.5** (Turing und neuer) unterstützt. Ältere GPUs (Pascal, Volta) benötigen Triton ≤24.12.

### vLLM v1 Engine (ab Triton 25.10)

Ab Triton 25.10 ist die **vLLM v1 Engine** Standard. Wichtige Änderungen:
- `disable_log_requests` wurde entfernt — **nicht** in `model.json` verwenden
- Python wurde von 3.10 auf 3.12 aktualisiert
- Neue CUDAGraph-Compilation beim ersten Start (wird danach gecacht)

## Konfiguration

### 1. Environment File

```bash
cd docker/
cp .env.example .env
vim .env
```

Wichtige Einstellungen:

```bash
# HuggingFace Token (optional für Qwen, erforderlich für gated Models)
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx

# GPU Settings
CUDA_VISIBLE_DEVICES=0       # Single GPU: 0 | Beide GPUs: 0,1

# vLLM Settings
GPU_MEMORY_UTILIZATION=0.90  # 90% GPU Memory
MAX_MODEL_LEN=16384          # Max Context Length (an VRAM anpassen!)
```

> **Hinweis:** `MAX_MODEL_LEN` muss kleiner sein als die Anzahl Tokens, die in den KV-Cache passen.
> Falls der Fehler `max seq len is larger than the maximum number of tokens that can be stored in KV cache`
> auftritt, `MAX_MODEL_LEN` reduzieren oder `GPU_MEMORY_UTILIZATION` erhöhen.

### 2. GPU Parallelismus

Für Multi-GPU Setups gibt es zwei Modi:

| Modus | Config | Empfohlen für |
|-------|--------|---------------|
| **Pipeline Parallel** | TP=1, PP=2 | PCIe ohne NVLink (H200 Cluster) |
| Tensor Parallel | TP=2, PP=1 | NVLink Verbindungen |

**Pipeline Parallel** ist besser für PCIe-Verbindungen, da weniger häufige GPU-Kommunikation nötig ist.

#### Automatische GPU-Erkennung

Das Script `scripts/detect-gpu.sh` erkennt automatisch GPU-Anzahl und Interconnect-Typ:

```bash
# GPU-Konfiguration anzeigen
bash scripts/detect-gpu.sh

# Beispiel-Ausgabe (2x H200 via PCIe):
# GPU_COUNT=2
# GPU_INTERCONNECT=pcie
# TENSOR_PARALLEL_SIZE=1
# PIPELINE_PARALLEL_SIZE=2
# CUDA_VISIBLE_DEVICES=0,1

# In anderen Scripts verwenden
source scripts/detect-gpu.sh
echo "TP=$TENSOR_PARALLEL_SIZE, PP=$PIPELINE_PARALLEL_SIZE"
```

Bestehende Env-Vars werden respektiert (kein Override):

```bash
# Manueller Override
TENSOR_PARALLEL_SIZE=2 source scripts/detect-gpu.sh
# -> TENSOR_PARALLEL_SIZE bleibt 2
```

### 3. Model Repository

Das Model Repository enthält die Triton-Konfiguration für jedes Modell:

```
models/model_repository/
└── mistral-7b-awq/
    ├── config.pbtxt    # Triton Konfiguration
    └── 1/
        └── model.json  # vLLM Engine Config (required!)
```

**Wichtig:** Das vLLM Backend benötigt `model.json` im Version-Ordner (`1/`).

Neues Modell hinzufügen:

```bash
# Interaktive Auswahl (GPU wird automatisch erkannt)
./scripts/download-model.sh

# Manueller Override (z.B. für Tests auf einer GPU)
TENSOR_PARALLEL_SIZE=1 PIPELINE_PARALLEL_SIZE=1 ./scripts/download-model.sh 3
```

## Deployment

### Stack starten

```bash
cd docker/
docker compose up -d
```

### Logs überwachen

```bash
# Alle Logs
docker compose logs -f

# Nur Triton
docker compose logs -f triton
```

Beim ersten Start:
1. Container wird heruntergeladen (~20 GB)
2. Model Weights werden von HuggingFace geladen (~140 GB für 70B)
3. Model wird auf beide GPUs verteilt
4. Server wird ready

### Status prüfen

```bash
# Container Status
docker compose ps

# GPU Nutzung
nvidia-smi

# Triton Health
curl http://localhost:8000/v2/health/ready

# Geladene Models
curl -X POST http://localhost:8000/v2/repository/index
```

## LiteLLM Konfiguration

LiteLLM stellt eine OpenAI-kompatible API bereit und leitet Anfragen an Triton weiter.

### api_base Format

LiteLLM benötigt den **vollständigen Pfad** zum Triton-Generate-Endpoint pro Modell:

```yaml
# litellm-config.yaml
model_list:
  - model_name: mistral-7b-awq
    litellm_params:
      model: triton/mistral-7b-awq
      api_base: http://triton:8000/v2/models/mistral-7b-awq/generate
```

> **Achtung:** Kürzere Formen wie `http://triton:8000` oder `http://triton:8000/triton/generate` funktionieren **nicht** und führen zu `Invalid Triton API base` bzw. `404 Not Found`.

### OpenAI-Aliases

Für Kompatibilität mit Tools, die feste Modellnamen erwarten:

```yaml
  - model_name: gpt-4
    litellm_params:
      model: triton/mistral-7b-awq
      api_base: http://triton:8000/v2/models/mistral-7b-awq/generate
```

## API Nutzung

### Via LiteLLM (empfohlen, OpenAI-kompatibel)

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{
    "model": "mistral-7b-awq",
    "messages": [{"role": "user", "content": "Was ist Machine Learning?"}],
    "max_tokens": 100
  }'
```

### Via Triton direkt (HTTP)

```bash
curl -X POST http://localhost:8000/v2/models/mistral-7b-awq/generate \
  -H "Content-Type: application/json" \
  -d '{
    "text_input": "What is machine learning?",
    "parameters": {
      "max_tokens": 100,
      "temperature": 0.7
    }
  }'
```

### Streaming

```bash
curl -X POST http://localhost:8000/v2/models/mistral-7b-awq/generate_stream \
  -H "Content-Type: application/json" \
  -d '{
    "text_input": "Explain quantum computing",
    "parameters": {
      "max_tokens": 200,
      "stream": true
    }
  }'
```

### gRPC (Port 8001)

Für höheren Throughput, siehe Triton Client Libraries:
```
https://github.com/triton-inference-server/client
```

## Monitoring

### Prometheus Metrics

Metrics Endpoint: `http://localhost:8002/metrics`

Wichtige Metriken:
- `nv_inference_request_success` - Erfolgreiche Anfragen
- `nv_inference_request_failure` - Fehlgeschlagene Anfragen
- `nv_inference_queue_duration_us` - Queue Latenz
- `nv_gpu_utilization` - GPU Auslastung

### GPU Monitoring

```bash
# Echtzeit GPU Stats
watch -n 1 nvidia-smi

# Detaillierte Stats
nvidia-smi dmon -s pucvmet
```

## Multi-Model Setup

Mehrere Modelle gleichzeitig (falls VRAM ausreicht):

```
models/model_repository/
├── mistral-7b-awq/
│   └── config.pbtxt
├── mixtral-8x7b/
│   └── config.pbtxt
└── embed-model/
    └── config.pbtxt
```

Jedes Modell benötigt eigene `config.pbtxt` mit angepassten Parametern.

### Modelle aktivieren/deaktivieren

Triton lädt **alle** Verzeichnisse im `model_repository`. Um ein Modell zu deaktivieren, muss es **aus dem Verzeichnis entfernt** werden:

```bash
# Modell deaktivieren (aus model_repository verschieben)
mv models/model_repository/nvidia-nemotron-3-nano-30b-a3b-nvfp4 \
   models/nvidia-nemotron-3-nano-30b-a3b-nvfp4.disabled

# Modell wieder aktivieren
mv models/nvidia-nemotron-3-nano-30b-a3b-nvfp4.disabled \
   models/model_repository/nvidia-nemotron-3-nano-30b-a3b-nvfp4
```

> **Achtung:** Unterstriche als Prefix (`_modelname/`) funktionieren **nicht** — Triton versucht trotzdem, den Ordner zu laden und crasht mit `"failed to load all models"`.

### Lokales Testen vs. Server-Deployment

| | Lokal (Laptop/WSL2) | Server (H200) |
|---|---|---|
| **GPU** | RTX A3000 12GB | 2x H200 141GB |
| **Modelle** | Nur Mistral 7B AWQ | Mistral + Nemotron 30B |
| **CUDA_VISIBLE_DEVICES** | `0` | `0,1` |
| **PIPELINE_PARALLEL_SIZE** | `1` | `2` |
| **.env anpassen** | Single-GPU Settings | Dual-GPU Settings |

Für lokales Testen: `.env` auf Single-GPU anpassen und große Modelle aus `model_repository` entfernen.

## Operationen

### Stack stoppen

```bash
docker compose down
```

### Model neu laden

```bash
# Triton Model Control API
curl -X POST http://localhost:8000/v2/repository/models/mistral-7b-awq/load
curl -X POST http://localhost:8000/v2/repository/models/mistral-7b-awq/unload
```

### Container Update

```bash
docker compose pull
docker compose up -d
```

### Model Weight Cache

Model Weights werden in einem Host-Verzeichnis gespeichert (Standard: `models/hf_cache/`).
Dies ermöglicht direkten Zugriff auf die Weights vom Host und vereinfacht Backups.

```bash
# Cache-Verzeichnis anpassen (in docker/.env)
HF_CACHE_DIR=../models/hf_cache

# Cache leeren
rm -rf models/hf_cache/*
```

## Troubleshooting

### KV-Cache / Max Sequence Length

Fehler: `max seq len (32768) is larger than the maximum number of tokens that can be stored in KV cache (18432)`

**Lösung:** `max_model_len` in `model.json` und `config.pbtxt` reduzieren:

```json
// model.json
{ "max_model_len": 16384 }
```

```protobuf
// config.pbtxt
{ key: "max_model_len"  value: { string_value: "16384" } }
```

Alternativ `gpu_memory_utilization` auf `0.95` erhöhen (weniger Spielraum für System-VRAM).

### Out of Memory

```bash
# GPU Memory prüfen
nvidia-smi

# In config.pbtxt: gpu_memory_utilization reduzieren
{
  key: "gpu_memory_utilization"
  value: { string_value: "0.80" }
}
```

### Treiber zu alt

Fehler: `driver too old (found version XXXXX)` oder Container startet nicht.

**Lösung:** NVIDIA-Treiber aktualisieren (bei WSL2: auf der **Windows-Seite**). Siehe Kompatibilitätstabelle oben.

```bash
# Treiber-Version prüfen
nvidia-smi --query-gpu=driver_version --format=csv,noheader
```

### "Invalid Triton API base" (LiteLLM)

LiteLLM benötigt den vollständigen Pfad zum Generate-Endpoint:

```yaml
# FALSCH:
api_base: http://triton:8000

# RICHTIG:
api_base: http://triton:8000/v2/models/mistral-7b-awq/generate
```

### "failed to load all models" (Restart-Schleife)

Triton versucht alle Verzeichnisse im `model_repository` zu laden. Deaktivierte Modelle müssen **komplett herausgenommen** werden (nicht nur umbenannt).

```bash
# Modell aus Repository entfernen
mv models/model_repository/<model-name> models/<model-name>.disabled
docker compose restart triton
```

### Model lädt nicht

```bash
# Logs prüfen
docker compose logs triton | grep -i error

# HuggingFace Token prüfen
docker compose exec triton env | grep HF_TOKEN
```

### Langsame Inference

```bash
# Tensor Parallelism prüfen (sollte 2 sein)
docker compose logs triton | grep "tensor_parallel"

# GPU Auslastung prüfen
nvidia-smi dmon
```

### WSL2-spezifische Hinweise

- `pin_memory=False` wird automatisch gesetzt (leichter Performance-Nachteil)
- Treiber-Update nur über Windows möglich (Host → WSL2)
- Erster Start dauert länger durch CUDAGraph-Compilation (wird gecacht)

## Nächster Schritt

→ [04-kubernetes-setup.md](04-kubernetes-setup.md) - Kubernetes Migration
