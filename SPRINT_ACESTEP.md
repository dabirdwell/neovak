# Sprint: NeoVak Major Refresh + ACE-Step 1.5 Music Integration

**Date:** April 11, 2026
**Type:** Claude Code CLI task
**Codebase:** `/Users/david/Documents/Fawkes/Products and Services/NeoVak/`
**Priority:** High — completes the music tab which is currently stub-only

---

## Context

NeoVak (formerly Forge) is a NiceGUI-based local AI creative suite at v1.2.0. It wraps ComfyUI for image (Flux/SDXL/Qwen) and video (LTX-Video/Wan) generation, has direct-mode Chatterbox TTS for voice, and AudioGen for sound effects. The music tab exists in the UI but routes to ComfyUI-based MusicGen/StableAudio/AudioCraft workflows that are essentially stubs — no one has these ComfyUI nodes installed, and the workflows are untested.

ACE-Step 1.5 is a new open-source music generation model (MIT license, commercially safe, royalty-free training data) that:
- Runs natively on Mac via MLX backend
- Has its own REST API server (port 8001 by default)
- Generates full songs (10s–10min) from text tags + structured lyrics
- Supports cover generation, repainting, vocal-to-BGM
- Needs <4GB VRAM for base model, <6GB with LM planner
- Has native macOS launch scripts with MLX auto-detection
- Models auto-download on first run (~10GB)

**Key insight:** ACE-Step has its own REST API (`POST /release_task`, `POST /query_result`) that NeoVak can talk to directly — same pattern as the ComfyUI backend, but a separate service on a different port.

---

## Architecture Decision

**ACE-Step runs as a separate backend service** (like ComfyUI), NOT embedded in NeoVak's Python process. Reasons:
1. ACE-Step has heavy dependencies (its own torch, mlx, transformers) that would conflict with NeoVak's venv
2. It already has a production REST API with async task queuing
3. Follows the same pattern as ComfyUI — NeoVak is the UI layer, backends do the heavy lifting
4. User starts ACE-Step server separately (or NeoVak can auto-launch it)

**Integration pattern:**
```
NeoVak UI (NiceGUI, port 7861)
    │
    ├── ComfyUI backend (port 8188) — images, video, sfx
    │
    └── ACE-Step backend (port 8001) — music generation
```

---

## File Inventory

### Files to modify:
- `neovak_backend.py` (3395 lines) — Add ACE-Step client, music generation via REST API
- `neovak_ui.py` (2368 lines) — Overhaul music tab UI, add ACE-Step status/controls
- `neovak_config.example.json` — Add `acestep_url` config
- `requirements.txt` — Add `requests` if not present (for ACE-Step API calls)

### Files to create:
- `acestep_client.py` — Standalone ACE-Step REST API client (clean separation)
- `start_acestep.sh` — Helper script to launch ACE-Step server
- `docs/ACESTEP_SETUP.md` — User guide for ACE-Step installation

### Files to NOT touch:
- `neovak_progress.py` — works fine
- `neovak_launcher.py` — works fine
- `workflows/` — ACE-Step doesn't use ComfyUI workflows
- `packaging/` — no changes needed yet

---

## Task 1: Create `acestep_client.py`

A clean, standalone client for the ACE-Step REST API.

```python
"""
ACE-Step 1.5 REST API Client for NeoVak.
Talks to the ACE-Step API server (default: http://localhost:8001).
"""

# Key functions to implement:

def check_acestep_backend(url: str = "http://localhost:8001") -> tuple[bool, str]:
    """Check if ACE-Step API server is running. Hit GET /health."""

def get_available_models(url: str) -> list[dict]:
    """GET /get_models — returns available DiT models."""

def generate_music(
    url: str,
    caption: str,          # Style tags: "indie pop, acoustic guitar, warm vocals"
    lyrics: str = "",      # Structured: "[Verse]\nWords...\n[Chorus]\n..."
    duration: int = 120,   # seconds (10-600)
    seed: int = -1,
    thinking: bool = True, # Use LM planner for better results
    batch_size: int = 1,
    # Advanced params:
    infer_step: int = 30,
    guidance_scale: float = 15.0,
    guidance_scale_text: float = 0.0,
    guidance_scale_lyric: float = 0.0,
    # Optional:
    model: str = "",       # specific DiT model
    lm_model: str = "",    # specific LM model
    # Audio conditioning (for cover/repaint):
    audio_path: str = "",
    repaint_start: float = 0.0,
    repaint_end: float = 0.0,
    progress_callback=None
) -> tuple[Optional[str], str]:
    """
    Submit a music generation task and poll for result.
    
    Flow:
    1. POST /release_task with params → get task_id
    2. Poll POST /query_result with {"task_id_list": [task_id]}
    3. Check status: 0=processing, 1=completed, 2=failed
    4. On completion, result field is a JSON STRING (double-parse!)
       containing [{file: "/v1/audio?path=...", metas: {...}, ...}]
    5. Download audio via GET {url}{file_path}
    6. Save to NeoVak output dir
    
    Returns: (output_path, status_message)
    """

def format_input(
    url: str,
    caption: str,
    lyrics: str = ""
) -> dict:
    """
    POST /format_input — Use LM to expand short tags into full captions/lyrics
    without generating audio. Useful for preview/refinement.
    Returns: {"caption": "...", "lyrics": "..."}
    """

def get_acestep_status(url: str) -> dict:
    """GET /v1/stats — server load, queue depth, avg job time."""
```

