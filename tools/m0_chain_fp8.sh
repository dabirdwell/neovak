#!/bin/bash
export PATH=/opt/homebrew/bin:/opt/homebrew/sbin:$PATH
MMM="/Volumes/Mix Master Mike/ComfyUI/models"
echo "[$(date +%H:%M:%S)] downloading fp8_scaled DiT (21G)"
hf download Comfy-Org/MiniMax-H3 diffusion_models/minimax_h3_fl2va_pruned_fp8_scaled.safetensors --local-dir "$MMM" || { echo DOWNLOAD FAILED; exit 1; }
echo "[$(date +%H:%M:%S)] download complete, rerunning probe with fp8"
M0_UNET="minimax_h3_fl2va_pruned_fp8_scaled.safetensors" /opt/homebrew/bin/python3 /Users/david/Documents/Claude_Technical/neovak/tools/m0_probe.py
