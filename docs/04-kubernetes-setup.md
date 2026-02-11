# Kubernetes Setup

Migration von Docker Compose zu Kubernetes für Production Workloads.

## Voraussetzungen

- Funktionierendes Docker Setup ([03-docker-deployment.md](03-docker-deployment.md))
- Kubernetes Cluster (k3s, kubeadm, oder managed)
- kubectl konfiguriert
- Helm 3.x installiert

## Cluster Setup (Single Node mit k3s)

Für einen einzelnen GPU-Server ist k3s eine leichtgewichtige Option:

```bash
# k3s installieren (ohne Traefik)
curl -sfL https://get.k3s.io | sh -s - --disable traefik

# kubectl konfigurieren
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config

# Verifizieren
kubectl get nodes
```

## NVIDIA GPU Operator

Der GPU Operator automatisiert die GPU-Konfiguration in Kubernetes:

```bash
# Helm Repo hinzufügen
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update

# GPU Operator installieren
helm install gpu-operator nvidia/gpu-operator \
  --namespace gpu-operator \
  --create-namespace \
  --set driver.enabled=false \
  --set toolkit.enabled=true

# Status prüfen
kubectl get pods -n gpu-operator
```

> **Hinweis**: `driver.enabled=false` weil der Host-Driver bereits installiert ist.

## Kubernetes Manifests

### Namespace

```bash
kubectl apply -f kubernetes/namespace.yaml
```

```yaml
# kubernetes/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: triton-inference
```

### Secret für HuggingFace Token

```bash
kubectl create secret generic hf-secret \
  --namespace triton-inference \
  --from-literal=HF_TOKEN=hf_xxxxxxxxxxxx
```

### Model Storage (PersistentVolumeClaim)

```yaml
# kubernetes/model-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: model-cache
  namespace: triton-inference
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 500Gi
  storageClassName: local-path  # k3s default
```

### Triton Deployment

```yaml
# kubernetes/triton-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: triton-vllm
  namespace: triton-inference
spec:
  replicas: 1
  selector:
    matchLabels:
      app: triton-vllm
  template:
    metadata:
      labels:
        app: triton-vllm
    spec:
      containers:
        - name: triton
          image: nvcr.io/nvidia/tritonserver:24.08-vllm-python-py3
          ports:
            - containerPort: 8000
              name: http
            - containerPort: 8001
              name: grpc
            - containerPort: 8002
              name: metrics
          env:
            - name: HF_TOKEN
              valueFrom:
                secretKeyRef:
                  name: hf-secret
                  key: HF_TOKEN
          command:
            - tritonserver
            - --model-repository=/models
            - --log-verbose=1
          volumeMounts:
            - name: model-repository
              mountPath: /models
            - name: model-cache
              mountPath: /root/.cache/huggingface
            - name: shm
              mountPath: /dev/shm
          resources:
            limits:
              nvidia.com/gpu: "2"  # Beide H200 GPUs
              memory: "200Gi"
            requests:
              nvidia.com/gpu: "2"
              memory: "100Gi"
          readinessProbe:
            httpGet:
              path: /v2/health/ready
              port: 8000
            initialDelaySeconds: 120
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /v2/health/live
              port: 8000
            initialDelaySeconds: 120
            periodSeconds: 30
      volumes:
        - name: model-repository
          configMap:
            name: model-config
        - name: model-cache
          persistentVolumeClaim:
            claimName: model-cache
        - name: shm
          emptyDir:
            medium: Memory
            sizeLimit: 16Gi
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

### Service

```yaml
# kubernetes/triton-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: triton-inference
  namespace: triton-inference
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 8000
      targetPort: 8000
    - name: grpc
      port: 8001
      targetPort: 8001
    - name: metrics
      port: 8002
      targetPort: 8002
  selector:
    app: triton-vllm
```

### NodePort Service (externer Zugriff)

```yaml
# kubernetes/triton-nodeport.yaml
apiVersion: v1
kind: Service
metadata:
  name: triton-external
  namespace: triton-inference
spec:
  type: NodePort
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      nodePort: 30800
    - name: grpc
      port: 8001
      targetPort: 8001
      nodePort: 30801
  selector:
    app: triton-vllm
```

## Deployment

```bash
# Alle Manifests anwenden
kubectl apply -f kubernetes/

# Status prüfen
kubectl get all -n triton-inference

# Pod Logs
kubectl logs -f deployment/triton-vllm -n triton-inference

# GPU Allocation prüfen
kubectl describe node | grep -A5 "Allocated resources"
```

## Monitoring mit Prometheus

### ServiceMonitor (wenn Prometheus Operator installiert)

```yaml
# kubernetes/servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: triton-metrics
  namespace: triton-inference
spec:
  selector:
    matchLabels:
      app: triton-vllm
  endpoints:
    - port: metrics
      interval: 15s
```

## Operationen

### Scaling

Bei einem einzelnen Server mit 2 GPUs ist horizontales Scaling begrenzt.
Für Multi-Node Cluster:

```bash
# Nicht für Single-Node mit allen GPUs in einem Pod!
# kubectl scale deployment triton-vllm --replicas=2 -n triton-inference
```

### Rolling Update

```bash
# Image Update
kubectl set image deployment/triton-vllm \
  triton=nvcr.io/nvidia/tritonserver:24.09-vllm-python-py3 \
  -n triton-inference

# Status
kubectl rollout status deployment/triton-vllm -n triton-inference
```

### Rollback

```bash
kubectl rollout undo deployment/triton-vllm -n triton-inference
```

## Troubleshooting

### Pod startet nicht

```bash
# Events prüfen
kubectl describe pod -l app=triton-vllm -n triton-inference

# GPU Verfügbarkeit
kubectl describe node | grep nvidia.com/gpu
```

### GPU nicht erkannt

```bash
# GPU Operator Status
kubectl get pods -n gpu-operator

# Device Plugin Logs
kubectl logs -n gpu-operator -l app=nvidia-device-plugin-daemonset
```

### Out of Memory

```bash
# Pod Resources anpassen
kubectl edit deployment triton-vllm -n triton-inference
```

## Backup & Recovery

### Model Cache sichern

```bash
# PVC Snapshot (wenn StorageClass unterstützt)
kubectl apply -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: model-cache-snapshot
  namespace: triton-inference
spec:
  source:
    persistentVolumeClaimName: model-cache
EOF
```

## Weiterführend

- [NVIDIA Triton Kubernetes Deployment Guide](https://github.com/triton-inference-server/server/tree/main/deploy/k8s-onprem)
- [NVIDIA GPU Operator Documentation](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/index.html)
