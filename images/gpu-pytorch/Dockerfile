FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/opt/conda/bin:$PATH \
    SHELL=/bin/bash \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl git bzip2 ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python 3.11 via Miniconda (pinned installer)
RUN wget -q \
    https://repo.anaconda.com/miniconda/Miniconda3-py311_24.5.0-0-Linux-x86_64.sh \
    -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh && \
    conda clean -afy && \
    pip install --no-cache-dir --upgrade pip==24.2

# PyTorch 2.4.0 + CUDA 12.4 installed first to anchor numpy ABI.
# torch/torchvision/torchaudio come from the PyTorch cu124 index;
# numpy is pinned here so nothing later can up/downgrade it.
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    torch==2.4.0 \
    torchvision==0.19.0 \
    torchaudio==2.4.0 \
    --index-url https://download.pytorch.org/whl/cu124

# All other packages from the exact-pinned requirements file
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# code-server (VS Code in the browser) — installs to /usr/bin/code-server
RUN curl -fsSL https://code-server.dev/install.sh | sh

# jupyter-server-proxy config: registers code-server in JupyterLab launcher
RUN mkdir -p /opt/conda/etc/jupyter
COPY jupyter_server_config.py /opt/conda/etc/jupyter/jupyter_server_config.py

COPY smoke_test.py /tmp/smoke_test.py

RUN useradd -m -s /bin/bash jovyan && \
    mkdir -p /home/jovyan/work && \
    chown -R jovyan:jovyan /home/jovyan

USER jovyan
WORKDIR /home/jovyan

EXPOSE 8888
CMD ["jupyterhub-singleuser", "--ip=0.0.0.0"]
