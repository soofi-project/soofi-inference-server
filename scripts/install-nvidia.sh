#!/bin/bash
set -euo pipefail

#===============================================================================
# NVIDIA Stack Installation Script
# Target: Ubuntu 24.04 LTS with NVIDIA H200 GPUs
# Components: NVIDIA Driver 550+, CUDA 12.4, NVIDIA Container Toolkit
#===============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root (use sudo)"
   exit 1
fi

# Check Ubuntu version
if ! grep -q "Ubuntu 24" /etc/os-release; then
    log_warn "This script is designed for Ubuntu 24.04. Detected:"
    cat /etc/os-release | grep PRETTY_NAME
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

#===============================================================================
# Step 1: System Update
#===============================================================================
log_info "Updating system packages..."
apt-get update
apt-get upgrade -y

#===============================================================================
# Step 2: Install Prerequisites
#===============================================================================
log_info "Installing prerequisites..."
apt-get install -y \
    build-essential \
    dkms \
    curl \
    wget \
    gnupg \
    ca-certificates \
    software-properties-common

#===============================================================================
# Step 3: Install NVIDIA Driver
#===============================================================================
log_info "Adding NVIDIA driver repository..."

# Add NVIDIA package repositories
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

# Install driver from ubuntu repository (recommended for H200)
log_info "Installing NVIDIA Driver 550..."
apt-get install -y nvidia-driver-550

#===============================================================================
# Step 4: Install CUDA Toolkit
#===============================================================================
log_info "Installing CUDA Toolkit 12.4..."

# Add CUDA repository
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
dpkg -i cuda-keyring_1.1-1_all.deb
rm cuda-keyring_1.1-1_all.deb

apt-get update
apt-get install -y cuda-toolkit-12-4

# Add CUDA to PATH
cat >> /etc/profile.d/cuda.sh << 'EOF'
export PATH=/usr/local/cuda-12.4/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-12.4/lib64:$LD_LIBRARY_PATH
EOF

#===============================================================================
# Step 5: Install Docker
#===============================================================================
log_info "Installing Docker..."

# Remove old versions
apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Add Docker repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable Docker service
systemctl enable docker
systemctl start docker

#===============================================================================
# Step 6: Install NVIDIA Container Toolkit
#===============================================================================
log_info "Installing NVIDIA Container Toolkit..."

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
    gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt-get update
apt-get install -y nvidia-container-toolkit

# Configure Docker to use NVIDIA runtime
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

#===============================================================================
# Step 7: Configure System for Large Models
#===============================================================================
log_info "Configuring system limits for large models..."

# Increase file limits
cat >> /etc/security/limits.conf << 'EOF'
* soft nofile 1048576
* hard nofile 1048576
* soft memlock unlimited
* hard memlock unlimited
EOF

# Disable swap (recommended for GPU servers)
swapoff -a
sed -i '/swap/d' /etc/fstab

#===============================================================================
# Verification
#===============================================================================
log_info "Installation complete. System reboot required."
log_info ""
log_info "After reboot, verify installation with:"
log_info "  nvidia-smi                    # Check GPU driver"
log_info "  nvcc --version                # Check CUDA"
log_info "  docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu24.04 nvidia-smi"
log_info ""

read -p "Reboot now? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    reboot
fi
