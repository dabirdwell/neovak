#!/usr/bin/env python3
"""
NeoVak MCP Server: Local AI Media Generation for Apple Silicon
Exposes image, video, speech, and music generation as MCP tools.

Image: MLX + Flux via mflux (native Apple Silicon)
Video: ComfyUI + LTX-Video (background jobs)
Speech: TBD (Kokoro/Bark via MLX)
Music: TBD (ACE-Step/MusicGen)

Install: pip install mflux "mcp[cli]"
Run: python3 neovak_server.py
Config: Add to ~/Library/Application Support/Claude/claude_desktop_config.json
"""
import os, json, time, subprocess, uuid, asyncio
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP

VENV_BIN = Path(__file__).parent / "venv" / "bin"
MFLUX = str(VENV_BIN / "mflux-generate")

def make_thumbnail(src_path, max_size=384):
    """Create a small thumbnail for inline preview."""
    thumb_path = src_path.replace(".png", "_thumb.png")
    subprocess.run([
        str(VENV_BIN / "python3"), "-c",
        f"from PIL import Image; im=Image.open('{src_path}'); im.thumbnail(({max_size},{max_size})); im.save('{thumb_path}')"
    ], capture_output=True)
    return thumb_path

def open_in_preview(path, force=False):
    """Open full-size image in macOS Preview.app.

    SILENCED BY DEFAULT (ruled 2026-07-16): a headless sprint that
    generated a deck of covers threw a dozen Preview windows at him mid-work.
    Auto-open is now OPT-IN. It fires only when:
      • force=True is passed (an interactive call: "we're working on this together"), or
      • the NEOVAK_PREVIEW env var is set to 1/true/yes.
    The explicit `open_editor` tool is unaffected: that IS the "show me" verb.
    """
    if not force and os.environ.get("NEOVAK_PREVIEW", "").lower() not in ("1", "true", "yes"):
        return False
    subprocess.Popen(["open", "-a", "Preview", path])
    return True

# === Configuration ===
# Every folder and outside tool comes from the settings file (neovak_queue/settings.py).
# NEOVAK_OUTPUT_DIR still lets a test copy write somewhere other than the real output folder.
from neovak_queue import settings as _settings  # noqa: E402
SETTINGS = _settings.load()
OUTPUT_DIR = SETTINGS.output_dir
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE = Path(__file__).parent / "jobs.json"

MODEL_DIR = SETTINGS.model_dir
# Do not create the model folder at import time: if the volume is not mounted the
# mkdir raises PermissionError and the whole server fails to start (seen on a laptop,
# Aug 8 sprint report). Create it lazily, and tolerate its absence.
try:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError):
    pass
os.environ.setdefault("HF_HOME", str(MODEL_DIR / "huggingface"))
os.environ.setdefault("MFLUX_CACHE_DIR", str(MODEL_DIR))

# === Style Presets ===
STYLES = {
    # General
    "editorial": "professional editorial photography, clean composition, natural lighting, magazine quality",
    "cinematic": "cinematic film still, dramatic lighting, shallow depth of field, 35mm film grain",
    "illustration": "digital illustration, clean lines, vibrant colors, professional concept art",
    "documentary": "documentary photography, candid, natural, authentic, photojournalistic",
    "technical": "technical diagram, clean white background, precise, labeled, professional",
}
# A household can add its own looks in a file beside the settings file: ~/.config/neovak/styles.json,
# a JSON object of name to words. They join the list above and are never part of the code.
try:
    import json as _json
    _own = Path(SETTINGS.path).with_name("styles.json")
    if _own.is_file():
        STYLES.update({str(k): str(v) for k, v in _json.loads(_own.read_text()).items() if str(k).replace("_", "").isalnum()})
except (OSError, ValueError, AttributeError):
    pass

SIZES = {
    "square": (1024, 1024),
    "wide": (1344, 768),
    "tall": (768, 1344),
    "portrait": (896, 1152),
    "landscape": (1152, 896),
    "banner": (1536, 512),
}

# === Job tracking for background tasks ===
def load_jobs():
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text())
    return {}

def save_job(job_id, data):
    jobs = load_jobs()
    jobs[job_id] = data
    JOBS_FILE.write_text(json.dumps(jobs, indent=2))
    return job_id