### ACE-Step API Reference (VERIFIED April 11, 2026 on Mac Studio):

**POST /release_task:**
```json
{
    "caption": "indie pop, acoustic guitar, warm vocals, dreamy atmosphere",
    "lyrics": "[Verse]\nWalking down this road\nCarrying this heavy load\n\n[Chorus]\nBut we keep on moving",
    "duration": 120,
    "infer_step": 30,
    "guidance_scale": 15.0,
    "guidance_scale_text": 0.0,
    "guidance_scale_lyric": 0.0,
    "seed": -1,
    "batch_size": 1,
    "thinking": true,
    "model": "",
    "lm_model": ""
}
```
Response: `{"data": {"task_id": "xxx", "status": "queued", "queue_position": 1}, "code": 200, ...}`

**POST /query_result:** (NOTE: uses `task_id_list`, NOT `task_id`)
```json
{"task_id_list": ["<task_id>"]}
```
Response: `data` is an array. Each item has:
- `status`: 0 = processing, 1 = completed, 2 = failed
- `result`: **JSON string** (needs double-parse!) containing array of results
- `progress_text`: progress/error messages

The `result` field (after JSON.parse) contains:
```json
[{
    "file": "/v1/audio?path=%2F...%2Foutput.mp3",  // Download URL path
    "wave": "",
    "status": 1,
    "metas": {"bpm": 86, "duration": 15.0, "keyscale": "C# major", "timesignature": "4"},
    "generation_info": "Total generation time: 11.92s...",
    "seed_value": "2103560926",
    "lm_model": "acestep-5Hz-lm-0.6B",
    "dit_model": "acestep-v15-turbo",
    "progress": 1.0,
    "stage": "succeeded"
}]
```

**GET /v1/audio?path=<url_encoded_path>:** Download the generated MP3 file.

**GET /health:** Returns `models_initialized` and `llm_initialized` booleans.

**GET /v1/stats:** Queue depth, avg job time.

**POST /format_input:** LM-enhanced prompt/lyrics expansion.

### Performance (Mac Studio, M2 Ultra, 192GB):
- 15s clip: ~12s total (7.5s LM + 4.5s DiT)
- Model: acestep-v15-turbo with acestep-5Hz-lm-0.6B
- Output: MP3, 48kHz, 128kbps
- First-run model download: ~13GB to ~/ACE-Step-1.5/checkpoints/

---

## Task 2: Update `neovak_backend.py`

### 2a. Add ACE-Step configuration
At the top config section, add:
```python
ACESTEP_URL = _get_config('acestep_url', 'ACESTEP_URL', "http://127.0.0.1:8001")
ACESTEP_DIR = Path(_get_config('acestep_dir', 'ACESTEP_DIR', 
    Path.home() / "ACE-Step-1.5"))
```

### 2b. Add ACE-Step to model classification
In `SPECIFIC_MODEL_INFO` and `FAMILY_FALLBACKS`, add:
```python
"acestep": {
    "type": "music", 
    "desc": "ACE-Step 1.5. Commercial-grade music from text+lyrics. Under 4GB VRAM.",
    "backend": "acestep"
},
```

### 2c. Add ACE-Step backend check
```python
def check_acestep_backend() -> tuple[bool, str]:
    """Check if ACE-Step API server is running."""
    from acestep_client import check_acestep_backend as _check
    return _check(ACESTEP_URL)
```

### 2d. Replace `generate_music()` function
The existing `generate_music()` routes through ComfyUI. Replace with:
```python
def generate_music(
    prompt: str,
    lyrics: str = "",
    duration: int = 120,
    seed: int = -1,
    thinking: bool = True,
    progress_callback=None
) -> tuple[Optional[str], str]:
    """Generate music using ACE-Step 1.5 backend."""
    from acestep_client import generate_music as _generate
    return _generate(
        url=ACESTEP_URL,
        caption=prompt,
        lyrics=lyrics,
        duration=duration,
        seed=seed,
        thinking=thinking,
        progress_callback=progress_callback
    )
```

