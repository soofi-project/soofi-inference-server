# Open WebUI Setup

Integration von Open WebUI mit Triton + vLLM via LiteLLM Proxy.

## Architektur

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Open WebUI    │────▶│    LiteLLM      │────▶│     Triton      │
│   (Port 3000)   │     │   (Port 4000)   │     │   (Port 8000)   │
│                 │     │                 │     │                 │
│  Chat Interface │     │  OpenAI API     │     │  vLLM Backend   │
│                 │     │  Compatibility  │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                                                ┌───────┴───────┐
                                                ▼               ▼
                                            H200 GPU 0     H200 GPU 1
```

**Komponenten:**
- **Open WebUI**: Web-basierte Chat-Oberfläche
- **LiteLLM**: Proxy für OpenAI API Kompatibilität
- **Triton + vLLM**: Inference Backend

## Docker Setup

### 1. Konfiguration

```bash
cd docker/
cp .env.example .env
vim .env
```

Wichtige Einstellungen:
```bash
# LiteLLM API Key (für Authentifizierung)
LITELLM_MASTER_KEY=sk-your-secret-key-here

# Open WebUI
WEBUI_PORT=3000
WEBUI_AUTH=true
WEBUI_NAME=AI Inference Server
```

### 2. LiteLLM Config anpassen

Model-Mapping in `docker/litellm-config.yaml`:

```yaml
model_list:
  # Hauptmodell
  - model_name: mistral-7b-awq
    litellm_params:
      model: triton/mistral-7b-awq
      api_base: http://triton:8000/v2/models/mistral-7b-awq/generate

  # Aliase für OpenAI-kompatible Clients
  - model_name: gpt-4
    litellm_params:
      model: triton/mistral-7b-awq
      api_base: http://triton:8000/v2/models/mistral-7b-awq/generate

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

> **Wichtig:** Die `api_base` muss die vollständige Triton URL mit Model-Pfad enthalten:
> `http://triton:8000/v2/models/<model_name>/generate`
>
> Der `master_key` wird über die Umgebungsvariable `LITELLM_MASTER_KEY` gesetzt (nicht hardcoden!).

### 3. Stack starten

```bash
docker compose up -d

# Status prüfen
docker compose ps

# Logs
docker compose logs -f open-webui
```

### 4. Zugriff

- **Open WebUI**: http://localhost:3000
- **LiteLLM API**: http://localhost:4000
- **Triton API**: http://localhost:8000

Beim ersten Zugriff auf Open WebUI:
1. Admin-Account erstellen
2. Einstellungen prüfen (Model sollte automatisch verfügbar sein)

## Kubernetes Setup

### 1. Secrets erstellen

```bash
# Vorlage kopieren
cp kubernetes/secrets.yaml.example kubernetes/secrets.yaml

# Werte anpassen (base64 encoded)
vim kubernetes/secrets.yaml

# Secrets anwenden
kubectl apply -f kubernetes/secrets.yaml
```

### 2. Deployment

```bash
# Alle Komponenten deployen
kubectl apply -f kubernetes/

# Status prüfen
kubectl get pods -n triton-inference

# Auf Ready warten
kubectl wait --for=condition=ready pod -l app=open-webui -n triton-inference --timeout=300s
```

### 3. Zugriff

```bash
# NodePort (Port 30080)
http://<node-ip>:30080

# Port-Forward für lokalen Zugriff
kubectl port-forward svc/open-webui 3000:80 -n triton-inference
```

## API Nutzung

### LiteLLM Endpoint (OpenAI-kompatibel)

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-secret-key-here" \
  -d '{
    "model": "mistral-7b-awq",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "max_tokens": 100
  }'
```

### Python Client

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:4000/v1",
    api_key="sk-your-secret-key-here"
)

response = client.chat.completions.create(
    model="mistral-7b-awq",
    messages=[
        {"role": "user", "content": "Explain quantum computing"}
    ]
)

print(response.choices[0].message.content)
```

## Mehrere Modelle

Für mehrere Modelle in `litellm-config.yaml`:

```yaml
model_list:
  - model_name: mistral-7b-awq
    litellm_params:
      model: triton/mistral-7b-awq
      api_base: http://triton:8000/v2/models/mistral-7b-awq/generate

  - model_name: qwen2.5-72b
    litellm_params:
      model: triton/qwen2.5-72b
      api_base: http://triton:8000/v2/models/qwen2.5-72b/generate
```

Jedes Modell benötigt die vollständige `api_base` URL mit dem jeweiligen Modellnamen.
Alle konfigurierten Modelle erscheinen automatisch in Open WebUI.

## Troubleshooting

### Open WebUI zeigt keine Modelle

```bash
# LiteLLM Liveness prüfen (kein Auth nötig)
curl http://localhost:4000/health/liveliness

# Verfügbare Modelle auflisten (Auth erforderlich)
curl http://localhost:4000/v1/models \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

> **Hinweis:** Das LiteLLM-Image enthält kein `curl`. Der Docker Health-Check verwendet
> daher Python: `python -c "import urllib.request; urllib.request.urlopen(...)"`

### LiteLLM kann Triton nicht erreichen

Fehler: `Invalid Triton API base: http://triton:8000`

**Ursache:** Die `api_base` in `litellm-config.yaml` muss den vollständigen Pfad enthalten:
```
# Falsch:
api_base: http://triton:8000

# Richtig:
api_base: http://triton:8000/v2/models/<model_name>/generate
```

```bash
# Docker: Netzwerk prüfen
docker network inspect inference-network

# Kubernetes: Service prüfen
kubectl get svc -n triton-inference
kubectl logs deployment/litellm -n triton-inference
```

### Authentifizierungsfehler

Open WebUI muss den gleichen API-Key wie LiteLLM verwenden. Die Env-Variablen sind **Plural**:

```yaml
# docker-compose.yml (Open WebUI)
environment:
  - OPENAI_API_BASE_URLS=http://litellm:4000/v1   # Plural!
  - OPENAI_API_KEYS=${LITELLM_MASTER_KEY}          # Plural!
```

```bash
# API Key prüfen
docker compose exec litellm env | grep LITELLM_MASTER_KEY

# Kubernetes
kubectl get secret litellm-secret -n triton-inference -o yaml
```

## Sicherheit

### Produktions-Empfehlungen

1. **HTTPS aktivieren** - Reverse Proxy (nginx, traefik) mit TLS
2. **Starke API Keys** - Mindestens 32 Zeichen, zufällig generiert
3. **Network Policies** - Kubernetes NetworkPolicies für Isolation
4. **Rate Limiting** - In LiteLLM oder Reverse Proxy konfigurieren

### API Key generieren

```bash
# Sicheren Key generieren
openssl rand -base64 32 | tr -d '/+=' | cut -c1-32
# Ausgabe z.B.: sk-AbCdEfGhIjKlMnOpQrStUvWxYz123456
```
