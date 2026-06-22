#!/bin/bash
# Sahab Platform - Phase 1 Setup Script
# Run on the GPU server as: bash sahab_phase1_setup.sh

set -e

SAHAB_DIR="$HOME/sahab"
mkdir -p "$SAHAB_DIR"/{jupyterhub,images/gpu-pytorch}
cd "$SAHAB_DIR"
echo "Project directory: $SAHAB_DIR"

# ------------------------------------------------------------------
# 1. JupyterHub container Dockerfile
# ------------------------------------------------------------------
cat > jupyterhub/Dockerfile << 'DOCKERFILE'
FROM jupyterhub/jupyterhub:4.1.6

RUN pip install --no-cache-dir \
    dockerspawner==13.0.0 \
    jupyterhub-nativeauthenticator==1.3.0 \
    jupyterhub-idle-culler==1.3.1
DOCKERFILE

# ------------------------------------------------------------------
# 2. JupyterHub config
# ------------------------------------------------------------------
cat > jupyterhub/jupyterhub_config.py << 'PYCONFIG'
import os

c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = "sahab-hub"
c.JupyterHub.port = 8000

c.JupyterHub.db_url = "sqlite:////srv/jupyterhub/jupyterhub.sqlite"
c.JupyterHub.cookie_secret_file = "/srv/jupyterhub/jupyterhub_cookie_secret"

c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.image = os.environ.get("WORKSPACE_GPU_IMAGE", "sahab-gpu-pytorch:latest")
c.DockerSpawner.network_name = os.environ.get("DOCKER_NETWORK_NAME", "sahab-network")
c.DockerSpawner.use_internal_ip = True
c.DockerSpawner.remove = True

# Phase 1: all GPUs visible. Phase 2 control plane will pin one GPU UUID per session.
c.DockerSpawner.extra_host_config = {
    "runtime": "nvidia",
}
c.DockerSpawner.environment = {
    "NVIDIA_VISIBLE_DEVICES": "all",
    "NVIDIA_DRIVER_CAPABILITIES": "compute,utility",
}

c.DockerSpawner.notebook_dir = "/home/jovyan/work"
c.DockerSpawner.volumes = {
    "sahab-user-{username}": "/home/jovyan/work",
}

c.DockerSpawner.mem_limit = "32G"
c.DockerSpawner.cpu_limit = 8

c.JupyterHub.authenticator_class = "nativeauthenticator.NativeAuthenticator"
c.NativeAuthenticator.enable_signup = True
c.NativeAuthenticator.minimum_password_length = 8
c.NativeAuthenticator.check_common_password = True
# Change "syed" to your JupyterHub login username
c.Authenticator.admin_users = {"syed"}

# Stop servers idle for 45 minutes
c.JupyterHub.services = [
    {
        "name": "idle-culler",
        "command": [
            "python", "-m", "jupyterhub_idle_culler",
            "--timeout=2700",
        ],
    }
]
PYCONFIG

# ------------------------------------------------------------------
# 3. Workspace GPU image Dockerfile
# ------------------------------------------------------------------
cat > images/gpu-pytorch/Dockerfile << 'DOCKERFILE'
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/opt/conda/bin:$PATH \
    SHELL=/bin/bash

RUN apt-get update && apt-get install -y \
    wget curl git bzip2 ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python 3.11 via Miniconda
RUN wget -q \
    https://repo.anaconda.com/miniconda/Miniconda3-py311_24.5.0-0-Linux-x86_64.sh \
    -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh && \
    conda clean -afy && \
    pip install --no-cache-dir --upgrade pip

# PyTorch 2.4.0 + CUDA 12.4 (installed first to anchor numpy)
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    torch==2.4.0 \
    torchvision==0.19.0 \
    torchaudio==2.4.0 \
    --index-url https://download.pytorch.org/whl/cu124

# All other packages from pinned lockfile
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# code-server (VS Code in the browser)
RUN curl -fsSL https://code-server.dev/install.sh | sh

# jupyter-server-proxy config: exposes code-server in the JupyterLab launcher
RUN mkdir -p /opt/conda/etc/jupyter
COPY jupyter_server_config.py /opt/conda/etc/jupyter/jupyter_server_config.py

COPY smoke_test.py /tmp/smoke_test.py

RUN mkdir -p /home/jovyan/work
WORKDIR /home/jovyan

EXPOSE 8888
CMD ["jupyterhub-singleuser", "--ip=0.0.0.0"]
DOCKERFILE

