# NVIDIA Stack Installation

Installation von NVIDIA Driver, CUDA und Container Toolkit für H200 GPUs.

## Übersicht

| Komponente | Version |
|------------|---------|
| NVIDIA Driver | 550+ |
| CUDA Toolkit | 12.4+ |
| Container Toolkit | Latest |

## Automatische Installation

Das mitgelieferte Script installiert den kompletten Stack:

```bash
sudo ./scripts/install-nvidia.sh
```

Nach der Installation ist ein **Reboot erforderlich**.

## Manuelle Installation

### 1. NVIDIA Driver

```bash
# Nouveau Treiber blacklisten
sudo bash -c "echo blacklist nouveau > /etc/modprobe.d/blacklist-nvidia-nouveau.conf"
sudo bash -c "echo options nouveau modeset=0 >> /etc/modprobe.d/blacklist-nvidia-nouveau.conf"
sudo update-initramfs -u

# Driver installieren
sudo apt update
sudo apt install -y nvidia-driver-550

sudo reboot
```

### 2. CUDA Toolkit

```bash
# CUDA Repository hinzufügen
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb

sudo apt update
sudo apt install -y cuda-toolkit-12-4

# PATH konfigurieren
echo 'export PATH=/usr/local/cuda-12.4/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.4/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```

### 3. Docker

```bash
# Docker Repository
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# User zur docker Gruppe hinzufügen
sudo usermod -aG docker $USER
newgrp docker
```

### 4. NVIDIA Container Toolkit

```bash
# Repository hinzufügen
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
    sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit

# Docker konfigurieren
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

## Verifizierung

### GPU Status

```bash
nvidia-smi
```

Erwartete Ausgabe:
```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 550.xx       Driver Version: 550.xx       CUDA Version: 12.4     |
|-------------------------------+----------------------+----------------------+
| GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
| Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
|===============================+======================+======================|
|   0  NVIDIA H200         On   | 00000000:XX:00.0 Off |                    0 |
| N/A   30C    P0    70W / 700W |      0MiB / 141120MiB |      0%      Default |
+-------------------------------+----------------------+----------------------+
|   1  NVIDIA H200         On   | 00000000:XX:00.0 Off |                    0 |
| N/A   30C    P0    70W / 700W |      0MiB / 141120MiB |      0%      Default |
+-------------------------------+----------------------+----------------------+
```

### CUDA Version

```bash
nvcc --version
```

### Docker GPU Test

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu24.04 nvidia-smi
```

### Beide GPUs prüfen

```bash
# GPU 0
docker run --rm --gpus '"device=0"' nvidia/cuda:12.4.0-base-ubuntu24.04 nvidia-smi

# GPU 1
docker run --rm --gpus '"device=1"' nvidia/cuda:12.4.0-base-ubuntu24.04 nvidia-smi
```

## Troubleshooting

### Driver lädt nicht

```bash
# Kernel Module Status
lsmod | grep nvidia

# Logs prüfen
dmesg | grep -i nvidia
journalctl -b | grep -i nvidia
```

### CUDA nicht gefunden

```bash
# PATH prüfen
echo $PATH
echo $LD_LIBRARY_PATH

# Symlink prüfen
ls -la /usr/local/cuda
```

### Docker sieht keine GPU

```bash
# Runtime prüfen
docker info | grep -i runtime

# Config prüfen
cat /etc/docker/daemon.json
```

## GPU Persistence Mode

Für Production empfohlen (reduziert Initialisierungszeit):

```bash
sudo nvidia-smi -pm 1
```

Automatisch beim Boot:

```bash
sudo systemctl enable nvidia-persistenced
```

## Nächster Schritt

→ [03-docker-deployment.md](03-docker-deployment.md) - Triton + vLLM Deployment
