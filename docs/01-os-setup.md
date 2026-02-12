# Ubuntu 24.04 Server Setup

Basis-Installation und Konfiguration für den AI Inference Server.

## Hardware-Voraussetzungen

| Komponente | Spezifikation |
|------------|---------------|
| GPU | 2x NVIDIA H200 (141 GB HBM3e) |
| CPU | 2x AMD EPYC GENOA 9124 |
| RAM | 256 GB |
| Storage | 3.84 TB SSD |

## Ubuntu Installation

### ISO Download

Ubuntu Server 24.04 LTS von der offiziellen Quelle:
```
https://ubuntu.com/download/server
```

### Installation

1. Von USB/ISO booten
2. **Minimized Installation** auswählen (ohne Desktop)
3. Partitionierung:

```
/boot/efi    512 MB   (EFI System Partition)
/boot        1 GB     (ext4)
/            100 GB   (ext4) - System
/var         Rest     (ext4) - Docker Images, Model Cache
```

4. OpenSSH Server aktivieren
5. Keine zusätzlichen Snaps installieren

## Post-Installation

### System Update

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

### Basis-Pakete

```bash
sudo apt install -y \
    build-essential \
    curl \
    wget \
    git \
    htop \
    nvme-cli \
    net-tools \
    vim
```

### SSH Konfiguration

```bash
# SSH Key Authentication erzwingen
sudo vim /etc/ssh/sshd_config
```

Empfohlene Einstellungen:
```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

```bash
sudo systemctl restart sshd
```

### Netzwerk (optional: statische IP)

```bash
sudo vim /etc/netplan/00-installer-config.yaml
```

```yaml
network:
  version: 2
  ethernets:
    eth0:
      addresses:
        - 192.168.1.100/24
      routes:
        - to: default
          via: 192.168.1.1
      nameservers:
        addresses:
          - 8.8.8.8
          - 8.8.4.4
```

```bash
sudo netplan apply
```

### Firewall

```bash
sudo ufw allow ssh
sudo ufw allow 8000/tcp  # Triton HTTP
sudo ufw allow 8001/tcp  # Triton gRPC
sudo ufw allow 8002/tcp  # Metrics
sudo ufw enable
```

### System Limits

Für große Modelle und viele gleichzeitige Verbindungen:

```bash
sudo vim /etc/security/limits.conf
```

Hinzufügen:
```
* soft nofile 1048576
* hard nofile 1048576
* soft memlock unlimited
* hard memlock unlimited
```

### Swap deaktivieren

Für GPU-Server empfohlen:

```bash
sudo swapoff -a
sudo sed -i '/swap/d' /etc/fstab
```

## Verifizierung

```bash
# System Info
uname -a
cat /etc/os-release

# Hardware Check
lscpu | grep "Model name"
free -h
lsblk
```

## Nächster Schritt

→ [02-nvidia-setup.md](02-nvidia-setup.md) - NVIDIA Driver und CUDA Installation