# ------------------------------------------------------------------
# 4. requirements.txt (torch and numpy are installed above, not here)
# ------------------------------------------------------------------
cat > images/gpu-pytorch/requirements.txt << 'REQTXT'
jupyterhub==4.1.6
jupyterlab==4.2.5
jupyter-server==2.14.2
jupyter-server-proxy==4.3.0
jupyterlab-git==0.50.1
ipywidgets==8.1.5
pandas==2.2.2
matplotlib==3.9.2
seaborn==0.13.2
scikit-learn==1.5.2
scipy==1.13.1
tokenizers==0.19.1
huggingface-hub==0.24.6
transformers==4.44.2
datasets==2.21.0
accelerate==0.33.0
peft==0.12.0
safetensors==0.4.4
sentencepiece==0.2.0
tqdm==4.66.5
Pillow==10.4.0
requests==2.32.3
REQTXT

# ------------------------------------------------------------------
# 5. jupyter-server-proxy config (adds VS Code button to JupyterLab)
# ------------------------------------------------------------------
cat > images/gpu-pytorch/jupyter_server_config.py << 'PYCONFIG'
c.ServerProxy.servers = {
    "vscode": {
        "command": [
            "code-server",
            "--auth", "none",
            "--disable-telemetry",
            "--disable-update-check",
            "--user-data-dir", "/home/jovyan/work/.vscode-data",
            "--extensions-dir", "/home/jovyan/work/.vscode-extensions",
            "--bind-addr", "127.0.0.1:{port}",
        ],
        "timeout": 30,
        "new_browser_tab": True,
        "launcher_entry": {
            "title": "VS Code",
        },
    }
}
PYCONFIG

# ------------------------------------------------------------------
# 6. Smoke test (run after image build to catch any breakage)
# ------------------------------------------------------------------
cat > images/gpu-pytorch/smoke_test.py << 'SMOKETEST'
import sys
import subprocess
print("Running Sahab workspace smoke test...")

import torch
assert torch.cuda.is_available(), "CUDA not available -- check NVIDIA runtime"
gpu_name = torch.cuda.get_device_name(0)
print(f"GPU: {gpu_name}")
assert "L4" in gpu_name, f"Expected L4, got: {gpu_name}"

x = torch.randn(512, 512, device="cuda")
result = x @ x.T
assert result.is_cuda
del x, result
torch.cuda.empty_cache()
print("GPU compute: OK")

import numpy as np;      print(f"numpy {np.__version__}: OK")
import pandas;           print(f"pandas {pandas.__version__}: OK")
import matplotlib;       print(f"matplotlib {matplotlib.__version__}: OK")
import sklearn;          print(f"scikit-learn {sklearn.__version__}: OK")
import transformers;     print(f"transformers {transformers.__version__}: OK")
import datasets;         print(f"datasets {datasets.__version__}: OK")
import jupyterlab;       print(f"jupyterlab {jupyterlab.__version__}: OK")

result = subprocess.run(["code-server", "--version"], capture_output=True, text=True)
assert result.returncode == 0, f"code-server not found: {result.stderr}"
print(f"code-server {result.stdout.strip()}: OK")

print("\nAll smoke tests passed.")
SMOKETEST

# ------------------------------------------------------------------
# 7. Docker Compose
# ------------------------------------------------------------------
cat > docker-compose.yml << 'COMPOSE'
version: "3.8"

services:
  jupyterhub:
    build: ./jupyterhub
    image: sahab-hub:latest
    container_name: sahab-hub
    ports:
      - "8000:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./jupyterhub/jupyterhub_config.py:/srv/jupyterhub/jupyterhub_config.py:ro
      - sahab-hub-db:/srv/jupyterhub
    environment:
      DOCKER_NETWORK_NAME: sahab-network
      WORKSPACE_GPU_IMAGE: sahab-gpu-pytorch:latest
    networks:
      - sahab-network
    restart: unless-stopped

networks:
  sahab-network:
    name: sahab-network
    driver: bridge
    attachable: true

volumes:
  sahab-hub-db:
COMPOSE

echo ""
echo "All files written to $SAHAB_DIR"
echo ""
echo "NEXT STEPS (run these one at a time):"
echo ""
echo "Step 1 - Build the workspace image (takes 15-25 min, downloads ~5 GB):"
echo "  cd ~/sahab"
echo "  docker build -t sahab-gpu-pytorch:latest ./images/gpu-pytorch/"
echo ""
echo "Step 2 - Run the smoke test (must pass before continuing):"
echo "  docker run --rm --gpus device=0 sahab-gpu-pytorch:latest python /tmp/smoke_test.py"
echo ""
echo "Step 3 - Start JupyterHub:"
echo "  cd ~/sahab && docker compose up -d"
echo ""
echo "Step 4 - Open in your browser (while on the VPN):"
echo "  http://10.125.81.52:8000"
echo ""
echo "First login: click 'Sign Up', create your account (username: syed)."
echo "Admin approval is at: http://10.125.81.52:8000/hub/authorize"