Keep the old ComfyUI music functions but mark them as deprecated/fallback.

### 2e. Update `MUSIC_STYLE_TAGS` and `MUSIC_DURATION_PRESETS`
Replace with ACE-Step-appropriate values:
```python
MUSIC_STYLE_TAGS = [
    # Genre
    "pop", "rock", "jazz", "classical", "electronic", "hip-hop", "r&b",
    "country", "folk", "blues", "metal", "punk", "indie", "ambient",
    "lo-fi", "synthwave", "disco", "reggae", "latin", "k-pop",
    # Instruments
    "acoustic guitar", "electric guitar", "piano", "synth", "drums",
    "bass", "strings", "brass", "woodwinds", "choir",
    # Mood
    "upbeat", "melancholic", "energetic", "calm", "dark", "dreamy",
    "aggressive", "romantic", "epic", "intimate", "playful",
    # Vocal
    "male vocals", "female vocals", "vocal harmony", "rap", "spoken word",
    "no vocals", "instrumental",
]

MUSIC_DURATION_PRESETS = [
    ("Short", 30, "~30 second clip"),
    ("Medium", 120, "~2 minute track"),
    ("Standard", 180, "~3 minute song"),
    ("Long", 300, "~5 minute piece"),
    ("Extended", 600, "~10 minute composition"),
]
```

### 2f. Add `RecommendedModel` entry for ACE-Step
In the recommendations catalog:
```python
RecommendedModel(
    name="ACE-Step 1.5",
    type="music",
    size="~10GB (auto-downloads)",
    min_ram=8,
    description="Commercial-grade music generation. Full songs from text + lyrics.",
    url="https://github.com/ACE-Step/ACE-Step-1.5",
    filename="",  # Not a single file — separate service
    priority=1,
)
```

---

## Task 3: Overhaul Music Tab in `neovak_ui.py`

The current music tab is a bare stub. Replace with a full-featured music creation panel.

### Layout:
```
┌─────────────────────────────────────────────────────────────────┐
│  ACE-Step Status: ● Connected (port 8001)    [Start Server]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  STYLE TAGS                                                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ indie pop, acoustic guitar, warm vocals, dreamy            │  │
│  └────────────────────────────────────────────────────────────┘  │
│  Quick tags: [pop] [rock] [jazz] [electronic] [ambient] ...     │
│                                                                  │
│  LYRICS (optional)                                               │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ [Verse 1]                                                   │  │
│  │ Walking down the street                                     │  │
│  │ Music in my feet                                            │  │
│  │                                                              │  │
│  │ [Chorus]                                                     │  │
│  │ We are alive tonight                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
│  [✨ Expand with AI]  — uses /format_input to flesh out         │
│                                                                  │
│  DURATION                                                        │
│  ○ Short (30s)  ○ Medium (2m)  ● Standard (3m)  ○ Long (5m)   │
│                                                                  │
│  [▾ Advanced Settings]                                           │
│    Seed: [-1          ]  Thinking: [✓]                          │
│    Inference steps: [60]  Guidance: [15.0]                      │
│                                                                  │
│  [🎵 Generate Music]                                             │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│  OUTPUT                                                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  🎵  [▶ Play]  [⏸]  [⬇ Download]                          │  │
│  │  ═══════════●════════════════════  2:34 / 3:00             │  │
│  │  Seed: 42381  [📋]                                         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  HISTORY                                                         │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                           │
│  │ 🎵   │ │ 🎵   │ │ 🎵   │ │ 🎵   │                           │
│  │3:00  │ │2:00  │ │0:30  │ │5:00  │                           │
│  └──────┘ └──────┘ └──────┘ └──────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

### UI Components:
1. **ACE-Step status bar** — shows connection status, model info, start server button
2. **Style tags input** — text input with clickable quick-tag chips
3. **Lyrics textarea** — multi-line with structure markers ([Verse], [Chorus], etc.)
4. **"Expand with AI" button** — calls `/format_input` to have the LM flesh out sparse input
5. **Duration presets** — radio buttons matching MUSIC_DURATION_PRESETS
6. **Advanced settings** — collapsible: seed, thinking toggle, inference steps, guidance scales
7. **Generate button** — primary action
8. **Audio player** — HTML5 audio with play/pause/seek/download
9. **Generation history** — horizontal strip of recent generations (like image/video tabs)
10. **Progress indicator** — during generation, show status from poll responses

### Key behaviors:
- On tab switch to Music, check ACE-Step backend status
- If not connected, show setup instructions with link to docs
- Quick tags are clickable chips that append to the style tags input
- "Expand with AI" calls format_input and fills/replaces the lyrics textarea
- Generate submits to ACE-Step, polls until complete, auto-plays result
- History persists within session (list of dicts with path, tags, duration, seed)

---

## Task 4: Rename Residuals

Search and replace any remaining "Forge" references in the codebase:
- Variable names like `forge_*` → `neovak_*`
- CSS class names `.forge-*` → `.neovak-*`
- Comments referencing "Forge"
- File output prefixes (already mostly `neovak_` but verify)

Use: `grep -rn "forge" --include="*.py" --include="*.css" --include="*.json" .`

Do NOT rename the `/forge/` design docs directory in Claude_Technical — those are historical.

---

## Task 5: Create helper scripts and docs

### `start_acestep.sh`:
```bash
#!/bin/bash
# Start ACE-Step 1.5 API server for NeoVak
ACESTEP_DIR="${ACESTEP_DIR:-$HOME/ACE-Step-1.5}"

