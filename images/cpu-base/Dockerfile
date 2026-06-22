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

COPY smoke_test.py /tmp/smoke_test.py

RUN useradd -m -s /bin/bash jovyan && \
    mkdir -p /home/jovyan/work && \
    chown -R jovyan:jovyan /home/jovyan

USER jovyan
WORKDIR /home/jovyan

EXPOSE 8888
CMD ["jupyterhub-singleuser", "--ip=0.0.0.0"]