# === Server ===
mcp = FastMCP("NeoVak", json_response=True)

@mcp.tool()
def generate_image(
    prompt: str,
    style: str = "editorial",
    size: str = "landscape",
    model: str = "z-image-turbo",
    steps: int = 0,
    seed: int = -1,
    quantize: int = 0,
) -> dict:
    """Generate an image using Flux on local Apple Silicon via MLX.
    
    Args:
        prompt: What to generate. Be descriptive.
        style: Preset style. Options: editorial, cinematic, illustration, documentary, technical, inference, foundation, phoenix_wells, show, lumina, structured_emergence, oklahoma, moltbook.
        size: Image dimensions. Options: square, wide, tall, portrait, landscape, banner.
        model: One of z-image-turbo (default), z-image, flux2-klein-4b (fastest), schnell (FLUX.1 fast draft), dev (FLUX.1 dev), krea-dev (FLUX.1 Krea dev), qwen (Qwen-Image, best text in the picture), fibo (FIBO). Each really runs its own weights.
        steps: Inference steps. 0 = the model's usual count.
        seed: Random seed. -1 for random.
        quantize: Quantization level (0=none, 4/6/8 for GGUF quant). 0 recommended for 64GB.
    
    Returns:
        dict with path to generated image, seed used, and generation time.
    """
    if QUEUE is not None:
        return _run_via_queue("mflux", dict(prompt=prompt, style=style, size=size, model=model,
                              steps=steps, seed=seed, quantize=quantize, mode="standard"),
                              note="Thumbnail available for inline display.")
    from neovak_queue.adapters.mflux_image import ENGINE_MODELS, engine_command
    from neovak_queue.adapters.base import AdapterError as _AdapterError
    try:
        head = engine_command(VENV_BIN, MODEL_DIR, model, quantize)
    except _AdapterError as e:
        return {"error": str(e)}

    style_suffix = STYLES.get(style, "")
    full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt
    w, h = SIZES.get(size, (1024, 1024))
    
    # Auto-set steps
    if steps == 0:
        steps = ENGINE_MODELS[model]["steps"]
    
    actual_seed = seed if seed >= 0 else int(time.time()) % 100000
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"neovak_{timestamp}_{actual_seed}.png"
    output_path = str(OUTPUT_DIR / filename)
    
    cmd = head + [
        "--prompt", full_prompt,
        "--seed", str(actual_seed),
        "--height", str(h),
        "--width", str(w),
        "--steps", str(steps),
        "--output", output_path,
    ]
    
    start = time.time()
    env = os.environ.copy()
    env["HF_HOME"] = str(MODEL_DIR / "huggingface")
    
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    elapsed = round(time.time() - start, 1)
    
    if result.returncode != 0:
        return {"error": result.stderr[-500:] if result.stderr else "Unknown error", "command": " ".join(cmd)}
    
    # Create thumbnail for inline preview. Auto-open is opt-in (see open_in_preview).
    thumb_path = make_thumbnail(output_path)
    open_in_preview(output_path)
    
    return {
        "path": output_path,
        "thumbnail": thumb_path,
        "seed": actual_seed,
        "prompt": full_prompt,
        "size": f"{w}x{h}",
        "model": model,
        "steps": steps,
        "time_seconds": elapsed,
        "note": "Full image opened in Preview. Thumbnail available for inline display."
    }

@mcp.tool()
def generate_image_fast(
    prompt: str,
    style: str = "editorial",
    size: str = "landscape",
    seed: int = -1,
) -> dict:
    """Generate an image using Flux 2 Klein 4B: fastest model, ~10-15s.
    Good for quick iteration and exploring ideas before committing to a full Flux Dev render.
    
    Args:
        prompt: What to generate.
        style: Style preset (same options as generate_image).
        size: Image size (same options as generate_image).
        seed: Random seed. -1 for random.
    """
    if QUEUE is not None:
        return _run_via_queue("mflux", dict(prompt=prompt, style=style, size=size, seed=seed,
                                            mode="fast"))
    MFLUX = str(Path(__file__).parent / "venv" / "bin" / "mflux-generate-flux2")
    style_suffix = STYLES.get(style, "")
    full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt
    w, h = SIZES.get(size, (1024, 1024))
    actual_seed = seed if seed >= 0 else int(time.time()) % 100000
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"neovak_klein_{timestamp}_{actual_seed}.png"
    output_path = str(OUTPUT_DIR / filename)

    cmd = [MFLUX, "--base-model", "flux2-klein-4b", "--prompt", full_prompt,
           "--seed", str(actual_seed), "--height", str(h), "--width", str(w),
           "--steps", "4", "--output", output_path]
    
    start = time.time()
    env = os.environ.copy()
    env["HF_HOME"] = str(MODEL_DIR / "huggingface")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    elapsed = round(time.time() - start, 1)
    
    if result.returncode != 0:
        return {"error": result.stderr[-500:] if result.stderr else "Unknown error"}
    return {"path": output_path, "seed": actual_seed, "prompt": full_prompt,
            "size": f"{w}x{h}", "model": "flux2-klein-4b", "time_seconds": elapsed}

