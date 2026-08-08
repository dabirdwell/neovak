# NeoVak — Claude Code Orientation

## What This Is
NeoVak is a NiceGUI-based local AI creative suite ("LM Studio for multimedia"). 
It wraps ComfyUI for image/video generation and has direct-mode Chatterbox TTS.

## Architecture
- `neovak_ui.py` — NiceGUI frontend (2368 lines)
- `neovak_backend.py` — Backend logic, model discovery, ComfyUI integration (3395 lines)
- `neovak_progress.py` — Progress tracking for ComfyUI generations
- `neovak_launcher.py` — App launcher
- `workflows/` — ComfyUI workflow JSON files

## Current Sprint
**Read `SPRINT_ACESTEP.md` first** — it's the full sprint spec for:
1. Integrating ACE-Step 1.5 music generation (REST API on port 8001)
2. Overhauling the music tab UI
3. Cleaning up Forge→NeoVak rename residuals

## ACE-Step Server
Already installed and tested at `~/ACE-Step-1.5`. Server runs on port 8001.
Start with: `cd ~/ACE-Step-1.5 && ./start_api_server_macos.sh`
The sprint spec has **verified API formats** with actual response examples.

## Key Notes
- This is a Mac Studio (M2 Ultra, 192GB RAM)
- Python 3.11 available, venv at `./venv/`
- ComfyUI backend at port 8188, ACE-Step at port 8001
- ffmpeg installed at `/opt/homebrew/bin/ffmpeg`, symlinked into ACE-Step venv

## Related

- [[CLAUDE_CODE_PHASE1]]
- [[SE_Post_Image_Generation_Spec]]
- [[Remote_Claude_Code_Auth]]
- [[Claude_AI_vs_Claude_Code_Decision_Guide]]
- [[Claude_Code_Source_Brief_March2026]]
