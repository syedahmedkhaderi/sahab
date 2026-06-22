#!/usr/bin/env python3
"""Sahab GPU-PyTorch workspace smoke test.

Must exit non-zero on any failure. Run after every image build:
  docker run --rm --gpus device=0 sahab-gpu-pytorch:latest python /tmp/smoke_test.py
"""
import sys
import subprocess

print("=== Sahab GPU-PyTorch workspace smoke test ===")

# --- CUDA and GPU ---
import torch

assert torch.cuda.is_available(), "CUDA not available — check NVIDIA runtime and NVIDIA_VISIBLE_DEVICES"
gpu_name = torch.cuda.get_device_name(0)
print(f"GPU: {gpu_name}")
assert "L4" in gpu_name, f"Expected L4, got: {gpu_name} (set NVIDIA_VISIBLE_DEVICES to an L4 UUID)"

x = torch.randn(1024, 1024, device="cuda")
result = x @ x
assert result.is_cuda, "matmul result not on CUDA device"
del x, result
torch.cuda.empty_cache()
print("GPU compute: OK")

# --- Core ML stack ---
import numpy as np
print(f"numpy {np.__version__}: OK")

import pandas
print(f"pandas {pandas.__version__}: OK")

import matplotlib
print(f"matplotlib {matplotlib.__version__}: OK")

import seaborn
print(f"seaborn {seaborn.__version__}: OK")

import sklearn
print(f"scikit-learn {sklearn.__version__}: OK")

import scipy
print(f"scipy {scipy.__version__}: OK")

# --- HuggingFace / LLM stack ---
import tokenizers
print(f"tokenizers {tokenizers.__version__}: OK")

import huggingface_hub
print(f"huggingface-hub {huggingface_hub.__version__}: OK")

import transformers
print(f"transformers {transformers.__version__}: OK")

import datasets
print(f"datasets {datasets.__version__}: OK")

import accelerate
print(f"accelerate {accelerate.__version__}: OK")

import peft
print(f"peft {peft.__version__}: OK")

import safetensors
print(f"safetensors {safetensors.__version__}: OK")

import sentencepiece
print(f"sentencepiece: OK")

import tqdm
print(f"tqdm {tqdm.__version__}: OK")

import PIL
print(f"Pillow {PIL.__version__}: OK")

import requests
print(f"requests {requests.__version__}: OK")

# --- Jupyter stack ---
import jupyterlab
print(f"jupyterlab {jupyterlab.__version__}: OK")

import ipywidgets
print(f"ipywidgets {ipywidgets.__version__}: OK")

# --- code-server ---
result = subprocess.run(["code-server", "--version"], capture_output=True, text=True)
assert result.returncode == 0, f"code-server not found or failed: {result.stderr}"
print(f"code-server {result.stdout.strip().splitlines()[0]}: OK")

print("\n=== All smoke tests passed. ===")
