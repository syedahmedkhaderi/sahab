#!/usr/bin/env python3
"""Sahab CPU-base workspace smoke test.

Must exit non-zero on any failure. Run after every image build:
  docker run --rm sahab-cpu-base:latest python /tmp/smoke_test.py

NOTE: No GPU assertions here. This image runs on CPU only.
"""
import sys
import subprocess

print("=== Sahab CPU-base workspace smoke test ===")

# --- PyTorch (CPU) ---
import torch

# CPU image: we only verify torch imports correctly, not CUDA.
print(f"torch {torch.__version__}: OK (CPU build — cuda available: {torch.cuda.is_available()})")

# Basic CPU tensor op to confirm the installation is functional.
x = torch.randn(256, 256)
result = x @ x
assert result.shape == (256, 256), "matmul shape mismatch"
del x, result
print("CPU compute: OK")

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
