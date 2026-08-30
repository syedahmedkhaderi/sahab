FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip==24.2

# CPU-only PyTorch wheels (no CUDA userspace, dramatically smaller image)
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    torch==2.4.0 \
    torchvision==0.19.0 \
    torchaudio==2.4.0 \
    --index-url https://download.pytorch.org/whl/cpu

# All other packages from the exact-pinned requirements file
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# code-server (VS Code in the browser)
RUN curl -fsSL https://code-server.dev/install.sh | sh

# jupyter-server-proxy config: registers code-server in JupyterLab launcher
RUN mkdir -p /etc/jupyter
COPY jupyter_server_config.py /etc/jupyter/jupyter_server_config.py
COPY jupyter_lab_config.py /etc/jupyter/jupyter_lab_config.py

# ---------------------------------------------------------------------------
# Sahab workspace configuration: Lab settings defaults and custom CSS.
#
# The settings path is resolved from sys.prefix rather than hardcoded, because
# the GPU image is Miniconda under /opt/conda and the CPU image is system
# Python under /usr/local. The trailing json.load makes a malformed overrides
# file fail the build instead of shipping and being silently ignored.
#
# custom.css must live in the ServerApp's config_dir, which is
# /home/jovyan/.jupyter. That is deliberately NOT under /home/jovyan/work,
# which is a mounted named volume that would shadow anything baked in here.
# ---------------------------------------------------------------------------
COPY vscode-icon.svg /opt/sahab/icons/vscode.svg
COPY lab-overrides.json /tmp/lab-overrides.json
COPY custom.css /tmp/custom.css
RUN LAB_SETTINGS="$(python -c 'import os,sys; print(os.path.join(sys.prefix, "share/jupyter/lab/settings"))')" && \
    mkdir -p "$LAB_SETTINGS" /home/jovyan/.jupyter/custom && \
    cp /tmp/lab-overrides.json "$LAB_SETTINGS/overrides.json" && \
    cp /tmp/custom.css /home/jovyan/.jupyter/custom/custom.css && \
    python -c "import json,sys; json.load(open(sys.argv[1]))" "$LAB_SETTINGS/overrides.json" && \
    rm /tmp/lab-overrides.json /tmp/custom.css

COPY config_test.py /tmp/config_test.py

COPY smoke_test.py /tmp/smoke_test.py

RUN useradd -m -s /bin/bash jovyan && \
    mkdir -p /home/jovyan/work && \
    chown -R jovyan:jovyan /home/jovyan

USER jovyan
WORKDIR /home/jovyan

EXPOSE 8888
CMD ["jupyterhub-singleuser", "--ip=0.0.0.0"]