@mcp.tool()
def edit_image_with_prompt(
    image_path: str,
    prompt: str,
    seed: int = -1,
) -> dict:
    """Edit an existing image using Flux Kontext: describe what to change.
    Example: 'change the sky to sunset' or 'add a red barn in the background'.
    
    Args:
        image_path: Path to the input image to edit.
        prompt: Description of the desired edit.
        seed: Random seed. -1 for random.
    """
    if QUEUE is not None:
        return _run_via_queue("kontext", dict(source=image_path, prompt=prompt, seed=seed))
    MFLUX = str(Path(__file__).parent / "venv" / "bin" / "mflux-generate-kontext")
    actual_seed = seed if seed >= 0 else int(time.time()) % 100000
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"neovak_edit_{timestamp}_{actual_seed}.png"
    output_path = str(OUTPUT_DIR / filename)
    
    cmd = [MFLUX, "--prompt", prompt, "--image-path", image_path,
           "--seed", str(actual_seed), "--steps", "8", "--output", output_path]
    
    start = time.time()
    env = os.environ.copy()
    env["HF_HOME"] = str(MODEL_DIR / "huggingface")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    elapsed = round(time.time() - start, 1)
    
    if result.returncode != 0:
        return {"error": result.stderr[-500:] if result.stderr else "Unknown error"}
    return {"path": output_path, "seed": actual_seed, "prompt": prompt,
            "source_image": image_path, "time_seconds": elapsed}

@mcp.tool()
def upscale_image(
    image_path: str,
    seed: int = -1,
) -> dict:
    """Upscale an image using SeedVR2 AI upscaler via mflux.
    
    Args:
        image_path: Path to the image to upscale.
        seed: Random seed. -1 for random.
    """
    if QUEUE is not None:
        return _run_via_queue("seedvr2", dict(source=image_path, seed=seed))
    MFLUX = str(Path(__file__).parent / "venv" / "bin" / "mflux-upscale-seedvr2")
    actual_seed = seed if seed >= 0 else int(time.time()) % 100000
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"neovak_upscaled_{timestamp}.png"
    output_path = str(OUTPUT_DIR / filename)
    
    cmd = [MFLUX, "--image-path", image_path, "--seed", str(actual_seed),
           "--output", output_path]
    
    start = time.time()
    env = os.environ.copy()
    env["HF_HOME"] = str(MODEL_DIR / "huggingface")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    elapsed = round(time.time() - start, 1)
    
    if result.returncode != 0:
        return {"error": result.stderr[-500:] if result.stderr else "Unknown error"}
    return {"path": output_path, "source_image": image_path, "time_seconds": elapsed}

@mcp.tool()
def generate_with_lora(
    prompt: str,
    lora_style: str = "illustration",
    size: str = "landscape",
    seed: int = -1,
) -> dict:
    """Generate an image with a built-in LoRA style applied.
    
    Args:
        prompt: What to generate.
        lora_style: LoRA preset. Options: couple, font, home, identity, illustration, portrait, ppt, sandstorm, sparklers, storyboard.
        size: Image size preset.
        seed: Random seed. -1 for random.
    """
    # This tool used to pass --base-model dev to mflux-generate-flux2, which made a plain FLUX.2
    # klein picture and ignored the style. The ten named styles are in-context LoRAs that mflux
    # would have to fetch, and the files are not on this machine. Say so instead of faking it.
    return {"error": "The built-in LoRA styles need files that are not on this machine, so "
                     "nothing was generated. Use generate_image with a style preset instead.",
            "lora_style": lora_style, "seed": seed}

