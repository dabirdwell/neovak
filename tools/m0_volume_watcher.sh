#!/bin/bash
# m0_volume_watcher.sh — polls for Mix Master Mike, verifies H3 weights,
# resumes the fp8 download, runs the M0 probe ONLY if governor preflight
# clears. Log: /Users/david/Documents/Claude_Technical/neovak/tools/m0_watch.log
LOG=/Users/david/Documents/Claude_Technical/neovak/tools/m0_watch.log
exec >> "$LOG" 2>&1
export PATH=/opt/homebrew/bin:/opt/homebrew/sbin:$PATH
MMM="/Volumes/Mix Master Mike/ComfyUI/models"
echo "[$(date '+%F %T')] watcher armed, polling every 60s (12h cap)"
for i in $(seq 1 720); do
  [ -d "$MMM" ] && break
  sleep 60
done
if [ ! -d "$MMM" ]; then
  echo "[$(date '+%F %T')] gave up after 12h, volume never appeared"
  exit 1
fi
echo "[$(date '+%F %T')] VOLUME MOUNTED"
sleep 10
echo "--- weight check ---"
for f in "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors" \
         "text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors" \
         "vae/minimax_h3_video_vae_fp16.safetensors" \
         "vae/minimax_h3_audio_vae_fp32.safetensors"; do
  [ -f "$MMM/$f" ] && echo "PRESENT $f" || echo "MISSING $f"
done
echo "--- officer ggufs on this volume (for plist regen) ---"
find "/Volumes/Mix Master Mike" -maxdepth 3 -iname "*free_mind*.gguf" 2>/dev/null | head -4
echo "--- resuming fp8 download (hf resumes partials) ---"
hf download Comfy-Org/MiniMax-H3 \
  diffusion_models/minimax_h3_fl2va_pruned_fp8_scaled.safetensors \
  --local-dir "$MMM" || { echo "[$(date '+%F %T')] DOWNLOAD FAILED"; exit 1; }
echo "[$(date '+%F %T')] fp8 download complete"
echo "--- governor preflight before any probe ---"
PF=$(/opt/homebrew/bin/python3 /Users/david/Documents/Claude_Technical/model_governor.py preflight 32)
echo "$PF"
if echo "$PF" | grep -q "VERDICT: GO"; then
  echo "[$(date '+%F %T')] GO — launching ComfyUI (skipped if :8188 already held) + probe"
  if ! lsof -i :8188 >/dev/null 2>&1; then
    cd /Users/david/Documents/AI-Projects/ComfyUI
    nohup venv/bin/python main.py --listen 127.0.0.1 --port 8188 --cache-none \
      > /Users/david/Documents/Claude_Technical/neovak/tools/comfy_m0.log 2>&1 &
    sleep 90
  fi
  M0_UNET="minimax_h3_fl2va_pruned_fp8_scaled.safetensors" \
    /opt/homebrew/bin/python3 /Users/david/Documents/Claude_Technical/neovak/tools/m0_probe.py
  echo "[$(date '+%F %T')] probe finished — see lines above for wall time / peak RSS / ffprobe"
else
  echo "[$(date '+%F %T')] NO-GO on memory — download secured, probe HELD. Rerun after memory eases:"
  echo "  M0_UNET=minimax_h3_fl2va_pruned_fp8_scaled.safetensors /opt/homebrew/bin/python3 /Users/david/Documents/Claude_Technical/neovak/tools/m0_probe.py"
fi
