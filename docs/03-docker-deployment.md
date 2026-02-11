# Docker Deployment

Triton Inference Server mit vLLM Backend via Docker Compose.

## Voraussetzungen

- NVIDIA Driver und Container Toolkit installiert ([02-nvidia-setup.md](02-nvidia-setup.md))
- Docker mit GPU-Unterstützung verifiziert
- HuggingFace Token (optional für Qwen, erforderlich für gated Models)

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
curl http://localhost:8000/v2/models
```

## API Nutzung

### HTTP Endpoint

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

## Nächster Schritt

→ [04-kubernetes-setup.md](04-kubernetes-setup.md) - Kubernetes Migration