@mcp.tool()
def check_models() -> dict:
    """Check which models are downloaded and ready to use.
    
    Returns:
        dict with status of each model (downloaded, size, location).
    """
    models = {}
    # Check saved/quantized models
    saved_dir = MODEL_DIR
    for d in saved_dir.glob("flux-*"):
        if d.is_dir():
            size_mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / (1024*1024)
            models[d.name] = {"status": "ready", "size_mb": round(size_mb), "path": str(d)}
    
    # Check HF cache
    hub_dir = MODEL_DIR / "huggingface" / "hub"
    if hub_dir.exists():
        for d in hub_dir.glob("models--*"):
            name = d.name.replace("models--", "").replace("--", "/")
            size_mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / (1024*1024)
            models[name] = {"status": "cached", "size_mb": round(size_mb), "path": str(d)}
    
    # Check output directory
    output_count = len(list(OUTPUT_DIR.glob("*.png")))
    
    return {"models": models, "output_dir": str(OUTPUT_DIR), "images_generated": output_count}

@mcp.tool()
def open_editor(image_path: str) -> dict:
    """Open the NeoVak visual editor for mask painting and inpainting.
    Opens a browser-based tool where you can paint masks over areas to edit,
    enter a prompt, and generate edits. The editor communicates back to NeoVak.
    
    Args:
        image_path: Path to the image to edit.
    
    Returns:
        dict confirming editor opened.
    """
    editor_path = Path(__file__).parent / "editor.html"
    url = f"file://{editor_path}?image={image_path}"
    subprocess.Popen(["open", url])
    return {
        "status": "editor_opened",
        "url": url,
        "image": image_path,
        "instructions": "Paint mask over areas to edit. Enter a prompt. Click 'Save Mask & Generate'."
    }

@mcp.tool()
def generate_video(
    prompt: str,
    duration: float = 5.0,
    size: str = "landscape",
    image_path: str = "",
    seed: int = -1,
) -> dict:
    """Start a short video with LTX-2.3 in the background, from a description, or from a picture
    and a description. A clip takes several minutes. Check it with check_job().
    
    Args:
        prompt: What happens in the clip.
        duration: Length in seconds (1-10).
        size: Shape of the clip: landscape, portrait or square. A picture sets its own shape.
        image_path: Optional picture to start from, inside the output folder.
        seed: Random seed. -1 for random.
    
    Returns:
        dict with job_id to track progress.
    """
    if QUEUE is None:
        return {"status": "unavailable", "message": "Video needs the job queue, which is switched off in this server. Nothing was started."}
    params = dict(prompt=prompt, seconds=duration, size=size, seed=seed)
    if image_path:
        params["source"] = image_path
    try:
        v = QUEUE.submit("ltx-video", params, client="tool")
    except AdapterError as e:
        return {"error": str(e)}
    return {"job_id": v["id"], "status": v["state"], "estimate_seconds": v["progress"].get("estimate_seconds"),
            "output": (v.get("outputs") or [None])[0], "message": "Started. Check it with check_job."}