if [ ! -d "$ACESTEP_DIR" ]; then
    echo "ACE-Step not found. Installing..."
    cd "$HOME"
    git clone https://github.com/ACE-Step/ACE-Step-1.5.git
    cd ACE-Step-1.5
    # Use their macOS script which handles MLX backend
    chmod +x start_api_server_macos.sh
fi

cd "$ACESTEP_DIR"
./start_api_server_macos.sh
```

### `docs/ACESTEP_SETUP.md`:
Quick setup guide:
1. Clone ACE-Step 1.5
2. Run `start_api_server_macos.sh` (auto-installs deps, downloads models)
3. Verify at http://localhost:8001/health
4. Launch NeoVak — Music tab should show "Connected"

---

## Task 6: Update `neovak_config.example.json`

Add ACE-Step configuration:
```json
{
    "comfyui_url": "http://127.0.0.1:8188",
    "acestep_url": "http://127.0.0.1:8001",
    "acestep_dir": "~/ACE-Step-1.5",
    "output_dir": "./output",
    "model_paths": []
}
```

---

## Testing Checklist

- [ ] `acestep_client.py` can connect to ACE-Step API and report status
- [ ] Music tab shows correct connection status
- [ ] Style tags input works with quick-tag chips
- [ ] Lyrics input supports structure markers
- [ ] "Expand with AI" calls format_input successfully
- [ ] Generate button submits task and polls to completion
- [ ] Audio player loads and plays generated music
- [ ] Download button works
- [ ] Seed copy works
- [ ] History strip populates with generations
- [ ] Duration presets map to correct seconds
- [ ] Advanced settings (seed, thinking, steps, guidance) pass through
- [ ] Graceful handling when ACE-Step not running
- [ ] No remaining "Forge" references in Python/CSS/JSON
- [ ] Other tabs (Image, Video, Voice, SFX) still work normally
- [ ] Config file supports acestep_url override

---

## Dependencies / Prerequisites

**ALREADY DONE (April 11, 2026):**
- [x] ACE-Step 1.5 cloned at `~/ACE-Step-1.5`
- [x] Models downloaded (13GB in checkpoints/)
- [x] ffmpeg installed via homebrew (`/opt/homebrew/bin/ffmpeg` v8.1)
- [x] ffmpeg symlinked into ACE-Step venv: `ln -sf /opt/homebrew/bin/ffmpeg ~/ACE-Step-1.5/.venv/bin/ffmpeg`
- [x] API server tested end-to-end — generates MP3 files successfully
- [x] Server starts via: `cd ~/ACE-Step-1.5 && ./start_api_server_macos.sh`

**IMPORTANT:** The server must be started with `/opt/homebrew/bin` on PATH for MP3 export.
The symlink in .venv/bin/ handles this when the server uses its own Python.

---

## Notes

- ACE-Step uses `uv` for package management. It has its own venv/environment. NeoVak's venv stays separate.
- The macOS scripts auto-detect Apple Silicon and use MLX backend for the LM component, PyTorch+MPS for DiT.
- Mac Studio with 192GB RAM (tier: studio) can easily run ACE-Step + ComfyUI simultaneously.
- ACE-Step XL models (4B DiT) need ≥12GB VRAM — fine for Mac Studio, tight on MacBook Pro 16GB.
- The REST API is async task-based (submit → poll), NOT streaming. Plan UI accordingly.
- ACE-Step's `/format_input` endpoint is a killer feature — lets the LM "think" about the music before generating. This should be prominent in the UI.

## Related

- [[SE_Post_Image_Generation_Spec]]
- [[Moltbook_Post_Community_Music]]
- [[SPRINT_VIDEO_CHAIN]]
- [[SPRINT_LUMINA_WORLD]]
- [[SPRINT_ENHANCEMENTS]]
