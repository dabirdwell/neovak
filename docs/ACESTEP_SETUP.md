# ACE-Step 1.5 Setup for NeoVak

ACE-Step 1.5 is NeoVak's music generation backend. It runs as a separate service on port 8001.

## Quick Start

```bash
# 1. Clone ACE-Step (if not already installed)
cd ~
git clone https://github.com/ACE-Step/ACE-Step-1.5.git

# 2. Start the API server (auto-installs deps, downloads models on first run)
cd ~/ACE-Step-1.5
./start_api_server_macos.sh

# 3. Verify it's running
curl http://localhost:8001/health
```

Or use the helper script from NeoVak:
```bash
./start_acestep.sh
```

## First Run

- Models auto-download on first run (~13GB to `~/ACE-Step-1.5/checkpoints/`)
- The macOS script auto-detects Apple Silicon and uses the MLX backend
- ffmpeg is required for MP3 export: `brew install ffmpeg`

## Requirements

- macOS with Apple Silicon (M1/M2/M3/M4)
- ~4GB free VRAM for base model, ~6GB with LM planner
- Python 3.10+ (managed by ACE-Step's own venv via `uv`)
- ffmpeg for MP3 output

## Verifying in NeoVak

Once the server is running, switch to the **Music** tab in NeoVak. The status bar at the top should show a green dot with "Connected".

## Configuration

Set a custom ACE-Step URL in `neovak_config.json`:
```json
{
    "acestep_url": "http://127.0.0.1:8001"
}
```

Or via environment variable:
```bash
export ACESTEP_URL="http://127.0.0.1:8001"
```

## Performance (Mac Studio, M2 Ultra, 192GB)

- 15s clip: ~12s (7.5s LM + 4.5s DiT)
- 2min track: ~2-3min
- Output: MP3, 48kHz, 128kbps

## Related

- [[Dual_Publishing_Setup]]