@mcp.tool()
def generate_speech(
    text: str,
    voice: str = "kokoro",
    speed: float = 1.0,
    speaker: int = 0,
) -> dict:
    """Generate speech audio from text using local MLX TTS models.
    
    Args:
        text: Text to speak. Keep under ~200 words for best quality.
        voice: TTS model. Options:
            fish-s2-pro: BEST quality (4B), 15000+ emotion tags, voice cloning, multi-speaker, broadcast-ready
            kokoro: fastest (82M), 54 presets, professional tone, best for quick drafts
            chatterbox: expressive (1.6B), emotional delivery, voice cloning, best for shows/fiction
            csm-1b: conversational (1B), voice cloning
            qwen3-tts: multilingual (1.7B), voice design via natural language description
        speed: Speech speed multiplier (0.5-2.0).
        speaker: Speaker ID for models that support it.
    
    Returns:
        dict with path to generated WAV file.
    """
    if QUEUE is not None:
        return _run_via_queue("mlx-audio", dict(text=text, voice=voice, speed=speed, speaker=speaker))
    PYTHON = str(VENV_BIN / "python3")
    models = {
        "fish-s2-pro": "mlx-community/fish-audio-s2-pro-bf16",
        "kokoro": "mlx-community/Kokoro-82M-bf16",
        "chatterbox": "mlx-community/chatterbox-fp16",
        "csm-1b": "mlx-community/csm-1b",
        "qwen3-tts": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    }
    model = models.get(voice, models["csm-1b"])
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = str(OUTPUT_DIR / f"speech_{timestamp}")
    
    cmd = [
        PYTHON, "-m", "mlx_audio.tts.generate",
        "--model", model,
        "--text", text,
        "--output", output_dir,
    ]
    
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)
    
    if result.returncode != 0:
        return {"error": result.stderr[-500:] if result.stderr else "Unknown error"}
    
    # mlx-audio saves as output_dir/audio_000.wav: find and rename
    import glob
    wav_files = glob.glob(f"{output_dir}/*.wav")
    if wav_files:
        final_path = str(OUTPUT_DIR / f"neovak_speech_{timestamp}.wav")
        os.rename(wav_files[0], final_path)
        # Clean up the temp directory
        try:
            os.rmdir(output_dir)
        except:
            pass
    else:
        return {"error": "No audio file generated"}
    
    # Auto-open in QuickTime: the same opt-in rule as images (ruled 2026-07-16).
    if os.environ.get("NEOVAK_PREVIEW", "").lower() in ("1", "true", "yes"):
        subprocess.Popen(["open", final_path])
    
    return {
        "path": final_path,
        "text": text[:100] + ("..." if len(text) > 100 else ""),
        "voice": voice,
        "time_seconds": elapsed,
        "note": "Audio opened in default player."
    }

@mcp.tool()
def generate_music(
    prompt: str,
    duration: float = 30.0,
    genre: str = "ambient",
    lyrics: str = "[inst]",
) -> dict:
    """Start a music generation job in the background: MiniMax-Music3 (4-bit, MLX) on the Studio.
    Returns a job_id at once; check it with check_job(job_id). A 30-second piece takes a few minutes.
    If the Studio is short of memory (the model governor says NO-GO), the job ends as "blocked" and
    nothing runs. Wired 2026-10-15; the work is done by music_job.py beside
    this file, from its own venv, so this server's venv is never touched.

    Args:
        prompt: Description of the music: instruments, mood, tempo.
        duration: Length in seconds (5 to 180).
        genre: Style hint added to the description, e.g. ambient, electronic, acoustic, cinematic.
        lyrics: "[inst]" for instrumental (the default), or lyrics to sing.

    Returns:
        dict with job_id to track progress and the path the WAV will be written to.
    """
    if QUEUE is not None:
        try:
            v = QUEUE.submit("minimax-music", dict(prompt=prompt, duration=duration, genre=genre,
                                                   lyrics=lyrics), client="generate_music")
        except AdapterError as e:
            return {"error": str(e)}
        return {"job_id": v["id"], "status": "queued", "output": v["outputs"][0],
                "message": "Music job queued. Check it with check_job(job_id) or job_status(job_id); "
                           "a 30-second piece takes a few minutes."}
    duration = max(5.0, min(float(duration), 180.0))
    job_id = str(uuid.uuid4())[:8]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = str(OUTPUT_DIR / f"neovak_music_{stamp}_{job_id}.wav")
    caption = f"{genre} music. {prompt}" if genre else prompt
    save_job(job_id, {"type": "music", "status": "queued", "prompt": prompt, "genre": genre,
                      "duration": duration, "started": datetime.now().isoformat(), "path": out})
    subprocess.Popen(["/opt/homebrew/bin/python3", str(Path(__file__).resolve().parent / "music_job.py"),
                      job_id, out, str(duration), caption, lyrics],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"job_id": job_id, "status": "queued", "output": out,
            "message": "Music job started. Check it with check_job(job_id); a 30-second piece takes a few minutes."}

@mcp.tool()
def check_job(job_id: str) -> dict:
    """Check status of a background generation job.
    
    Args:
        job_id: The job ID returned by generate_video or generate_music.
    
    Returns:
        dict with current status and output path if complete.
    """
    jobs = load_jobs()
    if job_id in jobs:
        return jobs[job_id]
    if QUEUE is not None and QUEUE.get(job_id):
        return _check_job_shape(QUEUE.status(job_id))
    return {"status": "not_found", "message": f"No job with ID {job_id}"}

def _image_models():
    from neovak_queue.adapters.mflux_image import ENGINE_MODELS
    return ENGINE_MODELS


@mcp.tool()
def list_presets() -> dict:
    """List available style presets, sizes, and capabilities.
    
    Returns:
        dict with all available options for image generation.
    """
    return {
        "styles": {k: v for k, v in STYLES.items()},
        "sizes": {k: f"{v[0]}x{v[1]}" for k, v in SIZES.items()},
        "models": {k: f"{v['label']} ({v['steps']} steps)" for k, v in _image_models().items()},
        "capabilities": {
            "image": "Ready: FLUX.2 klein, Z-Image, FLUX.1, Qwen-Image, FIBO through mflux",
            "video": "Ready when the job queue is on: LTX-2.3, from a description or a picture, 1 to 10 seconds",
            "speech": "Ready: Kokoro, CSM-1B, Chatterbox, Qwen3-TTS through mlx-audio",
            "music": "Ready: MiniMax-Music3",
        }
    }

# === Job queue (S1, 2026-10-28) ===
# One queue for every lane and every client: neovak_queue/ in this folder.
# OFF unless NEOVAK_QUEUE=1. Claude Desktop loads this file straight from the repo, so with the
# switch off the tool list and behavior stay exactly as before S1 until parity passes
# (S1_PARITY_2026-10-28.md). With it on, generate_image,
# generate_image_fast, generate_speech and generate_music run as queue jobs, check_job also
# reads queue jobs, and five tools are added: submit_job, job_status, cancel_job, list_jobs,
# job_lanes. edit_image_with_prompt and upscale_image also run as queue jobs. generate_with_lora is not queued.
QUEUE = None
QUEUE_ENABLED = os.environ.get("NEOVAK_QUEUE", "").lower() in ("1", "true", "yes")


def _nightly_hold(estimate_seconds=0):
    from neovak_queue.recipes import hold_reason
    return hold_reason(estimate_seconds)


def build_queue(start_worker=None):
    from neovak_queue import JobQueue
    from neovak_queue.adapters import default_adapters
    state_dir = str(SETTINGS.state_dir)  # [folders] state in the settings file; NEOVAK_STATE_DIR still wins for a test copy
    config = {"venv_bin": str(VENV_BIN), "output_dir": str(OUTPUT_DIR), "model_dir": str(MODEL_DIR),
              "styles": STYLES, "sizes": SIZES, "music_python": SETTINGS.tool("music_python"),
              "state_dir": state_dir}  # state_dir: where the text lane keeps measured peaks
    if start_worker is None:
        start_worker = os.environ.get("NEOVAK_QUEUE_WORKER", "1") != "0"
    return JobQueue(
        state_dir=state_dir,
        adapters=default_adapters(config),
        governor=True,  # the memory check the settings file names, or the built-in simple check
        legacy_jobs_file=JOBS_FILE,
        start_worker=start_worker,
        hold=_nightly_hold)


RECIPES = None
if QUEUE_ENABLED:
    from neovak_queue.adapters import AdapterError
    from neovak_queue.recipes import RecipeBook, RecipeError
    QUEUE = build_queue()
    RECIPES = RecipeBook(QUEUE, Path(__file__).resolve().parent / "recipes")


def _run_via_queue(adapter, params, note=None):
    """The old synchronous tools, as queue jobs: submit, wait, answer in the old shape."""
    try:
        v = QUEUE.submit(adapter, params, client="tool")
    except AdapterError as e:
        return {"error": str(e)}
    v = QUEUE.wait(v["id"])
    if v["state"] != "done":
        return {"error": v.get("error") or f"job {v['state']}", "job_id": v["id"], "state": v["state"]}
    out = {k: val for k, val in (v.get("result") or {}).items() if k != "files"}
    out["job_id"] = v["id"]
    if note:
        out["note"] = note
    return out


def _check_job_shape(v):
    """A queue job in the shape check_job has always returned for music jobs."""
    st, stage = v["state"], (v.get("progress") or {}).get("stage")
    if st == "running":
        status = "checking_memory" if stage == "checking memory" else "generating"
    elif st == "failed" and "NO-GO" in (v.get("error") or ""):
        status = "blocked"
    else:
        status = st
    p = v.get("params") or {}
    out = {"type": v.get("lane"), "status": status, "job_id": v["id"],
           "prompt": p.get("prompt") or p.get("text"), "started": v.get("created"),
           "updated": v.get("finished"), "path": (v.get("outputs") or [None])[0],
           "progress": v.get("progress")}
    for k in ("genre", "duration"):
        if k in p:
            out[k] = p[k]
    r = v.get("result") or {}
    if "time_seconds" in r:
        out["time_seconds"] = r["time_seconds"]
    if r.get("message"):
        out["message"] = r["message"]
    if v.get("error"):
        out["error"] = v["error"]
    if status == "blocked":
        out["governor"] = v.get("governor")
    return out


def submit_job(lane: str = "", params: dict | None = None, adapter: str = "") -> dict:
    """Queue a generation job and return at once with its id. One job runs at a time.

    Args:
        lane: image, speech or music today (video, animation and text come later). Picks the
            lane's adapter when there is only one.
        params: The adapter's parameters, e.g. {"prompt": "...", "seed": 7, "mode": "fast"}
            for image or {"text": "...", "voice": "kokoro"} for speech. job_lanes() lists them.
        adapter: Name an adapter directly instead of a lane: mflux, mlx-audio, minimax-music.

    Returns:
        The job: id, state (queued), position, the planned output path, progress.
    """
    try:
        return QUEUE.submit(adapter or None, params or {}, client="mcp", lane=lane or None)
    except AdapterError as e:
        return {"error": str(e), "lanes": QUEUE.describe()["adapters"]}


def job_status(job_id: str) -> dict:
    """A job's state (queued, running, done, failed, cancelled), progress (step, total,
    elapsed_seconds, estimate_seconds, eta_seconds, stage) and, when done, its files.
    Also answers for jobs from before S1 (jobs.json)."""
    return QUEUE.status(job_id)


def cancel_job(job_id: str) -> dict:
    """Cancel a job. A queued job is dropped; a running job's engine process is killed."""
    return QUEUE.cancel(job_id)


def list_jobs(state: str = "", lane: str = "", limit: int = 20) -> dict:
    """Recent jobs, newest first. Filter by state or lane if given."""
    keep = ("id", "lane", "adapter", "state", "created", "finished", "position", "progress",
            "outputs", "error")
    jobs = QUEUE.list(state=state or None, lane=lane or None, limit=limit)
    return {"jobs": [{k: j.get(k) for k in keep if k in j} for j in jobs],
            "worker_here": QUEUE.is_worker}


def job_lanes() -> dict:
    """Every lane and adapter the queue serves, with each adapter's parameters and models."""
    return QUEUE.describe()


def list_recipes() -> dict:
    """The saved recipes: named sets of steps, such as picture, then clip, then narration. Each lists
    what it asks for, the steps it runs, roughly how long it takes and the most memory one step needs."""
    return {"recipes": RECIPES.list()}


def run_recipe(recipe_id: str, values: dict = None) -> dict:
    """Start a recipe. Each step is a job on the queue, and each output gets a sidecar saying how it
    was made. Check it with recipe_status().

    Args:
        recipe_id: An id from list_recipes().
        values: The inputs that recipe asks for, by name. Blank means its default.
    """
    try:
        return RECIPES.start(recipe_id, values or {}, client="mcp")
    except RecipeError as e:
        return {"error": str(e)}


def recipe_status(run_id: str) -> dict:
    """A recipe run: its state, each step's state and progress, and the files made so far."""
    return RECIPES.status(run_id) or {"error": "No recipe run with that id."}


def cancel_recipe(run_id: str) -> dict:
    """Stop a recipe run. The step under way is stopped and later steps do not run. Files already finished are kept."""
    return RECIPES.cancel(run_id) or {"error": "No recipe run with that id."}


def make_animation(text: str = "", template: str = "title", image_path: str = "", look: str = "night", shape: str = "landscape",
                   seconds: float = 5.0, direction: str = "in") -> dict:
    """Start a short animation: a title card, a name strip, words appearing one line at a time, or a
    slow move over a picture. No model is loaded and every letter is exactly as written. Check it
    with check_job().

    Args:
        text: The words. First line is the main line, the second smaller. One line at a time uses each line.
        template: title, strip, lines or move.
        image_path: Optional picture or clip for the background, inside the output folder. Required for move.
        look: night, paper, studio or ember.
        shape: landscape, portrait or square.
        seconds: 2 to 20. A background clip sets its own length.
        direction: For move: in, out, left or right.

    Returns:
        dict with job_id to track progress and where the file will be.
    """
    params = dict(template=template, text=text, look=look, shape=shape, seconds=seconds, direction=direction)
    if image_path:
        params["source"] = image_path
    try:
        v = QUEUE.submit("motion", params, client="tool")
    except AdapterError as e:
        return {"error": str(e)}
    return {"job_id": v["id"], "status": v["state"], "estimate_seconds": v["progress"].get("estimate_seconds"),
            "output": (v.get("outputs") or [None])[0], "message": "Started. Check it with check_job."}


def write_text(brief: str, task: str = "script", model: str = "9b", length: int = 60, tone: str = "plain", target: str = "image", about: str = "") -> dict:
    """Write with a local language model, through the queue: a narration script, three captions, or a
    better prompt. Waits until the writing is finished and returns it. No token limit is set.

    Args:
        brief: What to write about, or the prompt to improve.
        task: script, caption or rewrite.
        model: 9b (quick) or 27b (careful, needs about 42 GB free).
        length: For a script, the spoken length in seconds: 30, 60, 120 or 300.
        tone: For a script: plain, warm, serious or playful.
        target: For a rewrite: image, video, music or voice.
        about: For captions: a description of the picture or clip.

    Returns:
        dict with the text, and the file it was saved to unless it is a rewrite.
    """
    return _run_via_queue("local-text", dict(task=task, brief=brief, model=model, length=length, tone=tone, target=target, about=about))


if QUEUE is not None:
    for _tool in (submit_job, job_status, cancel_job, list_jobs, job_lanes, make_animation, write_text,
                  list_recipes, run_recipe, recipe_status, cancel_recipe):
        mcp.tool()(_tool)


if __name__ == "__main__":
    import sys
    if "--http" in sys.argv:
        # HTTP mode: REST API for local models, other computers on your own network, scripts
        port = 8100
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        import uvicorn
        
        async def rest_generate(request):
            data = await request.json()
            result = generate_image(
                prompt=data.get("prompt", ""),
                style=data.get("style", "editorial"),
                size=data.get("size", "landscape"),
                model=data.get("model", "schnell"),
                steps=data.get("steps", 0),
                seed=data.get("seed", -1),
            )
            return JSONResponse(result)
        
        async def rest_generate_fast(request):
            data = await request.json()
            result = generate_image_fast(
                prompt=data.get("prompt", ""),
                style=data.get("style", "editorial"),
                size=data.get("size", "landscape"),
                seed=data.get("seed", -1),
            )
            return JSONResponse(result)
        
        async def rest_edit(request):
            data = await request.json()
            result = edit_image_with_prompt(
                image_path=data.get("image_path", ""),
                prompt=data.get("prompt", ""),
                seed=data.get("seed", -1),
            )
            return JSONResponse(result)
        
        async def rest_presets(request):
            return JSONResponse(list_presets())
        
        async def rest_models(request):
            return JSONResponse(check_models())
        
        async def rest_health(request):
            return JSONResponse({"status": "ok", "server": "NeoVak", "port": port})
        
        app = Starlette(routes=[
            Route("/api/generate", rest_generate, methods=["POST"]),
            Route("/api/generate/fast", rest_generate_fast, methods=["POST"]),
            Route("/api/edit", rest_edit, methods=["POST"]),
            Route("/api/presets", rest_presets),
            Route("/api/models", rest_models),
            Route("/health", rest_health),
        ])
        
        print(f"NeoVak REST API on http://localhost:{port}")
        print(f"  Generate:  POST /api/generate")
        print(f"  Fast:      POST /api/generate/fast")
        print(f"  Edit:      POST /api/edit")
        print(f"  Presets:   GET  /api/presets")
        print(f"  Models:    GET  /api/models")
        print(f"  Health:    GET  /health")
        print(f"  Output:    {OUTPUT_DIR}")
        
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        # stdio mode: Claude Desktop launches this as subprocess
        mcp.run()
